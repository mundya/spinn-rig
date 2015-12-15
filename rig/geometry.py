"""General-purpose SpiNNaker-related geometry functions.
"""

import random

from math import sqrt

import numpy as np

from rig.links import Links


def to_xyz(xy):
    """Convert a two-tuple (x, y) coordinate into an (x, y, 0) coordinate."""
    x, y = xy
    return (x, y, 0)


def minimise_xyz(xyz):
    """Minimise an (x, y, z) coordinate."""
    x, y, z = xyz
    m = max(min(x, y), min(max(x, y), z))
    return (x-m, y-m, z-m)


def shortest_mesh_path_length(source, destination):
    """Get the length of a shortest path from source to destination without
    using wrap-around links.

    Parameters
    ----------
    source : (x, y, z)
    destination : (x, y, z)

    Returns
    -------
    int
    """
    x, y, z = (d - s for s, d in zip(source, destination))
    # When vectors are minimised, (1,1,1) is added or subtracted from them.
    # This process does not change the range of numbers in the vector. When a
    # vector is minimal, it is easy to see that the range of numbers gives the
    # magnitude since there are at most two non-zero numbers (with opposite
    # signs) and the sum of their magnitudes will also be their range.
    return max(x, y, z) - min(x, y, z)


def shortest_mesh_path(source, destination):
    """Calculate the shortest vector from source to destination without using
    wrap-around links.

    Parameters
    ----------
    source : (x, y, z)
    destination : (x, y, z)

    Returns
    -------
    (x, y, z)
    """
    return minimise_xyz(d - s for s, d in zip(source, destination))


def shortest_torus_path_length(source, destination, width, height):
    """Get the length of a shortest path from source to destination using
    wrap-around links.

    See http://jhnet.co.uk/articles/torus_paths for an explanation of how this
    method works.

    Parameters
    ----------
    source : (x, y, z)
    destination : (x, y, z)
    width : int
    height : int

    Returns
    -------
    int
    """
    # Aliases for convenience
    w, h = width, height

    # Get (non-wrapping) x, y vector from source to destination as if the
    # source was at (0, 0).
    x, y, z = (d - s for s, d in zip(source, destination))
    x, y = x - z, y - z
    x %= w
    y %= h

    return min(max(x, y),          # No wrap
               w - x + y,          # Wrap X only
               x + h - y,          # Wrap Y only
               max(w - x, h - y))  # Wrap X and Y


def shortest_torus_path(source, destination, width, height):
    """Calculate the shortest vector from source to destination using
    wrap-around links.

    See http://jhnet.co.uk/articles/torus_paths for an explanation of how this
    method works.

    Note that when multiple shortest paths exist, one will be chosen at random
    with uniform probability.

    Parameters
    ----------
    source : (x, y, z)
    destination : (x, y, z)
    width : int
    height : int

    Returns
    -------
    (x, y, z)
    """
    # Aliases for convenience
    w, h = width, height

    # Convert to (x,y,0) form
    sx, sy, sz = source
    sx, sy = sx - sz, sy - sz

    # Translate destination as if source was at (0,0,0) and convert to (x,y,0)
    # form where both x and y are not -ve.
    dx, dy, dz = destination
    dx, dy = (dx - dz - sx) % w, (dy - dz - sy) % h

    # The four possible vectors: [(distance, vector), ...]
    approaches = [(max(dx, dy), (dx, dy, 0)),                # No wrap
                  (w-dx+dy, (-(w-dx), dy, 0)),               # Wrap X only
                  (dx+h-dy, (dx, -(h-dy), 0)),               # Wrap Y only
                  (max(w-dx, h-dy), (-(w-dx), -(h-dy), 0))]  # Wrap X and Y

    # Select a minimal approach at random
    _, vector = min(approaches, key=(lambda a: a[0]+random.random()))
    x, y, z = minimise_xyz(vector)

    # Transform to include a random number of 'spirals' on Z axis where
    # possible.
    if abs(x) >= height:
        max_spirals = x // height
        d = random.randint(min(0, max_spirals), max(0, max_spirals)) * height
        x -= d
        z -= d
    elif abs(y) >= width:
        max_spirals = y // width
        d = random.randint(min(0, max_spirals), max(0, max_spirals)) * width
        y -= d
        z -= d

    return (x, y, z)


def concentric_hexagons(radius, start=(0, 0)):
    """A generator which produces coordinates of concentric rings of hexagons.

    Parameters
    ----------
    radius : int
        Number of layers to produce (0 is just one hexagon)
    start : (x, y)
        The coordinate of the central hexagon.
    """
    x, y = start
    yield (x, y)
    for r in range(1, radius + 1):
        # Move to the next layer
        y -= 1
        # Walk around the hexagon of this radius
        for dx, dy in [(1, 1), (0, 1), (-1, 0), (-1, -1), (0, -1), (1, 0)]:
            for _ in range(r):
                yield (x, y)
                x += dx
                y += dy


