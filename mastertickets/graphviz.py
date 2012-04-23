# -*- coding: utf-8 -*-
# Created by Noah Kantrowitz on 2007-12-21.
# Copyright (c) 2007 Noah Kantrowitz. All rights reserved.
# Copyright (c) 2012 Aleksey A. Porfirov

import subprocess
import itertools
from collections import OrderedDict


def _format_options(base_string, options):
    return u'%s [%s]'%(base_string, u', '.join([u'%s="%s"'%x for x in options.iteritems()]))

class Edge(dict):
    """Model for an edge in a dot graph."""

    def __init__(self, source, dest, **kwargs):
        self.source = source
        self.dest = dest
        dict.__init__(self, **kwargs)

    def __str__(self):
        ret = u'%s -> %s'%(self.source.name, self.dest.name)
        if self:
            ret = _format_options(ret, self)
        return ret

    def __hash__(self):
        return hash(id(self))


class Node(dict):
    """Model for a node in a dot graph."""

    def __init__(self, name, **kwargs):
        self.name = unicode(name)
        self.edges = []
        dict.__init__(self, **kwargs)

    def __str__(self):
        ret = self.name
        if self:
            ret = _format_options(ret, self)
        return ret

    def __gt__(self, other):
        """Allow node1 > node2 to add an edge."""
        edge = Edge(self, other)
        self.edges.append(edge)
        other.edges.append(edge)
        return edge

    def __lt__(self, other):
        edge = Edge(other, self)
        self.edges.append(edge)
        other.edges.append(edge)
        return edge

    def __hash__(self):
        return hash(id(self))


class Cluster(object):
    '''A model object for cluster inside digraph'''

    def __init__(self, name, graph, **kwargs):
        self.name = unicode(name)
        self.graph = graph
        self.nodes = OrderedDict()
        self.edges = []
        self.attributes = kwargs

    def __str__(self):
        lines = [u'subgraph "%s" {' % self.name]
        lines.append(Graph.content_to_string(self.attributes, self.nodes.values(), self.edges))
        lines.append(u'}')
        return u'\n'.join(lines)

    def add(self, obj):
        if isinstance(obj, Node):
            self.graph.add_node(obj)
            key = obj.name
            if key not in self.nodes:
                self.nodes[key] = obj
        elif isinstance(obj, Edge):
            self.edges.append(obj)

    def __getitem__(self, key):
        key = unicode(key)
        node = self.graph.get_node(key)
        if key not in self.nodes:
            self.nodes[key] = node
        return node

    def __delitem__(self, key):
        key = unicode(key)
        self.nodes.pop(key, None)


class Graph(object):
    """A model object for a graphviz digraph."""

    def __init__(self, name=u'graph'):
        super(Graph,self).__init__()
        self.name = unicode(name)
        self.nodes = []
        self.global_nodes = []
        self._global_node_set = set()
        self.clusters = OrderedDict()
        self._node_map = {}
        self.attributes={}
        self.edges = []

    def add(self, obj):
        if isinstance(obj, Node):
            self.add_node(obj)
            if obj.name not in self._global_node_set:
                self.nodes.append(obj)
        elif isinstance(obj, Edge):
            self.edges.append(obj)

    def __getitem__(self, key):
        key = unicode(key)
        node = self.get_node(key)
        if key not in self._global_node_set:
            self._global_node_set.add(key)
            self.nodes.append(node)
        return node

    def __delitem__(self, key):
        key = unicode(key)
        if key in self._global_node_set:
            self._global_node_set.pop(key)
            node = self.get_node(key)
            self.nodes.remove(node)

    def create_cluster(self, name, **kwargs):
        name = unicode(name)
        cluster = Cluster(name, self, **kwargs)
        self.clusters[name] = cluster
        return cluster

    # Low-level methods (no checks) to manipulate graph node map

    def init_node(self, key):
        key = unicode(key)
        new_node = Node(key)
        self._node_map[key] = new_node
        return new_node

    def add_node(self, obj):
        key = obj.name
        if key not in self._node_map:
            self._node_map[key] = obj
        return obj

    def get_node(self, key):
        key = unicode(key)
        if key not in self._node_map:
            return self.init_node(key)
        return self._node_map[key]

    def del_node(self, key):
        key = unicode(key)
        return self._node_map.pop(key, None)

    def has_node(self, key):
        key = unicode(key)
        return key in self._node_map

    # Render methods

    @staticmethod
    def content_to_string(attributes, nodes, edges):
        lines = []
        edges_ = []
        nodes_ = []

        memo = set()
        def process(lst):
            for obj in lst:
                if obj in memo:
                    continue
                memo.add(obj)
                
                if isinstance(obj, Node):
                    nodes_.append(obj)
#                    process(obj.edges)
                elif isinstance(obj, Edge):
                    edges_.append(obj)
                    if isinstance(obj.source, Node):
                        process((obj.source,))
                    if isinstance(obj.dest, Node):
                        process((obj.dest,))
        
        process(nodes)
        process(edges)

        for att,value in attributes.iteritems():
            lines.append(u'\t%s="%s";' % (att,value))
        for obj in itertools.chain(nodes_, edges_):
            lines.append(u'\t%s;'%obj)

        return u'\n'.join(lines)

    def __str__(self):
        lines = [u'digraph "%s" {' % self.name]
        lines.append(self.content_to_string(self.attributes, self.nodes, self.edges))
        for _cl_name, cl in self.clusters.iteritems():
            lines.append(str(cl))
        lines.append(u'}')
        return u'\n'.join(lines)

    def render(self, dot_path='dot', format='png'):
        """Render a dot graph."""
        proc = subprocess.Popen([dot_path, '-T%s'%format], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        out, _ = proc.communicate(unicode(self).encode('utf8'))
        return out


if __name__ == '__main__':
    g = Graph()
    root = Node('me')
    root > Node('them')
    root < Node(u'Üs')
    
    g.add(root)
    
    print g.render()
