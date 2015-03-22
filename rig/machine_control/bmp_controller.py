from six import itervalues

import struct
import collections

import socket

import trollius
from trollius import From, Return

from .scp_protocol import SCPProtocol

from . import consts

from .consts import SCPCommands, LEDAction, BMPInfoType, BMP_V_SCALE_2_5, \
    BMP_V_SCALE_3_3, BMP_V_SCALE_12, BMP_TEMP_SCALE, BMP_MISSING_TEMP, \
    BMP_MISSING_FAN

from rig.utils.contexts import ContextMixin, Required
from rig.utils.look_blocking import LookBlockingMixin


class BMPController(ContextMixin, LookBlockingMixin):
    """Control the BMPs (Board Management Processors) onboard SpiNN-5 boards in
    a SpiNNaker machine.

    BMPs (and thus boards) are addressed as follows::

                  2             1                0
        Cabinet --+-------------+----------------+
                  |             |                |
        +-------------+  +-------------+  +-------------+    Frame
        |             |  |             |  |             |      |
        | +---------+ |  | +---------+ |  | +---------+ |      |
        | | : : : : | |  | | : : : : | |  | | : : : : |--------+ 0
        | | : : : : | |  | | : : : : | |  | | : : : : | |      |
        | +---------+ |  | +---------+ |  | +---------+ |      |
        | | : : : : | |  | | : : : : | |  | | : : : : |--------+ 1
        | | : : : : | |  | | : : : : | |  | | : : : : | |      |
        | +---------+ |  | +---------+ |  | +---------+ |      |
        | | : : : : | |  | | : : : : | |  | | : : : : |--------+ 2
        | | : : : : | |  | | : : : : | |  | | : : : : | |      |
        | +---------+ |  | +---------+ |  | +---------+ |      |
        | | : : : : | |  | | : : : : | |  | | : : : : |--------+ 3
        | | : : : : | |  | | : : : : | |  | | : : : : | |
        | +---------+ |  | +|-|-|-|-|+ |  | +---------+ |
        |             |  |  | | | | |  |  |             |
        +-------------+  +--|-|-|-|-|--+  +-------------+
                            | | | | |
                 Board -----+-+-+-+-+
                            4 3 2 1 0

    Coordinates are conventionally written as 3-tuples of integers (cabinet,
    frame, board). This gives the upper-right-most board's coordinate (0, 0,
    0).

    Communication with BMPs is facilitated either directly via Ethernet or
    indirectly via the Ethernet connection of another BMP and the CAN bus in
    the backplane of each frame.

    This class aims not to be a complete BMP communication solution (users are
    referred instead to the general-purpose `bmpc` utility), but rather to
    cover common uses of the BMP in normal application usage.
    """

    def __init__(self, hosts, scp_port=consts.SCP_PORT, n_tries=5, timeout=1.5,
                 initial_context={"cabinet": 0, "frame": 0, "board": 0},
                 loop=None):
        """Create a new controller for BMPs in a SpiNNaker machine.

        Parameters
        ----------
        hosts : string or {coord: string, ...}
            Hostname or IP address of the BMP to connect to or alternatively,
            multiple addresses can be given in a dictionary to allow control of
            many boards. `coord` may be given as ether (cabinet, frame) or
            (cabinet, frame, board) tuples. In the former case, the address
            will be used to communicate with all boards in the specified frame
            except those listed explicitly. If only a single hostname is
            supplied it is assumed to be for all boards in cabinet 0, frame 0.
        scp_port : int
            Port number to use for all SCP connections
        n_tries : int
            Number of SDP packet retransmission attempts.
        timeout : float
            SDP response timeout.
        initial_context : `{argument: value}`
            Dictionary of default arguments to pass to methods in this class.
            This defaults to selecting the coordinate (0, 0, 0) which is
            convenient in single-board systems.
        loop : :py:class:`asyncio.BaseEventLoop` or None
            If you're using BMPController in an asynchronous fashion, this
            argument can be used to specify the event loop to use. If
            unspecified, the default trollius event loop will be used.
        """
        # Initialise the context stack
        ContextMixin.__init__(self, initial_context)

        # Setup event loop
        LookBlockingMixin.__init__(self, loop)

        # Record paramters
        self.scp_port = scp_port
        self.n_tries = n_tries
        self.timeout = timeout
        self._scp_data_length = None

        # Create connections
        self.connections = {}
        if isinstance(hosts, str):
            hosts = {(0, 0): hosts}
        self.connect_to_hosts(hosts)

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    def connect_to_hosts(self, hosts):
        """Create connections to the supplied set of hosts.

        .. note::
            This function has an all-or-nothing behaviour: if any connection
            cannot be made, all already-successful connections will be closed
            and further connection attempts cancelled.

        .. warning::
            If a connection already exists for one of the coordinates/hosts
            supplied, the behaviour of this method is undefined.

        Parameters
        ----------
        hosts : {coord: hostname, ...}
            `coord` may be given as ether (cabinet, frame) or (cabinet, frame,
            board) tuples. In the former case, the address will be used to
            communicate with all boards in the specified frame except those
            listed explicitly.
        """
        # Open connections to all boards in parallel (enforcing the maximum
        # number of outstanding connections to one since BMPs do not handle
        # multiple outstanding connections correctly).
        connection_requests = [
            self.loop.create_datagram_endpoint(
                lambda: SCPProtocol(loop=self.loop,
                                    max_outstanding=1,
                                    n_tries=self.n_tries,
                                    timeout=self.timeout),
                remote_addr=(remote_addr, self.scp_port),
                family=socket.AF_INET)
            for remote_addr in itervalues(hosts)
        ]

        # Ensure all connections were successful
        responses = yield From(trollius.gather(*connection_requests,
                                               loop=self.loop,
                                               return_exceptions=True))

        exc = None
        connections = {}
        for coord, response in zip(hosts, responses):
            if isinstance(response, Exception) and exc is None:
                # Record the first exception
                exc = response
            else:
                # Keep a reference to the protocol
                connections[coord] = response[1]

        # If anything failed, kill all the connections and re-raise the
        # exception, otherwise add the protocols to the set of connections
        if exc is None:
            self.connections.update(connections)
        else:
            for protocol in itervalues(connections):
                protocol.close()
            raise exc

    def __call__(self, **context_args):
        """Create a new context for use with `with`."""
        return self.get_new_context(**context_args)

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    @ContextMixin.use_named_contextual_arguments(
        cabinet=Required, frame=Required, board=Required)
    def send_scp(self, *args, **kwargs):
        """Transmit an SCP Packet to a specific board.

        Automatically determines the appropriate connection to use.

        See the arguments for
        :py:meth:`~rig.machine_control.scp_protocol.SCPProtocol.send_scp` for
        details.

        Parameters
        ----------
        cabinet : int
        frame : int
        board : int
        """
        # Retrieve contextual arguments from the keyword arguments.  The
        # context system ensures that these values are present.
        cabinet = kwargs.pop("cabinet")
        frame = kwargs.pop("frame")
        board = kwargs.pop("board")
        return self._send_scp(cabinet, frame, board, *args, async=True,
                              **kwargs)

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    def _send_scp(self, cabinet, frame, board, *args, **kwargs):
        """Determine the best connection to use to send an SCP packet and use
        it to transmit.

        See the arguments for
        :py:meth:`~rig.machine_control.scp_protocol.SCPProtocol.send_scp` for
        details.
        """
        # Find the connection which best matches the specified coordinates,
        # preferring direct connections to a board when available.
        connection = self.connections.get((cabinet, frame, board), None)
        if connection is None:
            connection = self.connections.get((cabinet, frame), None)
        assert connection is not None, \
            "No connection available to ({}, {}, {})".format(cabinet,
                                                             frame,
                                                             board)

        return connection.send_scp(0, 0, board, *args, **kwargs)

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    @ContextMixin.use_contextual_arguments
    def get_software_version(self, cabinet=Required, frame=Required,
                             board=Required):
        """Get the software version for a given BMP.

        Returns
        -------
        :py:class:`.BMPInfo`
            Information about the software running on a BMP.
        """
        sver = yield From(self._send_scp(cabinet, frame, board,
                                         SCPCommands.sver,
                                         async=True))

        # Format the result
        # arg1
        code_block = (sver.arg1 >> 24) & 0xff
        frame_id = (sver.arg1 >> 16) & 0xff
        can_id = (sver.arg1 >> 8) & 0xff
        board_id = sver.arg1 & 0xff

        # arg2
        version = (sver.arg2 >> 16) / 100.
        buffer_size = (sver.arg2 & 0xffff)

        raise Return(BMPInfo(code_block, frame_id, can_id, board_id, version,
                             buffer_size, sver.arg3,
                             sver.data.decode("utf-8")))

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    @ContextMixin.use_contextual_arguments
    def set_power(self, state, cabinet=Required, frame=Required,
                  board=Required, delay=0.0, post_power_on_delay=5.0):
        """Control power to the SpiNNaker chips and FPGAs on a board.

        Returns
        -------
        state : bool
            True for power on, False for power off.
        board : int or iterable
            Specifies the board to control the power of. This may also be an
            iterable of multiple boards (in the same frame). The command will
            actually be sent to the first board in the iterable.
        delay : float
            Number of seconds delay between power state changes of different
            boards.
        post_power_on_delay : float
            Number of seconds for this command to block once the power on
            command has been carried out. A short delay (default) is useful at
            this point since power-supplies and SpiNNaker chips may still be
            coming on line immediately after the power-on command is sent.
        """
        if isinstance(board, int):
            boards = [board]
        else:
            boards = list(board)
            board = boards[0]

        arg1 = int(delay * 1000) << 16 | (1 if state else 0)
        arg2 = sum(1 << b for b in boards)

        # Allow additional time for response when powering on (since FPGAs must
        # be loaded)
        yield From(self._send_scp(cabinet, frame, board, SCPCommands.power,
                                  arg1=arg1, arg2=arg2,
                                  additional_timeout=(
                                      consts.BMP_POWER_ON_TIMEOUT
                                      if state else 0.0),
                                  expected_args=0, async=True))
        if state:
            yield From(trollius.sleep(post_power_on_delay, loop=self.loop))

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    @ContextMixin.use_contextual_arguments
    def set_led(self, led, action=None, cabinet=Required, frame=Required,
                board=Required):
        """Set or toggle the state of an LED.

        .. note::
            At the time of writing, LED 7 is only set by the BMP on start-up to
            indicate that the watchdog timer reset the board. After this point,
            the LED is available for use by applications.

        Parameters
        ----------
        led : int or iterable
            Number of the LED or an iterable of LEDs to set the state of (0-7)
        action : bool or None
            State to set the LED to. True for on, False for off, None to
            toggle (default).
        board : int or iterable
            Specifies the board to control the LEDs of. This may also be an
            iterable of multiple boards (in the same frame). The command will
            actually be sent to the first board in the iterable.
        """
        if isinstance(led, int):
            leds = [led]
        else:
            leds = led
        if isinstance(board, int):
            boards = [board]
        else:
            boards = list(board)
            board = boards[0]

        # LED setting actions
        arg1 = sum(LEDAction.from_bool(action) << (led * 2) for led in leds)

        # Bitmask of boards to control
        arg2 = sum(1 << b for b in boards)

        yield From(self._send_scp(cabinet, frame, board, SCPCommands.led,
                                  arg1=arg1, arg2=arg2, expected_args=0,
                                  async=True))

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    @ContextMixin.use_contextual_arguments
    def read_fpga_reg(self, fpga_num, addr, cabinet=Required, frame=Required,
                      board=Required):
        """Read the value of an FPGA (SPI) register.

        See the SpI/O project's spinnaker_fpga design's `README`_ for a listing
        of FPGA registers. The SpI/O project can be found on GitHub at:
        https://github.com/SpiNNakerManchester/spio/

        .. _README: https://github.com/SpiNNakerManchester/spio/\
                    blob/master/designs/spinnaker_fpgas/README.md#spi-interface

        Parameters
        ----------
        fpga_num : int
            FPGA number (0, 1 or 2) to communicate with.
        addr : int
            Register address to read to (will be rounded down to the nearest
            32-bit word boundary).

        Returns
        -------
        int
            The 32-bit value at that address.
        """
        arg1 = addr & (~0x3)
        arg2 = 4  # Read a 32-bit value
        arg3 = fpga_num
        response = yield From(self._send_scp(cabinet, frame, board,
                                             SCPCommands.link_read,
                                             arg1=arg1, arg2=arg2, arg3=arg3,
                                             expected_args=0, async=True))
        raise Return(struct.unpack("<I", response.data)[0])

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    @ContextMixin.use_contextual_arguments
    def write_fpga_reg(self, fpga_num, addr, value, cabinet=Required,
                       frame=Required, board=Required):
        """Write the value of an FPGA (SPI) register.

        See the SpI/O project's spinnaker_fpga design's `README`_ for a listing
        of FPGA registers. The SpI/O project can be found on GitHub at:
        https://github.com/SpiNNakerManchester/spio/

        .. _README: https://github.com/SpiNNakerManchester/spio/\
                    blob/master/designs/spinnaker_fpgas/README.md#spi-interface

        Parameters
        ----------
        fpga_num : int
            FPGA number (0, 1 or 2) to communicate with.
        addr : int
            Register address to read or write to (will be rounded down to the
            nearest 32-bit word boundary).
        value : int
            A 32-bit int value to write to the register
        """
        arg1 = addr & (~0x3)
        arg2 = 4  # Write a 32-bit value
        arg3 = fpga_num
        yield From(self._send_scp(cabinet, frame, board,
                                  SCPCommands.link_write,
                                  arg1=arg1, arg2=arg2, arg3=arg3,
                                  data=struct.pack("<I", value),
                                  expected_args=0, async=True))

    @LookBlockingMixin.look_blocking
    @trollius.coroutine
    @ContextMixin.use_contextual_arguments
    def read_adc(self, cabinet=Required, frame=Required, board=Required):
        """Read ADC data from the BMP including voltages and temperature.

        Returns
        -------
        :py:class:`.ADCInfo`
        """
        response = yield From(self._send_scp(cabinet, frame, board,
                                             SCPCommands.bmp_info,
                                             arg1=BMPInfoType.adc,
                                             expected_args=0, async=True))
        data = struct.unpack("<"   # Little-endian
                             "8H"  # uint16_t adc[8]
                             "4h"  # int16_t t_int[4]
                             "4h"  # int16_t t_ext[4]
                             "4h"  # int16_t fan[4]
                             "I"   # uint32_t warning
                             "I",  # uint32_t shutdown
                             response.data)

        raise Return(ADCInfo(
            voltage_1_2c=data[1] * BMP_V_SCALE_2_5,
            voltage_1_2b=data[2] * BMP_V_SCALE_2_5,
            voltage_1_2a=data[3] * BMP_V_SCALE_2_5,
            voltage_1_8=data[4] * BMP_V_SCALE_2_5,
            voltage_3_3=data[6] * BMP_V_SCALE_3_3,
            voltage_supply=data[7] * BMP_V_SCALE_12,
            temp_top=float(data[8]) * BMP_TEMP_SCALE,
            temp_btm=float(data[9]) * BMP_TEMP_SCALE,
            temp_ext_0=((float(data[12]) * BMP_TEMP_SCALE)
                        if data[12] != BMP_MISSING_TEMP else None),
            temp_ext_1=((float(data[13]) * BMP_TEMP_SCALE)
                        if data[13] != BMP_MISSING_TEMP else None),
            fan_0=float(data[16]) if data[16] != BMP_MISSING_FAN else None,
            fan_1=float(data[17]) if data[17] != BMP_MISSING_FAN else None,
        ))