def standard_system_dimensions(num_boards):
    """Calculate the standard network dimensions (in chips) for a system with
    the specified number of SpiNN-5 boards.

    Returns
    -------
    (w, h)
        Width and height of the network in chips.

        Standard SpiNNaker systems are constructed as squarely as possible
        given the number of boards available. When a square system cannot be
        made, the function prefers wider systems over taller systems.

      Raises
      ------
      ValueError
        If the number of boards is not a multiple of three.
    """
    # Special case to avoid division by 0
    if num_boards == 0:
        return (0, 0)

    # Special case: meaningful systems with 1 board can exist
    if num_boards == 1:
        return (8, 8)

    if num_boards % 3 != 0:
        raise ValueError("{} is not a multiple of 3".format(num_boards))

    # Find the largest pair of factors to discover the squarest system in terms
    # of triads of boards.
    for h in reversed(  # pragma: no branch
            range(1, int(sqrt(num_boards // 3)) + 1)):
        if (num_boards // 3) % h == 0:
            break

    w = (num_boards // 3) // h

    # Convert the number of triads into numbers of chips (each triad of boards
    # contributes as 12x12 block of chips).
    return (w * 12, h * 12)


def spinn5_eth_coords(width, height):
    """Generate a list of board coordinates with Ethernet connectivity in a
    SpiNNaker machine.

    Specifically, generates the coordinates for the Ethernet connected chips of
    SpiNN-5 boards arranged in a standard torus topology.

    Parameters
    ----------
    width : int
        Width of the system in chips.
    height : int
        Height of the system in chips.
    """
    # Internally, work with the width and height rounded up to the next
    # multiple of 12
    w = ((width + 11) // 12) * 12
    h = ((height + 11) // 12) * 12

    for x in range(0, w, 12):
        for y in range(0, h, 12):
            for dx, dy in ((0, 0), (4, 8), (8, 4)):
                nx = (x + dx) % w
                ny = (y + dy) % h
                # Skip points which are outside the range available
                if nx < width and ny < height:
                    yield (nx, ny)


def spinn5_local_eth_coord(x, y, w, h):
    """Get the coordinates of a chip's local ethernet connected chip.

    Returns the coordinates of the ethernet connected chip on the same board as
    the supplied chip.

    .. note::
        This function assumes the system is constructed from SpiNN-5 boards

    Parameters
    ----------
    x : int
    y : int
    w : int
        Width of the system in chips.
    h : int
        Height of the system in chips.
    """
    dx, dy = SPINN5_ETH_OFFSET[y % 12][x % 12]
    return ((x + dx) % w), ((y + dy) % h)


SPINN5_ETH_OFFSET = np.array([
    [(vx - x, vy - y) for x, (vx, vy) in enumerate(row)]
    for y, row in enumerate([
        # Below is an enumeration of the absolute coordinates of the nearest
        # ethernet connected chip. Note that the above list comprehension
        # changes these into offsets to the nearest chip.
        # X:   0         1         2         3         4         5         6         7         8         9        10        11     # noqa Y:
        [(+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+4, -4), (+4, -4), (+4, -4), (+4, -4), (+4, -4), (+4, -4), (+4, -4)],  # noqa  0
        [(+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+4, -4), (+4, -4), (+4, -4), (+4, -4), (+4, -4), (+4, -4)],  # noqa  1
        [(+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+4, -4), (+4, -4), (+4, -4), (+4, -4), (+4, -4)],  # noqa  2
        [(+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+4, -4), (+4, -4), (+4, -4), (+4, -4)],  # noqa  3
        [(-4, +4), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+8, +4), (+8, +4), (+8, +4), (+8, +4)],  # noqa  4
        [(-4, +4), (-4, +4), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+8, +4), (+8, +4), (+8, +4), (+8, +4)],  # noqa  5
        [(-4, +4), (-4, +4), (-4, +4), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+8, +4), (+8, +4), (+8, +4), (+8, +4)],  # noqa  6
        [(-4, +4), (-4, +4), (-4, +4), (-4, +4), (+0, +0), (+0, +0), (+0, +0), (+0, +0), (+8, +4), (+8, +4), (+8, +4), (+8, +4)],  # noqa  7
        [(-4, +4), (-4, +4), (-4, +4), (-4, +4), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+8, +4), (+8, +4), (+8, +4)],  # noqa  8
        [(-4, +4), (-4, +4), (-4, +4), (-4, +4), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+8, +4), (+8, +4)],  # noqa  9
        [(-4, +4), (-4, +4), (-4, +4), (-4, +4), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+8, +4)],  # noqa 10
        [(-4, +4), (-4, +4), (-4, +4), (-4, +4), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8), (+4, +8)]   # noqa 11
    ])
], dtype=int)
"""SpiNN-5 ethernet connected chip lookup.

Used by :py:func:`.spinn5_local_eth_coord`. Given an x and y chip position
modulo 12, return the offset of the board's bottom-left chip from the chip's
position.

Note: the order of indexes: ``SPINN5_ETH_OFFSET[y][x]``!
"""


def spinn5_chip_coord(x, y):
    """Get the coordinates of a chip on its board.

    Given the coordinates of a chip in a multi-board system, calculates the
    coordinates of the chip within its board.

    .. note::
        This function assumes the system is constructed from SpiNN-5 boards

    Parameters
    ----------
    x : int
    y : int
    """
    dx, dy = SPINN5_ETH_OFFSET[y % 12][x % 12]
    return (-dx, -dy)


def spinn5_fpga_link(x, y, link):
    """Get the identity of the FPGA link which corresponds with the supplied
    link.

    .. note::
        This function assumes the system is constructed from SpiNN-5 boards
        whose FPGAs are loaded with the SpI/O 'spinnaker_fpgas' image.

    Parameters
    ----------
    x : int
    y : int

    Returns
    -------
    (fpga_num, link_num) or None
        If not None, the link supplied passes through an FPGA link. The
        returned tuple indicates the FPGA responsible for the sending-side of
        the link.

        `fpga_num` is the number (0, 1 or 2) of the FPGA responsible for the
        link.

        `link_num` indicates which of the sixteen SpiNNaker links (0 to 15)
        into an FPGA is being used. Links 0-7 are typically handled by S-ATA
        link 0 and 8-15 are handled by S-ATA link 1.

        Returns None if the supplied link does not pass through an FPGA.
    """
    x, y = spinn5_chip_coord(x, y)
    return SPINN5_FPGA_LINKS.get((x, y, link))


SPINN5_FPGA_LINKS = {
    (0, 0, Links.south_west): (1, 0),  # noqa
    (0, 0, Links.west):       (1, 1),  # noqa
    (0, 1, Links.south_west): (1, 2),  # noqa
    (0, 1, Links.west):       (1, 3),  # noqa
    (0, 2, Links.south_west): (1, 4),  # noqa
    (0, 2, Links.west):       (1, 5),  # noqa
    (0, 3, Links.south_west): (1, 6),  # noqa
    (0, 3, Links.west):       (1, 7),  # noqa

    (0, 3, Links.north): (1, 8),  # noqa
    (1, 4, Links.west):  (1, 9),  # noqa
    (1, 4, Links.north): (1, 10),  # noqa
    (2, 5, Links.west):  (1, 11),  # noqa
    (2, 5, Links.north): (1, 12),  # noqa
    (3, 6, Links.west):  (1, 13),  # noqa
    (3, 6, Links.north): (1, 14),  # noqa
    (4, 7, Links.west):  (1, 15),  # noqa

    (4, 7, Links.north):       (2, 0),  # noqa
    (4, 7, Links.north_east):  (2, 1),  # noqa
    (5, 7, Links.north):       (2, 2),  # noqa
    (5, 7, Links.north_east):  (2, 3),  # noqa
    (6, 7, Links.north):       (2, 4),  # noqa
    (6, 7, Links.north_east):  (2, 5),  # noqa
    (7, 7, Links.north):       (2, 6),  # noqa
    (7, 7, Links.north_east):  (2, 7),  # noqa

    (7, 7, Links.east):        (2, 8),  # noqa
    (7, 6, Links.north_east):  (2, 9),  # noqa
    (7, 6, Links.east):        (2, 10),  # noqa
    (7, 5, Links.north_east):  (2, 11),  # noqa
    (7, 5, Links.east):        (2, 12),  # noqa
    (7, 4, Links.north_east):  (2, 13),  # noqa
    (7, 4, Links.east):        (2, 14),  # noqa
    (7, 3, Links.north_east):  (2, 15),  # noqa

    (7, 3, Links.east):  (0, 0),  # noqa
    (7, 3, Links.south): (0, 1),  # noqa
    (6, 2, Links.east):  (0, 2),  # noqa
    (6, 2, Links.south): (0, 3),  # noqa
    (5, 1, Links.east):  (0, 4),  # noqa
    (5, 1, Links.south): (0, 5),  # noqa
    (4, 0, Links.east):  (0, 6),  # noqa
    (4, 0, Links.south): (0, 7),  # noqa

    (4, 0, Links.south_west): (0, 8),  # noqa
    (3, 0, Links.south):      (0, 9),  # noqa
    (3, 0, Links.south_west): (0, 10),  # noqa
    (2, 0, Links.south):      (0, 11),  # noqa
    (2, 0, Links.south_west): (0, 12),  # noqa
    (1, 0, Links.south):      (0, 13),  # noqa
    (1, 0, Links.south_west): (0, 14),  # noqa
    (0, 0, Links.south):      (0, 15),  # noqa
}
"""FPGA link IDs for each link leaving a SpiNN-5 board.

Format::

    {(x, y, link): (fpga_num, link_num), ...}

Used by :py:func:`.spinn5_fpga_link`.
"""
