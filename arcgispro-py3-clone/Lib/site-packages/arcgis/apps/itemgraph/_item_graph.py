import networkx as nx
from arcgis.gis import Item, GIS
import arcgis
from ._get_dependencies import _get_item_dependencies
import os


class ItemNode:
    """
    An ItemNode is a node in an ItemGraph. It represents an item in the graph and contains methods to
    interact with the graph and other items in the graph. It is not intended to be created directly by
    the user, but rather as a part of the ItemGraph class. The nodes are very simple- the only properties
    they contain are the item ID, a reference to the graph they're tied to, and in most cases, a
    reference to the item they're tied to. Cases where an item will not be included:
    1. The item does not exist, or is not accessible to the user (e.g. outside of the organization)
    2. The graph is being reconstructed from a list of item ID's and the item has not been fetched yet
    In this second case, other methods will be used to fetch the item when needed, in order to maximize
    efficiency when creating a large graph.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    graph               Required ItemGraph. The graph instance that the node is associated
                        with.
    ---------------     --------------------------------------------------------------------
    itemid              Required String. The item ID of the item that the node represents.
    ---------------     --------------------------------------------------------------------
    item                Optional Item. An instance of the item that the node represents.
    ===============     ====================================================================
    """

    def __init__(self, graph, itemid: str, item=None):
        self.id = itemid
        self.graph = graph
        self.item = item

    def __str__(self):
        if self.item:
            return f"ItemNode(id: {self.id}, item: {self.item.title})"
        else:
            return f"ItemNode(id: {self.id})"

    def __repr__(self):
        return self.__str__()

    def _adj_list(self):
        """
        Returns a list of all items that are directly connected to this item.
        """
        neighbors = []
        neighbors.extend(self.contains())
        neighbors.extend(self.contained_by())
        # do join
        return neighbors

    def _handle_nodes(self, node_list, out_format):
        # first, get lowercase out format and determine if it's valid
        out_format = out_format.lower()
        if out_format not in ["id", "item", "node"]:
            raise ValueError(
                "Invalid out_format. Options are 'id', 'item', and 'node'."
            )

        # if id's, just return list
        if out_format == "id":
            return node_list
        # if returning items instead of just id's...
        items = []
        for n in node_list:
            node = self.graph.get_node(n)
            # if node format, append node
            if out_format == "node":
                items.append(node)
                continue
            # otherwise, try to append the item
            if node.item:
                items.append(node.item)
            # otherwise, grab it
            else:
                item = self.graph.gis.content.get(n)
                items.append(item or n)
        return items

    def contains(self, out_format: str = "node"):
        """
        Compiles all of the items that this item directly contains. Can be returned in either
        the format of a list of item ID's, a list of item instances, or a list of graph nodes.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        out_format          Optional string. Options are "id", "item", and "node". Default is
                            "id".

                            .. note::
                                If this is set to "item", and an item instance is not
                                accessible, the item ID will be returned for that item instead.
        ===============     ====================================================================

        :return:
            A list of item ID's or items.
        """

        return self._handle_nodes(list(self.graph.successors(self.id)), out_format)

    def contained_by(self, out_format: str = "node"):
        """
        Compiles all of the items that directly contain this item. Can be returned in either
        the format of a list of item ID's, a list of item instances, or a list of graph nodes.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        out_format          Optional string. Options are "id", "item", and "node". Default is
                            "id".

                            .. note::
                                If this is set to "item", and an item instance is not
                                accessible, the item ID will be returned for that item instead.
        ===============     ====================================================================

        :return:
            A list of item ID's or items.
        """

        return self._handle_nodes(list(self.graph.predecessors(self.id)), out_format)

    def requires(self, out_format: str = "node"):
        """
        Compiles a deep list of all items that this item requires to exist. For example, if an
        item contains a WebMap item that itself contains a Feature Service item, then both of
        them will be returned in the output list. Can be returned in either the format of a
        list of item ID's, a list of item instances, or a list of graph nodes.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        out_format          Optional string. Options are "id", "item", and "node". Default is
                            "id".

                            .. note::
                                If this is set to "item", and an item instance is not
                                accessible, the item ID will be returned for that item instead.
        ===============     ====================================================================

        :return:
            A list of item ID's or items.
        """

        return self._handle_nodes(list(nx.descendants(self.graph, self.id)), out_format)

    def required_by(self, out_format: str = "node"):
        """
        Compiles a deep list of all items that require this item to exist. For example, if this
        item is a Feature Service found in a WebMap that is then itself found in a Dashboard,
        both of those items will be in the output list, on the condition that they have been
        indexed into the ItemGraph. Can be returned in either the format of a list of item ID's,
        a list of item instances, or a list of graph nodes.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        out_format          Optional string. Options are "id", "item", and "node". Default is
                            "id".

                            .. note::
                                If this is set to "item", and an item instance is not
                                accessible, the item ID will be returned for that item instead.
        ===============     ====================================================================

        :return:
            A list of item ID's or items.
        """

        return self._handle_nodes(list(nx.ancestors(self.graph, self.id)), out_format)


