import pytest

from rig.links import Links
from rig.place_and_route import Machine, Cores, SDRAM, SRAM


class TestMachine(object):
    def test_constructor_copies(self):
        """Test that arguments are coped"""
        width = 8
        height = 12

        chip_resources = {Cores: 1, SDRAM: 321, SRAM: 123}
        chip_resource_exceptions = {(0, 0): {Cores: 0, SDRAM: 321, SRAM: 5}}

        dead_chips = set([(1, 1)])
        dead_links = set([(0, 0, Links.south_west),
                          (width-1, height-1, Links.north_east)])

        machine = Machine(width, height, chip_resources,
                          chip_resource_exceptions, dead_chips, dead_links)

        assert machine.width == width
        assert machine.height == height

        assert machine.chip_resources == chip_resources
        assert machine.chip_resources is not chip_resources
        assert machine.chip_resource_exceptions == chip_resource_exceptions
        assert machine.chip_resource_exceptions is not chip_resource_exceptions

        assert machine.dead_chips == dead_chips
        assert machine.dead_chips is not dead_chips
        assert machine.dead_links == dead_links
        assert machine.dead_links is not dead_links

    def test_copy(self):
        """Test copy function works correctly"""
        width = 8
        height = 12

        chip_resources = {Cores: 1, SDRAM: 321, SRAM: 123}
        chip_resource_exceptions = {(0, 0): {Cores: 0, SDRAM: 321, SRAM: 5}}

        dead_chips = set([(1, 1)])
        dead_links = set([(0, 0, Links.south_west),
                          (width-1, height-1, Links.north_east)])

        machine = Machine(width, height, chip_resources,
                          chip_resource_exceptions, dead_chips, dead_links)

        other_machine = machine.copy()

        assert machine.width == other_machine.width
        assert machine.height == other_machine.height

        assert machine.chip_resources == other_machine.chip_resources
        assert machine.chip_resources is not other_machine.chip_resources
        assert machine.chip_resource_exceptions \
            == other_machine.chip_resource_exceptions
        assert machine.chip_resource_exceptions \
            is not other_machine.chip_resource_exceptions

        assert machine.dead_chips == other_machine.dead_chips
        assert machine.dead_chips is not other_machine.dead_chips
        assert machine.dead_links == other_machine.dead_links
        assert machine.dead_links is not other_machine.dead_links

    def test_eq(self):
        """Ensure equality tests work."""
        m = Machine(1, 3)
        m.chip_resources = {Cores: 3}
        m.chip_resource_exceptions = {(0, 0): {Cores: 1}}
        m.dead_chips = set([(0, 1)])
        m.dead_links = set([(0, 0, Links.north)])

        # Should always compare equal to itself
        assert m == m
        assert not (m != m)

        # Should compare equal to a copy
        m_ = m.copy()
        assert m == m_
        assert not (m != m_)

        # Should not compare equal when the sizes differ
        m_.width = 2
        assert m != m_
        m_.width = 1
        assert m == m_
        assert not (m != m_)
        m_.height = 4
        assert m != m_
        assert not (m == m_)
        m_.height = 3
        assert m == m_
        assert not (m != m_)

        # Nor when resources differ
        m_.chip_resources = {Cores: 10}
        assert m != m_
        assert not (m == m_)
        m_.chip_resources = {Cores: 3}
        assert m == m_
        assert not (m != m_)

        # Nor when exceptions differ
        m_.chip_resource_exceptions = {(0, 0): {Cores: 10}}
        assert m != m_
        assert not (m == m_)
        m_.chip_resource_exceptions = {(0, 0): {Cores: 1}}
        assert m == m_
        assert not (m != m_)

        # Nor when dead chips differ
        m_.dead_chips = set([])
        assert m != m_
        assert not (m == m_)
        m_.dead_chips = set([(0, 1)])
        assert m == m_
        assert not (m != m_)

        # Nor when dead links differ
        m_.dead_links = set([(0, 0, Links.south)])
        assert m != m_
        assert not (m == m_)
        m_.dead_links = set([(0, 0, Links.north)])
        assert m == m_
        assert not (m != m_)

        # Should compare equal if exceptions result in the same system
        m_.chip_resource_exceptions = {(0, 0): {Cores: 1}, (0, 2): {Cores: 3}}
        assert m == m_
        assert not (m != m_)

    def test_issubset(self):
        """Ensure subset tests work."""
        m = Machine(1, 3)
        m.chip_resources = {Cores: 3}
        m.chip_resource_exceptions = {(0, 0): {Cores: 1}}
        m.dead_chips = set([(0, 1)])
        m.dead_links = set([(0, 0, Links.north)])

        # Should always be a subset of itself
        assert m.issubset(m)

        # Should compare equal to a copy
        m_ = m.copy()
        assert m.issubset(m_)

        # Should be a subset when smaller
        m_.width = 2
        assert m.issubset(m_)
        assert not m_.issubset(m)
        m_.width = 1
        assert m.issubset(m_)
        assert m_.issubset(m)

        m_.height = 2
        assert m_.issubset(m)
        assert not m.issubset(m_)
        m_.height = 3
        assert m.issubset(m_)
        assert m_.issubset(m)

        # Should be a subset when resources are lacking
        m_.chip_resources = {Cores: 10}
        assert m.issubset(m_)
        assert not m_.issubset(m)
        m_.chip_resources = {Cores: 3}
        assert m.issubset(m_)
        assert m_.issubset(m)

        # If resources are disjoint, should never be a subset
        m_.chip_resources = {Cores: 10}
        m.chip_resources = {Cores: 3, SDRAM: 1}
        assert not m.issubset(m_)
        assert not m_.issubset(m)
        m_.chip_resources = {Cores: 3}
        m.chip_resources = {Cores: 3}
        assert m.issubset(m_)
        assert m_.issubset(m)

        # Same should be true for resource exceptions
        m_.chip_resource_exceptions = {(0, 0): {Cores: 10}}
        assert m.issubset(m_)
        assert not m_.issubset(m)
        m_.chip_resource_exceptions = {(0, 0): {Cores: 1}}
        assert m.issubset(m_)
        assert m_.issubset(m)

        m_.chip_resource_exceptions = {(0, 0): {Cores: 10}}
        m.chip_resource_exceptions = {(0, 0): {SDRAM: 10}}
        assert not m.issubset(m_)
        assert not m_.issubset(m)
        m_.chip_resource_exceptions = {(0, 0): {Cores: 1}}
        m.chip_resource_exceptions = {(0, 0): {Cores: 1}}
        assert m.issubset(m_)
        assert m_.issubset(m)

        # A dead chip should count as a subset
        m_.dead_chips = set([])
        assert m.issubset(m_)
        assert not m_.issubset(m)
        m_.dead_chips = set([(0, 1)])
        assert m.issubset(m_)
        assert m_.issubset(m)

        # Disjoint sets of dead chips should always differ
        m_.dead_chips = set([(0, 0)])
        m.dead_chips = set([(0, 2)])
        assert not m.issubset(m_)
        assert not m_.issubset(m)
        m_.dead_chips = set([(0, 1)])
        m.dead_chips = set([(0, 1)])
        assert m.issubset(m_)
        assert m_.issubset(m)

        # Dead links should count as a subset
        m_.dead_links = set([])
        assert m.issubset(m_)
        assert not m_.issubset(m)
        m_.dead_links = set([(0, 0, Links.north)])
        assert m.issubset(m_)
        assert m_.issubset(m)

        # Disjoint sets of dead links should never count as a subset
        m_.dead_links = set([(0, 0, Links.south)])
        assert not m.issubset(m_)
        assert not m_.issubset(m)
        m_.dead_links = set([(0, 0, Links.north)])
        assert m.issubset(m_)
        assert m_.issubset(m)

    def test_in(self):
        """Ensure membership tests work."""
        width = 10
        height = 10

        # Hard-coded dead elements
        dead_chips = set([(1, 1)])
        dead_links = set([(0, 0, Links.south_west)])

        machine = Machine(width, height,
                          dead_chips=dead_chips, dead_links=dead_links)

        # Some sort of error when we test something insane
        with pytest.raises(ValueError):
            (1, 2, 3, 4) in machine

        # Exhaustive check of chip membership
        for x in range(width):
            for y in range(height):
                if (x, y) != (1, 1):
                    assert (x, y) in machine
                    for link in Links:
                        if (x, y, link) != (0, 0, Links.south_west):
                            assert (x, y, link) in machine
                        else:
                            assert (x, y, link) not in machine
                else:
                    assert (x, y) not in machine
                    for link in Links:
                        assert (x, y, link) not in machine

        # Check membership outside machine's bounds
        for x, y in ((0, -1), (-1, 0), (-1, -1),
                     (width, 0), (0, height), (width, height)):
            assert (x, y) not in machine
            for link in Links:
                assert (x, y, link) not in machine

    def test_resource_lookup(self):
        """Check can get/set resources for specified chips."""
        width = 2
        height = 2

        chip_resources = {Cores: 1, SDRAM: 2, SRAM: 3}
        chip_resource_exceptions = {(0, 0): {Cores: 4, SDRAM: 5, SRAM: 6}}

        machine = Machine(width, height, chip_resources,
                          chip_resource_exceptions)

        # Exhaustive lookup test
        for x in range(width):
            for y in range(width):
                if (x, y) != (0, 0):
                    assert machine[(x, y)] == chip_resources
                else:
                    assert machine[(x, y)] == chip_resource_exceptions[(0, 0)]

        # Test setting
        new_resource_exception = {Cores: 7, SDRAM: 8, SRAM: 9}
        machine[(1, 1)] = new_resource_exception
        assert machine[(1, 1)] == new_resource_exception

        # Test with non-existing chips
        with pytest.raises(IndexError):
            machine[(-1, -1)]
        with pytest.raises(IndexError):
            machine[(-1, -1)] = new_resource_exception

    def test_iter(self):
        machine = Machine(3, 2, dead_chips=set([(0, 0), (1, 1)]))
        assert set(machine) == set([(1, 0), (2, 0), (0, 1), (2, 1)])

    def test_iter_links(self):
        machine = Machine(1, 2, dead_links=set([(0, 0, Links.south),
                                                (0, 1, Links.north)]))
        assert set(machine.iter_links()) == set([
            (0, 0, Links.east),
            (0, 0, Links.west),
            (0, 0, Links.north),
            (0, 0, Links.north_east),
            (0, 0, Links.south_west),
            (0, 1, Links.east),
            (0, 1, Links.west),
            (0, 1, Links.south),
            (0, 1, Links.north_east),
            (0, 1, Links.south_west),
        ])

    def test_has_wrap_around_links(self):
        # Test singleton with wrap-arounds
        machine = Machine(1, 1)
        assert machine.has_wrap_around_links()
        assert machine.has_wrap_around_links(1.0)
        assert machine.has_wrap_around_links(0.1)

        # Test singleton with dead chip
        machine = Machine(1, 1, dead_chips=set([(0, 0)]))
        assert not machine.has_wrap_around_links()
        assert not machine.has_wrap_around_links(1.0)
        assert not machine.has_wrap_around_links(0.1)

        # Test singleton with one dead link
        machine = Machine(1, 1, dead_links=set([(0, 0, Links.north)]))
        assert machine.has_wrap_around_links(5.0 / 6.0)
        assert not machine.has_wrap_around_links(1.0)

        # Test fully-working larger machine
        machine = Machine(10, 10)
        assert machine.has_wrap_around_links()
        assert machine.has_wrap_around_links(1.0)
        assert machine.has_wrap_around_links(0.1)

        # Test larger machine with 50% dead links (note that we simply kill 50%
        # of links on border chips, not all chips, ensuring this function
        # probably isn't testing all links, just those on the borders)
        machine = Machine(10, 10, dead_links=set(
            [(x, y, link)
             for x in range(10)
             for y in range(10)
             for link in [Links.north, Links.west, Links.south_west]
             if x == 0 or y == 0]))
        assert not machine.has_wrap_around_links(1.0)
        assert machine.has_wrap_around_links(0.5)
        assert machine.has_wrap_around_links(0.1)
