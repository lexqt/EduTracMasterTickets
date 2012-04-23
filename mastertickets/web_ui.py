import subprocess
import re
import textwrap
import itertools
from functools import partial

from pkg_resources import resource_filename
from genshi.builder import tag

from trac.core import *
from trac.web.api import IRequestHandler, IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import ITemplateProvider, INavigationContributor, \
                            add_ctxtnav
from trac.ticket.api import ITicketManipulator
from trac.ticket.model import Ticket, Milestone
from trac.ticket.query import Query
from trac.config import Option, BoolOption, ChoiceOption, ListOption
from trac.resource import Resource, ResourceNotFound, get_resource_url, get_real_resource_from_url
from trac.util import to_unicode
from trac.util.text import shorten_line

from trac.project.api import ProjectManagement

import graphviz
from model import TicketLinks

class MasterTicketsModule(Component):
    """Provides support for ticket dependencies."""

    implements(IRequestHandler, IRequestFilter, ITemplateStreamFilter,
               ITemplateProvider, INavigationContributor, ITicketManipulator)

    dot_path = Option('mastertickets', 'dot_path', default='dot',
                      doc='Path to the dot executable.')
    gs_path = Option('mastertickets', 'gs_path', default='gs',
                     doc='Path to the ghostscript executable.')
    use_gs = BoolOption('mastertickets', 'use_gs', default=False,
                        doc='If enabled, use ghostscript to produce nicer output.')

    default_format = Option('mastertickets', 'default_format', default='svg',
                     doc='Default format for rendering depgraph.')

    closed_color = Option('mastertickets', 'closed_color', default='green',
        doc='Color of closed tickets')
    opened_color = Option('mastertickets', 'opened_color', default='red',
        doc='Color of opened tickets')
    bad_closed_color = Option('mastertickets', 'bad_closed_color', default='orange',
        doc='Color of bad closed tickets')

    bad_closed_resolutions = ListOption('mastertickets', 'bad_closed_resolution', 'invalid',
                               doc='Resolution list for bad closed tickets',
                               switcher=True)

    graph_direction = ChoiceOption('mastertickets', 'graph_direction', choices = ['TD', 'LR', 'DT', 'RL'],
        doc='Direction of the dependency graph (TD = Top Down, DT = Down Top, LR = Left Right, RL = Right Left)')

    check_actions = ListOption('mastertickets', 'check_action', 'close, resolve',
                               doc='Check for unclosed blocking tickets when performing specified actions',
                               switcher=True)

    fields = set(['blocking', 'blockedby'])
    IMAGE_RE = re.compile(r'depgraph\.([a-z]{3,5})$')

    def __init__(self):
        self.pm = ProjectManagement(self.env)

    # INavigationContributor

    def get_active_navigation_item(self, req):
        return 'depgraph'

    def get_navigation_items(self, req):
        if 'TICKET_VIEW' not in req.perm:
            return
        yield ('mainnav', 'depgraph',
               tag.a('Depgraph', href=req.href.depgraph()))

    # IRequestFilter

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if req.path_info.startswith('/ticket/'):
            # In case of an invalid ticket, the data is invalid
            if not data:
                return template, data, content_type
            tkt = data['ticket']
            self.pm.check_component_enabled(self, pid=tkt.pid)
            links = TicketLinks(self.env, tkt)

            # Add link to depgraph if needed
            if links:
                add_ctxtnav(req, 'Depgraph', req.href.depgraph(get_resource_url(self.env, tkt.resource)))

            for change in data.get('changes', {}):
                if not change.has_key('fields'):
                    continue
                for field, field_data in change['fields'].iteritems():
                    if field in self.fields:
                        vals = {}
                        for i in ('new', 'old'):
                            if isinstance(field_data[i], basestring):
                                val = field_data[i].strip()
                            else:
                                val = ''
                            if val:
                                vals[i] = set([int(n) for n in val.split(',')])
                            else:
                                vals[i] = set()
                        add = vals['new'] - vals['old']
                        sub = vals['old'] - vals['new']
                        elms = tag()
                        if add:
                            elms.append(
                                tag.em(u', '.join([unicode(n) for n in sorted(add)]))
                            )
                            elms.append(u' added')
                        if add and sub:
                            elms.append(u'; ')
                        if sub:
                            elms.append(
                                tag.em(u', '.join([unicode(n) for n in sorted(sub)]))
                            )
                            elms.append(u' removed')
                        field_data['rendered'] = elms

        #add a link to generate a dependency graph for all the tickets in the milestone
        if req.path_info.startswith('/milestone/'):
            if not data or not 'milestone' in data:
                return template, data, content_type
            milestone=data['milestone']
            self.pm.check_component_enabled(self, pid=milestone.pid)
            add_ctxtnav(req, 'Depgraph', req.href.depgraph(get_resource_url(self.env, milestone.resource)))


        return template, data, content_type

    # ITemplateStreamFilter

    def filter_stream(self, req, method, filename, stream, data):
        if not data:
            return stream

        # We try all at the same time to maybe catch also changed or processed templates
        if filename in ["report_view.html", "query_results.html", "ticket.html", "query.html"]:
            # For ticket.html
            if 'fields' in data and isinstance(data['fields'], list):
                self.pm.check_component_enabled(self, pid=data['ticket'].pid)
                for field in data['fields']:
                    for f in self.fields:
                        if field['name'] == f and data['ticket'][f]:
                            field['rendered'] = self._link_tickets(req, data['ticket'][f], fetch_tickets=True)
            # For query_results.html and query.html
            if 'groups' in data and isinstance(data['groups'], list):
                self.pm.check_component_enabled(self, syllabus_id=data['query'].syllabus_id)
                for group, tickets in data['groups']:
                    for ticket in tickets:
                        for f in self.fields:
                            if f in ticket:
                                ticket[f] = self._link_tickets(req, ticket[f])
            # For report_view.html
            if 'row_groups' in data and isinstance(data['row_groups'], list):
                self.pm.check_component_enabled(self, syllabus_id=data['report']['syllabus_id'])
                for group, rows in data['row_groups']:
                    for row in rows:
                        if 'cell_groups' in row and isinstance(row['cell_groups'], list):
                            for cells in row['cell_groups']:
                                for cell in cells:
                                    # If the user names column in the report differently (blockedby AS "blocked by") then this will not find it
                                    if cell.get('header', {}).get('col') in self.fields:
                                        cell['value'] = self._link_tickets(req, cell['value'])
        return stream

    # ITicketManipulator

    def prepare_ticket(self, req, ticket, fields, actions):
        pass

    def validate_ticket(self, req, ticket, action):
        if not ticket.exists: # new ticket
            return
        if not action:
            yield None, 'Valid action is required to validate ticket dependencies'
            return
        syllabus_id = ticket.syllabus_id
        actions = self.check_actions.syllabus(syllabus_id)
        if action['alias'] in actions:
            links = TicketLinks(self.env, ticket)
            for i in links.blocked_by:
                if Ticket(self.env, i)['status'] != 'closed':
                    yield None, 'Ticket #%s is blocking this ticket'%i

    # ITemplateProvider

    def get_htdocs_dirs(self):
        """Return the absolute path of a directory containing additional
        static resources (such as images, style sheets, etc).
        """
        return [('mastertickets', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        """Return the absolute path of the directory containing the provided
        ClearSilver templates.
        """
        return [resource_filename(__name__, 'templates')]

    # IRequestHandler

    def match_request(self, req):
        return req.path_info.startswith('/depgraph')

    def process_request(self, req):
        path_info = req.path_info[10:]

        img_format = req.args.get('format')
        m = self.IMAGE_RE.search(path_info)
        is_img = m is not None
        if is_img:
            img_format = m.group(1)
            path_info = path_info[:-(10+len(img_format))]

        is_full_graph = not path_info

        cur_pid = self.pm.get_current_project(req)

        #list of tickets to generate the depgraph for
        tkt_ids=[]

        if is_full_graph:
            # depgraph for full project
            # cluster by milestone
            self.pm.check_component_enabled(self, pid=cur_pid)
            db = self.env.get_read_db()
            cursor = db.cursor()
            q = '''
                SELECT milestone, id
                FROM ticket
                WHERE project_id=%s
                ORDER BY milestone, id
            '''
            cursor.execute(q, (cur_pid,))
            rows = cursor.fetchall()
            tkt_ids = rows
        else:
            # degraph for resource
            resource = get_real_resource_from_url(self.env, path_info, req.args)

            # project check
            res_pid = resource.pid
            self.pm.check_component_enabled(self, pid=res_pid)
            if res_pid != cur_pid:
                self.pm.redirect_to_project(req, res_pid)

            is_milestone = isinstance(resource, Milestone)
            #Urls to generate the depgraph for a ticket is /depgraph/ticketnum
            #Urls to generate the depgraph for a milestone is /depgraph/milestone/milestone_name
            if is_milestone:
                #we need to query the list of tickets in the milestone
                milestone = resource
                query=Query(self.env, constraints={'milestone' : [milestone.name]}, max=0, project=milestone.pid)
                tkt_ids=[fields['id'] for fields in query.execute()]
            else:
                #the list is a single ticket
                ticket = resource
                tkt_ids = [ticket.id]

        #the summary argument defines whether we place the ticket id or
        #it's summary in the node's label
        label_summary=0
        if 'summary' in req.args:
            label_summary=int(req.args.get('summary'))

        g = self._build_graph(req, tkt_ids, label_summary=label_summary, full_graph=is_full_graph)
        if is_img or img_format:
            if img_format == 'text':
                #in case g.__str__ returns unicode, we need to convert it in ascii
                req.send(to_unicode(g).encode('ascii', 'replace'), 'text/plain')
            elif img_format == 'debug':
                import pprint
                req.send(
                    pprint.pformat(
                        [TicketLinks(self.env, tkt_id) for tkt_id in tkt_ids]
                        ),
                    'text/plain')
            elif img_format == 'svg':
                req.send(g.render(self.dot_path, img_format), 'image/svg+xml')
            elif img_format is not None:
                req.send(g.render(self.dot_path, img_format), 'text/plain')

            if self.use_gs:
                ps = g.render(self.dot_path, 'ps2')
                gs = subprocess.Popen([self.gs_path, '-q', '-dTextAlphaBits=4', '-dGraphicsAlphaBits=4', '-sDEVICE=png16m', '-sOutputFile=%stdout%', '-'],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                img, err = gs.communicate(ps)
                if err:
                    self.log.debug('MasterTickets: Error from gs: %s', err)
            else:
                img = g.render(self.dot_path)
            req.send(img, 'image/png')
        else:
            data = {
                'graph': g,
                'graph_render': partial(g.render, self.dot_path),
                'use_gs': self.use_gs,
                'full_graph': is_full_graph,
                'img_format': self.default_format,
            }

            #add a context link to enable/disable labels in nodes
            if label_summary:
                add_ctxtnav(req, 'Without labels', req.href(req.path_info, summary=0))
            else:
                add_ctxtnav(req, 'With labels', req.href(req.path_info, summary=1))

            if is_full_graph:
                rsc_url = None
            else:
                if is_milestone:
                    resource = milestone.resource
                    add_ctxtnav(req, 'Back to Milestone %s'%milestone.name,
                                get_resource_url(self.env, resource, req.href))
                    data['milestone'] = milestone.name
                else: # ticket
                    data['tkt'] = ticket
                    resource = ticket.resource
                    add_ctxtnav(req, 'Back to Ticket #%s'%ticket.id,
                                get_resource_url(self.env, resource, req.href))
                rsc_url = get_resource_url(self.env, resource)

            data['img_url'] = req.href.depgraph(rsc_url, 'depgraph.%s' % self.default_format,
                                                summary=g.label_summary)

            return 'depgraph.html', data, None

    def _build_graph(self, req, tkt_ids, label_summary=0, full_graph=False):
        g = graphviz.Graph()
        g.label_summary = label_summary

        g.attributes.update({
            'rankdir': self.graph_direction,
        })

        node_default = g['node']
        node_default.update({
            'style': 'filled',
            'fontsize': 11,
            'fontname': 'Arial',
            'shape': 'box' if label_summary else 'ellipse',
            'target': '_blank',
        })

        edge_default = g['edge']
        edge_default['style'] = ''

        width = 20
        def q(text):
            return textwrap.fill(text, width).replace('"', '\\"').replace('\n', '\\n')

        def create_node(tkt):
            node = g.get_node(tkt.id)
            summary = q(tkt['summary'])
            if label_summary:
                node['label'] = u'#%s %s' % (tkt.id, summary)
            else:
                node['label'] = u'#%s'%tkt.id
            if tkt['status'] == 'closed':
                color = tkt['resolution'] in bc_resolutions and self.bad_closed_color or self.closed_color
            else:
                color = self.opened_color
            node['fillcolor'] = color
            node['URL'] = req.href.ticket(tkt.id)
            node['alt'] = u'Ticket #%s'%tkt.id
            node['tooltip'] = summary.replace('\\n', ' &#10;')
            return node

        ticket_cache = {}

        if full_graph:
            milestone_tkt_ids = sorted(tkt_ids)
            tkt_ids = []
            tickets = {} # { <milestone_name or None>: (<cluster or graph>, <tkt_ids list>), ... }
            ticket_milestones = {} # { <tkt_id>: <milestone> }
            m_idx = 0
            for milestone, mtkt_ids in itertools.groupby(milestone_tkt_ids, lambda p: p[0]):
                ids = [p[1] for p in mtkt_ids]
                if milestone:
                    m_idx += 1
                    url = req.href.depgraph(get_resource_url(self.env,
                                            Resource('milestone', milestone, pid=req.data['project_id'])))
                    tickets[milestone] = (g.create_cluster(
                            u'cluster%s' % m_idx,
                            label=q(milestone),
                            href=url, target='_blank'),
                                          ids)
                else:
                    milestone = None
                    tickets[None] = (g, ids)
                tkt_ids.extend(ids)
                for tkt_id in ids:
                    ticket_milestones[tkt_id] = milestone
        else:
            # Init nodes for resource tickets on graph top
            for id in tkt_ids:
                g[id]

        bc_resolutions = self.bad_closed_resolutions.syllabus(req.data['syllabus_id'])
        links = TicketLinks.walk_tickets(self.env, tkt_ids, ticket_cache)
        links = sorted(links, key=lambda link: link.tkt.id)
        for link in links:
            node = create_node(link.tkt)

            if full_graph:
                milestone_from = link.tkt['milestone'] or None
                stor = tickets[milestone_from][0]
                stor[link.tkt.id] # include node
                for n in link.blocking:
                    milestone_to = ticket_milestones[n]
                    if milestone_from == milestone_to:
                        stor.add(node > stor[n]) # save edge in same cluster
                    else:
                        g.add(node > tickets[milestone_to][0][n]) # save edge in global graph
            else:
                g[link.tkt.id]
                for n in link.blocking:
                    g.add(node > g[n])

        return g

    def _link_tickets(self, req, tickets, fetch_tickets=False):
        items = []

        for i, word in enumerate(re.split(r'([;,\s]+)', tickets or '')):
            if i % 2:
                items.append(word)
            elif word:
                try:
                    ticketid = int(word)
                except ValueError:
                    return None
                word = '#%s' % word

                if fetch_tickets:
                    try:
                        ticket = Ticket(self.env, ticketid)
                        if 'TICKET_VIEW' in req.perm(ticket.resource):
                            word = \
                                tag.a(
                                    '#%s' % ticket.id,
                                    class_=ticket['status'],
                                    href=req.href.ticket(int(ticket.id)),
                                    title=shorten_line(ticket['summary'])
                                )
                    except ResourceNotFound:
                        pass

                items.append(word)

        if items:
            return tag(items)
        else:
            return None