class ItemGraph(nx.DiGraph):
    """
    An ItemGraph is a directional dependency graph that represents relationships between
    items. An item is deemed to be dependent upon another item if the other item appears in
    the first item's data, structure, or dependent items property- the relationship type of
    this graph can be intepreted as "Item A needs Item B to exist". Users can retrieve an
    item in the graph via an item's item ID (assuming the item has been indexed into the
    graph), at which point they'll get an ItemNode to work with. Users can manually add
    items or relationships to the graph if desired, but most of the time this will be taken
    care by other functions, such as the create_dependency_graph function. The graph is built on
    top of the NetworkX DiGraph class, meaning it also inherits all of its methods and
    properties as well.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    gis                 Required GIS. The GIS instance that the graph is associated with.
    ===============     ====================================================================

    """

    def __init__(self, gis: GIS = None, digraph: nx.DiGraph = None):
        if not digraph:
            super().__init__()
        else:
            super().__init__(digraph)
        self.gis = gis or arcgis.env.active_gis

    def _create_tree(self, itemid: str):
        """
        Private method to create a tree structure of the graph starting from a given item ID.
        Items will not get repeated, meaning that even if one item is traversed multiple times
        during construction of the tree, it will only exist once in the tree. This is useful
        for visualizing the dependencies of an item in a hierarchical way.
        """
        tree = {}
        visited = []

        def _assemble_tree(itemid, tree):
            tree[itemid] = {}
            for child in self.successors(itemid):
                if child not in visited:
                    visited.append(child)
                    _assemble_tree(child, tree[itemid])

        _assemble_tree(itemid, tree)
        return tree

    def add_relationship(self, parent: str, child: str):
        """
        Adds a relationship to the graph. This relationship is directional: the parent item
        contains the child item, so the parent item is dependent upon the child. If either
        item is not already in the graph, they will be automatically added.

        .. note::
            Relationships cannot go both ways- an item cannot be both dependent upon and
            a dependency of the same item. Attempting to add a relationship will fail if
            the inverse already exists.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        parent              Required string. The item ID of the parent item.
        ---------------     --------------------------------------------------------------------
        child               Required string. The item ID of the child item.
        ===============     ====================================================================
        """

        if parent not in self:
            self.add_item(parent)
        if child not in self:
            self.add_item(child)

        if parent in self and child in self.predecessors(parent):
            raise ValueError(
                "An item cannot be both dependent upon and a dependency of the same item."
            )
        self.add_edge(parent, child)

    def delete_relationship(self, parent: str, child: str):
        """
        Deletes a relationship from the graph. The relationship is directional, so it is
        important to properly specify which item is the parent and which is the child.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        parent              Required string. The item ID of the parent item.
        ---------------     --------------------------------------------------------------------
        child               Required string. The item ID of the child item.
        ===============     ====================================================================
        """
        self.remove_edge(parent, child)

    def add_item(self, itemid: str, item=None):
        """
        Adds an item to the graph. The item ID is required, but the item itself is optional.
        Creates an ItemNode with the item ID and item. Will usually be called by other functions
        and not by users. Note that this does not add any relationships to the graph.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        itemid              Required string. The item ID of the item to add.
        ---------------     --------------------------------------------------------------------
        item                Optional :class:`~arcgis.gis.Item`. An instance of the item to add.
        ===============     ====================================================================
        """
        node = ItemNode(self, itemid, item)
        self.add_node(itemid, node=node)

    def delete_item(self, itemid: str):
        """
        Deletes an item from the graph. Associated relationships will also be removed.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        itemid              Required string. The item ID of the item to remove.
        ===============     ====================================================================
        """
        self.remove_node(itemid)

    def get_node(self, itemid: str):
        """
        Method gets an :class:`~arcgis.apps.itemgraph.ItemNode` instance for the item contained
        in the graph with the given item ID. *None* will be returned if the item is not
        in the graph.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        itemid              Required string. The item ID of the item node to retrieve.
        ===============     ====================================================================

        :return:
            An :class:`~arcgis.apps.itemgraph.ItemNode` instance.
        """
        try:
            return self.nodes[itemid]["node"]
        except:
            return None

    def add_dependencies(
        self, item_list: list[Item, str], outside_org: bool = True, **kwargs
    ):
        """
        Adds a list of items to the graph and their dependencies. The function recursively explores
        the dependencies of each item that is part of the organization, encompassing the full dependency
        tree of each source item.

        .. note::
            If the *outside_org* argument is set to *True*, items external to the organization
            are incuded in the results, but are not explored for dependencies.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        item_list           Required list of :class:`items <arcgis.gis.Item>` or *Item ID*
                            values to include in the graph.
        ---------------     --------------------------------------------------------------------
        outside_org         Optional boolean.

                            * When *True*, items outside of the organization will
                            be included in the graph (but still not explored for their
                            dependencies). Default is *True*.
                            * When *False*, only items owned by users in the org will
                            be included in the graph.
        ===============     ====================================================================

        In addition to explicitly named parameters, this function supports optional key word
        arguments:

        ===============     ========================================================================
        **kwargs**          **Description**
        ---------------     ------------------------------------------------------------------------
        include_reverse     Optional boolean.

                            * When *True*, the graph will include reverse relationships found
                            found when calling the :meth:`~arcgis.gis.Item.related_items`
                            method on an *item* with the *item.related_items(direction="reverse")*
                            argument
                            * When *False*, only includes *item.related_items(direction="forward")*
                            relationships
        ===============     ========================================================================
        """
        create_dependency_graph(self.gis, item_list, outside_org, graph=self, **kwargs)

    def all_items(self, out_format: str = "node"):
        """
        Returns a list of the item ID's of all items in the graph.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        out_format          Required string. The format of items in the list. Default is *node*.
                            Options:

                            * *node*
                            * *item*
        ===============     ====================================================================

        :return:
            * List of :class:`item <arcgis.gis.Item>` if *out_format="item"*
            * List of :class:`itemnode <arcgis.apps.itemgraph.ItemNode>` objects if *out_format="node"*
        """
        out_format = out_format.lower()
        if out_format == "node":
            return [i[1]["node"] for i in list(self.nodes(data=True))]
        elif out_format == "item":
            out_list = []
            for i in list(self.nodes(data=True)):
                node = i[1]["node"]
                if node.item:
                    out_list.append(node.item)
                else:
                    out_list.append(node.id)
            return out_list
        else:
            return list(self.nodes())

    def write_to_file(self, location: str):
        """
        Writes the graph to a file in GML format.

        ..note::
            Method strictly writes the ID's and edges of the graph.
            No information about the items themselves is included.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        location            Required string. The path to write the file to.
        ===============     ====================================================================
        """
        # assert the path is valid and ends with gml
        if not location.endswith(".gml"):
            location += ".gml"

        # create a stringizer that tells us later to make a node
        def stringize_node(data):
            if not isinstance(data, ItemNode):
                return data
            return f"node_{data.id}_item" if data.item else f"node_{data.id}"

        nx.write_gml(self, location, stringize_node)
        return location


