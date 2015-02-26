"""Neighbour Exploring Routing (NER) algorithm from J. Navaridas et al.

Algorithm refrence: J. Navaridas et al. SpiNNaker: Enhanced multicast routing,
Parallel Computing (2014).

`http://dx.doi.org/10.1016/j.parco.2015.01.002`
"""

import heapq

from collections import deque

from .util import longest_dimension_first, to_xyz, \
    shortest_mesh_path_length, shortest_mesh_path, \
    shortest_torus_path_length, shortest_torus_path, \
    has_wrap_around_links, links_between

from ..exceptions import MachineHasDisconnectedSubregion

from ..constraints import RouteEndpointConstraint

from ...machine import Links, Cores

from ...routing_table import Routes

from ..routing_tree import RoutingTree


def concentric_hexagons(radius, start=(0, 0)):
    """A generator which produces coordinates of concentric rings of hexagons.

    Parameters
    ----------
    radius : int
        Number of layers to produce (0 is just one hexagon)
    x : int
        Starting X-coordinate
    y : int
        Starting Y-coordinate
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


def ner_net(source, destinations, width, height, wrap_around=False, radius=10):
    """Produce a shortest path tree for a given net using NER.

    This is the kernel of the NER algorithm.

    Parameters
    ----------
    source : (x, y)
        The coordinate of the source vertex.
    destinations : iterable([(x, y), ...])
        The coordinates of destination vertices.
    width : int
        Width of the system (nodes)
    height : int
        Height of the system (nodes)
    wrap_around : bool
        True if wrap-around links should be used, false if they should be
        avoided.
    radius : int
        Radius of area to search from each node. 20 is arbitrarily selected in
        the paper and shown to be acceptable in practice.

    Returns
    -------
    (:py:class:`~.rig.place_and_route.routing_tree.RoutingTree`,
     {(x,y): :py:class:`~.rig.place_and_route.routing_tree.RoutingTree`, ...})
        A RoutingTree is produced rooted at the source and visiting all
        destinations but which does not contain any vertices etc. For
        convenience, a dictionarry mapping from destination (x, y) coordinates
        to the associated RoutingTree is provided to allow the caller to insert
        these items.
    """
    # Map from (x, y) to RoutingTree objects
    route = {source: RoutingTree(source)}

    # Handle each destination, sorted by distance from the source, closest
    # first.
    for destination in sorted(destinations,
                              key=(lambda destination:
                                   shortest_mesh_path_length(
                                       to_xyz(source), to_xyz(destination))
                                   if not wrap_around else
                                   shortest_torus_path_length(
                                       to_xyz(source), to_xyz(destination),
                                       width, height))):
        # We shall attempt to find our nearest neighbouring placed node.
        neighbour = None

        # Try to find nodes nearby by searching an enlarging concentric ring of
        # ndoes.
        for x, y in concentric_hexagons(radius, destination):
            if wrap_around:
                x %= width
                y %= height
            if (x, y) in route and (x, y) != destination:
                neighbour = (x, y)
                break

        # Fall back on routing directly to the source if nothing was found
        if neighbour is None:
            neighbour = source

        # Find the shortest vector from the neighbour to this destination
        if wrap_around:
            vector = shortest_torus_path(to_xyz(neighbour),
                                         to_xyz(destination),
                                         width, height)
        else:
            vector = shortest_mesh_path(to_xyz(neighbour), to_xyz(destination))

        # Take the longest dimension first route.
        last_node = route[neighbour]
        for x, y in longest_dimension_first(vector, neighbour, width, height):
            this_node = route.get((x, y), None)
            if this_node is None:
                this_node = RoutingTree((x, y))
                route[(x, y)] = this_node

            last_node.children.add(this_node)
            last_node = this_node

    return (route[source], route)


def copy_and_disconnect_tree(root, machine):
    """Copy a RoutingTree (containing nothing but RoutingTrees), disconnecting
    nodes which are not connected in the machine.

    Note that if a dead chip is part of the input RoutingTree, no corresponding
    node will be included in the copy. The assumption behind this is that the
    only reason a tree would visit a dead chip is because a route passed
    through the chip and wasn't actually destined to arrive at that chip. This
    situation is impossible to confirm since the input routing trees have not
    yet been populated with vertices. The caller is responsible for being
    sensible.

    Parameters
    ----------
    root : :py:class:`~rig.place_and_route.routing_tree.RoutingTree`
        The root of the RoutingTree that contains nothing but RoutingTrees
        (i.e. no vertices and links).
    machine : :py:class:`~rig.machine.Machine`
        The machine in which the routes exist.

    Returns
    -------
    (root, lookup, broken_links)
        Where:
        * `root` is the new root of the tree
          :py:class:`~rig.place_and_route.routing_tree.RoutingTree`
        * `lookup` is a dict {(x, y):
          :py:class:`~rig.place_and_route.routing_tree.RoutingTree`, ...}
        * `broken_links` is a set ([(parent, child), ...]) containing all
          disconnected parent and child (x, y) pairs due to broken links.
    """
    new_root = None

    # Lookup for copied routing tree {(x, y): RoutingTree, ...}
    new_lookup = {}

    # List of missing connections in the copied routing tree [(new_parent,
    # new_child), ...]
    broken_links = set()

    # A queue [(new_parent, old_node), ...]
    to_visit = deque([(None, root)])
    while to_visit:
        new_parent, old_node = to_visit.popleft()

        if old_node.chip in machine:
            # Create a copy of the node
            new_node = RoutingTree(old_node.chip)
            new_lookup[new_node.chip] = new_node
        else:
            # This chip is dead, move all its children into the parent node
            assert new_parent is not None, \
                "Net cannot be sourced from a dead chip."
            new_node = new_parent

        if new_parent is None:
            # This is the root node
            new_root = new_node
        elif new_node is not new_parent:
            # If this node is not dead, check connectivity to parent node (no
            # reason to check connectivity between a dead node and its parent).
            if links_between(new_parent.chip, new_node.chip, machine):
                # Is connected via working link
                new_parent.children.add(new_node)
            else:
                # Link to parent is dead (or original parent was dead and the
                # new parent is not adjacent)
                broken_links.add((new_parent.chip, new_node.chip))

        # Copy children
        for child in old_node.children:
            to_visit.append((new_node, child))

    return (new_root, new_lookup, broken_links)


def a_star(sink, heuristic_source, sources, machine, wrap_around):
    """Use A* to find a path from any of the sources to the sink.

    Note that the heuristic means that the search will proceed towards
    heuristic_source without any concern for any other sources. This means that
    the algorithm may miss a very close neighbour in order to pursue its goal
    of reaching heuristic_source. This is not considered a problem since 1) the
    heuristic source will typically be in the direction of the rest of the tree
    and near by and often the closest entity 2) it prevents us accidentally
    forming loops in the rest of the tree since we'll stop as soon as we touch
    any part of it.

    Parameters
    ----------
    sink : (x, y)
    heuristic_source : (x, y)
        An element from `sources` which is used as a guiding heuristic for the
        A* algorithm.
    sources : set([(x, y), ...])
    machine : :py:class:`~rig.machine.Machine`
    wrap_around : bool
        Consider wrap-around links in heuristic distance calculations.

    Return
    ------
    [(x, y), ...]
        A path starting with a coordinate in `sources` and terminating at
        connected neighbour of `sink` (i.e. the path does not include `sink`).

    Raises
    ------
    :py:class:~rig.place_and_route.exceptions.MachineHasDisconnectedSubregion`
        If a path cannot be found.
    """
    # Select the heuristic function to use for distances
    if wrap_around:
        heuristic = (lambda node:
                     shortest_torus_path_length(to_xyz(node),
                                                to_xyz(heuristic_source),
                                                machine.width, machine.height))
    else:
        heuristic = (lambda node:
                     shortest_mesh_path_length(to_xyz(node),
                                               to_xyz(heuristic_source)))

    # A dictionary {node: previous_node}. An entry indicates that 1) the node
    # has been visited and 2) which node we hopped from to reach previous_node.
    # This may be None if the node is the sink.
    visited = {sink: None}

    # The node which the tree will be reconnected to
    selected_source = None

    # A heap (accessed via heapq) of (distance, (x, y)) where distance is the
    # distance between (x, y) and heuristic_source and (x, y) is a node to
    # explore.
    to_visit = [(heuristic(sink), sink)]
    while to_visit:
        _, node = heapq.heappop(to_visit)

        # Terminate if we've found the destination
        if node in sources:
            selected_source = node
            break

        # Try all neighbouring locations. Note: link identifiers are from the
        # perspective of the neighbour, not the current node!
        for neighbour_link, vector in [(Links.east, (-1, 0)),
                                       (Links.west, (1, 0)),
                                       (Links.north, (0, -1)),
                                       (Links.south, (0, 1)),
                                       (Links.north_east, (-1, -1)),
                                       (Links.south_west, (1, 1))]:
            neighbour = ((node[0] + vector[0]) % machine.width,
                         (node[1] + vector[1]) % machine.height)

            # Skip links which are broken
            if (neighbour[0], neighbour[1], neighbour_link) not in machine:
                continue

            # Skip neighbours who have already been visited
            if neighbour in visited:
                continue

            # Explore all other neighbours
            visited[neighbour] = node
            heapq.heappush(to_visit, (heuristic(neighbour), neighbour))

    # Fail of no paths exist
    if selected_source is None:
        raise MachineHasDisconnectedSubregion(
            "Could not find path from {} to {}".format(
                sink, heuristic_source))

    # Reconstruct the discovered path
    path = [selected_source]
    while visited[path[-1]] != sink:
        path.append(visited[path[-1]])
    return path


def avoid_dead_links(root, machine, wrap_around=False):
    """Modify a RoutingTree to route-around dead links in a Machine.

    Uses A* to reconnect disconnected branches of the tree (due to dead links
    in the machine).

    Parameters
    ----------
    root : :py:class:`~rig.place_and_route.routing_tree.RoutingTree`
        The root of the RoutingTree which contains nothing but RoutingTrees
        (i.e. no vertices and links).
    machine : :py:class:`~rig.machine.Machine`
        The machine in which the routes exist.
    wrap_around : bool
        Consider wrap-around links in pathfinding heuristics.

    Returns
    -------
    (:py:class:`~.rig.place_and_route.routing_tree.RoutingTree`,
     {(x,y): :py:class:`~.rig.place_and_route.routing_tree.RoutingTree`, ...})
        A new RoutingTree is produced rooted as before. A dictionarry mapping
        from (x, y) to the associated RoutingTree is provided for convenience.

    Raises
    ------
    :py:class:~rig.place_and_route.exceptions.MachineHasDisconnectedSubregion`
        If a path to reconnect the tree cannot be found.
    """
    # Make a copy of the RoutingTree with all broken parts disconnected
    root, lookup, broken_links = copy_and_disconnect_tree(root, machine)

    for parent, child in broken_links:
        child_chips = set(c.chip for c in lookup[child])

        # Try to reconnect broken links to any other part of the tree
        # (excluding the broken subtree itself)
        path = a_star(child, parent,
                      set(lookup).difference(child_chips),
                      machine, wrap_around)

        # Add new RoutingTree nodes to reconnect the child to the tree.
        last_node = lookup[path[0]]
        for x, y in path[1:]:
            if (x, y) not in child_chips:
                new_node = RoutingTree((x, y))
                assert (x, y) not in lookup, "Cycle must not be created."
                lookup[(x, y)] = new_node
            else:
                # This path segment overlaps part of the disconnected tree
                # (A* doesn't know where the disconnected tree is and thus
                # doesn't avoid it). To prevent cycles being introduced, this
                # overlapped node is severed from its parent and merged as part
                # of the A* path.
                new_node = lookup[(x, y)]

                # Disconnect node from parent
                for node in lookup[child]:
                    if new_node in node.children:
                        node.children.remove(new_node)
                        break
            last_node.children.add(new_node)
            last_node = new_node
        last_node.children.add(lookup[child])

    return (root, lookup)


def route(vertices_resources, nets, machine, constraints, placements,
          allocation, core_resource=Cores, radius=20):
    """Routing algorithm based on Neighbour Exploring Routing (NER).

    This algorithm attempts to use NER to generate routing trees for all nets
    and routes around broken links using A* graph search. If the system is
    fully connected, this algorithm will always succeed though no consideration
    of congestion or routing-table usage is attempted.

    Router-Specific Parameters
    --------------------------
    radius : int
        Radius of area to search from each node. 20 is arbitrarily selected in
        the paper and shown to be acceptable in practice. If set to zero, this
        method is becomes longest dimension first routing.

    Raises
    ------
    :py:class:~rig.place_and_route.exceptions.MachineHasDisconnectedSubregion`
        If any pair of vertices in a net have no path between them (i.e.
        the system is impossible to route).
    """
    wrap_around = has_wrap_around_links(machine)

    # Vertices constrained to route to a specific link. {vertex: route}
    route_to_endpoint = {}
    for constraint in constraints:
        if isinstance(constraint, RouteEndpointConstraint):
            route_to_endpoint[constraint.vertex] = constraint.route

    routes = {}
    for net in nets:
        # Generate routing tree (assuming a perfect machine)
        root, lookup = ner_net(placements[net.source],
                               set(placements[sink] for sink in net.sinks),
                               machine.width, machine.height,
                               wrap_around, radius)

        # Fix routes to avoid dead chips/links
        root, lookup = avoid_dead_links(root, machine, wrap_around)

        # Annotate RoutingTree with vertices/links
        for sink in net.sinks:
            if sink in route_to_endpoint:
                # Route to link
                lookup[placements[sink]].children.add(route_to_endpoint[sink])
            else:
                # Route to the sink's cores
                cores = allocation[sink].get(core_resource, slice(0, 0))
                for core in range(cores.start, cores.stop):
                    lookup[placements[sink]].children.add(Routes.core(core))

        routes[net] = root

    return routes