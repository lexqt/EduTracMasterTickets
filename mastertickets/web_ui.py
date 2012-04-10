import subprocess
import re

from pkg_resources import resource_filename
from genshi.core import Markup, START, END, TEXT
from genshi.builder import tag

from trac.core import *
from trac.web.api import IRequestHandler, IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import ITemplateProvider, add_stylesheet, add_script, \
                            add_ctxtnav
from trac.ticket.api import ITicketManipulator
from trac.ticket.model import Ticket, Milestone
from trac.ticket.query import Query
from trac.config import Option, BoolOption, ChoiceOption, ListOption
from trac.resource import ResourceNotFound, get_resource_url, get_real_resource_from_url
from trac.util import to_unicode
from trac.util.html import html, Markup
from trac.util.text import shorten_line
from trac.util.compat import set, sorted, partial

from trac.project.api import ProjectManagement

import graphviz
from model import TicketLinks

class MasterTicketsModule(Component):
    """Provides support for ticket dependencies."""
    
    implements(IRequestHandler, IRequestFilter, ITemplateStreamFilter, 
               ITemplateProvider, ITicketManipulator)
    
    dot_path = Option('mastertickets', 'dot_path', default='dot',
                      doc='Path to the dot executable.')
    gs_path = Option('mastertickets', 'gs_path', default='gs',
                     doc='Path to the ghostscript executable.')
    use_gs = BoolOption('mastertickets', 'use_gs', default=False,
                        doc='If enabled, use ghostscript to produce nicer output.')
    
    closed_color = Option('mastertickets', 'closed_color', default='green',
        doc='Color of closed tickets')
    opened_color = Option('mastertickets', 'opened_color', default='red',
        doc='Color of opened tickets')

    graph_direction = ChoiceOption('mastertickets', 'graph_direction', choices = ['TD', 'LR', 'DT', 'RL'],
        doc='Direction of the dependency graph (TD = Top Down, DT = Down Top, LR = Left Right, RL = Right Left)')

    check_actions = ListOption('mastertickets', 'check_action', 'close, resolve',
                               doc='Check for unclosed blocking tickets when performing specified actions',
                               switcher=True)

    fields = set(['blocking', 'blockedby'])

    def __init__(self):
        self.pm = ProjectManagement(self.env)

    # IRequestFilter methods
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
            
            for i in links.blocked_by:
                if Ticket(self.env, i)['status'] != 'closed':
                    add_script(req, 'mastertickets/disable_resolve.js')
                    break

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
            ur = get_resource_url(self.env, milestone.resource)
            ur2 = req.href.depgraph(ur)
            add_ctxtnav(req, 'Depgraph', req.href.depgraph(get_resource_url(self.env, milestone.resource)))


        return template, data, content_type
        
    # ITemplateStreamFilter methods
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
                            field['rendered'] = self._link_tickets(req, data['ticket'][f])
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
        
    # ITicketManipulator methods
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

    # ITemplateProvider methods
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

    # IRequestHandler methods
    def match_request(self, req):
        return req.path_info.startswith('/depgraph')

    def process_request(self, req):
        path_info = req.path_info[10:]
        
        if not path_info:
            raise TracError('No resource specified')

        is_png = path_info.endswith('/depgraph.png')
        if is_png:
            path_info = path_info[:-13]

        #list of tickets to generate the depgraph for
        tkt_ids=[]

        resource = get_real_resource_from_url(self.env, path_info, req.args)
        self.pm.check_component_enabled(self, pid=resource.pid)
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

        g = self._build_graph(req, tkt_ids, label_summary=label_summary)
        if is_png or 'format' in req.args:
            format = req.args.get('format')
            if format == 'text':
                #in case g.__str__ returns unicode, we need to convert it in ascii
                req.send(to_unicode(g).encode('ascii', 'replace'), 'text/plain')
            elif format == 'debug':
                import pprint
                req.send(
                    pprint.pformat(
                        [TicketLinks(self.env, tkt_id) for tkt_id in tkt_ids]
                        ),
                    'text/plain')
            elif format is not None:
                req.send(g.render(self.dot_path, format), 'text/plain')
            
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
            data = {}
            
            #add a context link to enable/disable labels in nodes
            if label_summary:
                add_ctxtnav(req, 'Without labels', req.href(req.path_info, summary=0))
            else:
                add_ctxtnav(req, 'With labels', req.href(req.path_info, summary=1))

#            if milestone_name is None:
            if not is_milestone:
                data['tkt'] = ticket
                resource = ticket.resource
                add_ctxtnav(req, 'Back to Ticket #%s'%ticket.id,
                            get_resource_url(self.env, resource, req.href))
            else:
                resource = milestone.resource
                add_ctxtnav(req, 'Back to Milestone %s'%milestone.name,
                            get_resource_url(self.env, resource, req.href))
                data['milestone'] = milestone.name
            data['graph'] = g
            data['graph_render'] = partial(g.render, self.dot_path)
            data['use_gs'] = self.use_gs
            rsc_url = get_resource_url(self.env, resource)
            data['img_url'] = req.href.depgraph(rsc_url, 'depgraph.png', summary=g.label_summary)
            
            return 'depgraph.html', data, None

    def _build_graph(self, req, tkt_ids, label_summary=0):
        g = graphviz.Graph()
        g.label_summary = label_summary

        g.attributes['rankdir'] = self.graph_direction
        
        node_default = g['node']
        node_default['style'] = 'filled'
        
        edge_default = g['edge']
        edge_default['style'] = ''
        
        # Force this to the top of the graph
        for id in tkt_ids:
            g[id] 
        
        links = TicketLinks.walk_tickets(self.env, tkt_ids)
        links = sorted(links, key=lambda link: link.tkt.id)
        for link in links:
            tkt = link.tkt
            node = g[tkt.id]
            summary = tkt['summary'].replace('"', "'")
            if label_summary:
                node['label'] = u'#%s %s' % (tkt.id, summary)
            else:
                node['label'] = u'#%s'%tkt.id
            node['fillcolor'] = tkt['status'] == 'closed' and self.closed_color or self.opened_color
            node['URL'] = req.href.ticket(tkt.id)
            node['alt'] = u'Ticket #%s'%tkt.id
            node['tooltip'] = summary
            
            for n in link.blocking:
                node > g[n]
        
        return g

    def _link_tickets(self, req, tickets):
        items = []

        for i, word in enumerate(re.split(r'([;,\s]+)', tickets)):
            if i % 2:
                items.append(word)
            elif word:
                try:
                    ticketid = int(word)
                except ValueError:
                    return None
                word = '#%s' % word

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