def load_from_file(path: str, gis: GIS = None, include_items: bool = True):
    """
    Loads a graph from a file in GML format. The graph should have been written to the file
    using the write_to_file method.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    path                Required string. The path to the GML file to load the graph from.
    ---------------     --------------------------------------------------------------------
    gis                 Required :class:`~arcgis.gis.GIS` object. The GIS instance that the
                        graph is associated with. If not provided, the active GIS will be
                        used, if available. *Must* be the same GIS as the one used to create
                        the graph.
    ---------------     --------------------------------------------------------------------
    include_items       Optional boolean.

                        * When *True*, the :class:`~arcgis.apps.itemgraph.ItemNode` instances
                          will include the :class:`item <arcgis.gis.Item>` instances as well.
                          Otherwise, *items* are retrieved as needed. Default is *True*.
                        * When *False*, item instances are not included.

                        .. note::
                            Best practice is to set to False on very large graphs.
    ===============     ====================================================================

    :return:
        An :class:`~arcgis.apps.itemgraph.ItemGraph` instance.
    """
    if not gis:
        gis = arcgis.env.active_gis
    if not gis and include_items:
        raise ValueError("An active GIS is required to load an ItemGraph with items.")
    if not os.path.exists(path):
        raise FileNotFoundError("The file does not exist.")
    if not path.endswith(".gml"):
        raise ValueError("The file must be in GML format.")

    # create a destringizer to create nodes
    def destringize_node(data):
        if not data.startswith("node_"):
            return data
        itemid = data.split("_")[1]
        item = None
        if include_items and data.endswith("_item"):
            item = gis.content.get(itemid)
        return ItemNode(None, itemid, item)

    graph = nx.read_gml(path, destringizer=destringize_node)
    ig = ItemGraph(gis, digraph=graph)
    for node in ig.all_items():
        node.graph = ig
    return ig