class BMPInfo(collections.namedtuple(
    'BMPInfo', "code_block frame_id can_id board_id version buffer_size "
               "build_date version_string")):
    """Information returned about a BMP by sver.

    Parameters
    ----------
    code_block : int
        The BMP, on power-up, will execute the first valid block in its flash
        storage. This value which indicates which 64 KB block was selected.
    frame_id : int
        An identifier programmed into the EEPROM of the backplane which
        uniquely identifies the frame the board is in. Note: This ID is not
        necessarily the same as a board's frame-coordinate.
    can_id : int
        ID of the board in the backplane CAN bus.
    board_id : int
        The position of the board in a frame. (This should correspond exactly
        with a board's board-coordinate.
    version : float
        Software version number. (Major version is integral part, minor version
        is fractional part).
    buffer_size : int
        Maximum supported size (in bytes) of the data portion of an SCP packet.
    build_date : int
        The time at which the software was compiled as a unix timestamp. May be
        zero if not set.
    version_string : string
        Human readable, textual version information split in to two fields by a
        "/". In the first field is the kernel (e.g. BC&MP) and the second the
        hardware platform (e.g. Spin5-BMP).
    """


class ADCInfo(collections.namedtuple(
    'ADCInfo', "voltage_1_2c voltage_1_2b voltage_1_2a voltage_1_8 "
               "voltage_3_3 voltage_supply "
               "temp_top temp_btm temp_ext_0 temp_ext_1 fan_0 fan_1")):
    """ADC data returned by a BMP including voltages and temperature.

    Parameters
    ----------
    voltage_1_2a : float
        Measured voltage on the 1.2 V rail A.
    voltage_1_2b : float
        Measured voltage on the 1.2 V rail B.
    voltage_1_2c : float
        Measured voltage on the 1.2 V rail C.
    voltage_1_8 : float
        Measured voltage on the 1.8 V rail.
    voltage_3_3 : float
        Measured voltage on the 3.3 V rail.
    voltage_supply : float
        Measured voltage of the (12 V) power supply input.
    temp_top : float
        Temperature near the top of the board (degrees Celsius)
    temp_btm : float
        Temperature near the bottom of the board (degrees Celsius)
    temp_ext_0 : float
        Temperature read from external sensor 0 (degrees Celsius) or None if
        not connected.
    temp_ext_1 : float
        Temperature read from external sensor 1 (degrees Celsius) or None if
        not connected.
    fan_0 : int
        External fan speed (RPM) of fan 0 or None if not connected.
    fan_1 : int
        External fan speed (RPM) of fan 1 or None if not connected.
    """