def create_dependency_graph(
    gis: GIS, item_list: list[Item, str], outside_org: bool = True, **kwargs
):
    """
    Creates an :class:`~arcgis.apps.itemgraph.ItemGraph` from a list of
    :class:`items <arcgis.gis.Item>`. The function recursively explores the dependencies
    of each item that is part of the organization, encompassing the full dependency tree
    of each source item.

    .. note::
        If the *outside_org* argument is set to *True*, items external to the organization
        are incuded in the results, but are not explored for dependencies.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    gis                 Required :class:`~arcgis.gis.GIS` object. The GIS instance that the
                        graph is associated with.
    ---------------     --------------------------------------------------------------------
    item_list           Required list of :class:`items <arcgis.gis.Item>` or *Item ID*
                        values to include in the graph.
    ---------------     --------------------------------------------------------------------
    outside_org         Optional boolean.

                        * When *True*, items outside of the organization will
                          be included in the graph (but still not explored for their
                          dependencies). Default is *True*.
                        * When *False*, only items owned by users in the org will
                          be included in the graph.
    ===============     ====================================================================

    In addition to explicitly named parameters, this function supports optional key word
    arguments:

    ===============     ========================================================================
    **kwargs**          **Description**
    ---------------     ------------------------------------------------------------------------
    include_reverse     Optional boolean.

                        * When *True*, the graph will include reverse relationships found
                          found when calling the :meth:`~arcgis.gis.Item.related_items`
                          method on an *item* with the *item.related_items(direction="reverse")*
                          argument
                        * When *False*, only includes *item.related_items(direction="forward")*
                          relationships
    ===============     ========================================================================

    :return:
        An :class:`~arcgis.apps.itemgraph.ItemGraph` with all of the relevant items
        and relationships.
    """

    graph = kwargs.get("graph", None)
    if not isinstance(graph, ItemGraph):
        graph = ItemGraph(gis)
    rev = kwargs.get("include_reverse", False)

    def _add_deps(item: Item):
        if rev is True:
            deps, rev_deps = _get_item_dependencies(item, gis, True, True)
        else:
            deps = _get_item_dependencies(item, gis)
            rev_deps = None

        def _handle_deps(item, deps, forward):
            for dep in deps:

                # check if we've already checked this item before
                if dep in graph:
                    # not allowing bidirectional relationships currently
                    try:
                        if forward:
                            graph.add_relationship(item.itemid, dep)
                        else:
                            graph.add_relationship(dep, item.itemid)
                    finally:
                        continue

                if "http://" in dep or "https://" in dep:
                    dep_item = None
                else:
                    dep_item = gis.content.get(dep)

                # check if item is outside of the organization
                if not dep_item or gis.url not in dep_item.homepage:
                    if not outside_org:
                        continue
                    graph.add_item(dep, dep_item)
                    if forward:
                        graph.add_relationship(item.itemid, dep)
                    else:
                        graph.add_relationship(dep, item.itemid)

                # if an item in our org, add it and check its dependencies
                else:
                    graph.add_item(dep, dep_item)
                    if forward:
                        graph.add_relationship(item.itemid, dep)
                    else:
                        graph.add_relationship(dep, item.itemid)
                    _add_deps(dep_item)

        _handle_deps(item, deps, True)
        if rev_deps:
            _handle_deps(item, rev_deps, False)

    for item in item_list:
        # first grab our item
        if isinstance(item, str):
            item = gis.content.get(item)

        # if valid, add it and check its dependencies
        if item:
            graph.add_item(item.itemid, item)
            _add_deps(item)

    return graph
