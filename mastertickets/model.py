# Created by Noah Kantrowitz on 2007-07-04.
# Copyright (c) 2007 Noah Kantrowitz. All rights reserved.
# Copyright (c) 2012 Aleksey A. Porfirov

import copy
from datetime import datetime

from trac.ticket.model import Ticket
from trac.util.compat import set, sorted
from trac.util.datefmt import utc, to_utimestamp
from trac.util.text import exception_to_unicode

class TicketLinks(object):
    """A model for the ticket links used MasterTickets."""

    def __init__(self, env, tkt, db=None, ticket_cache=None):
        '''Initialize ticket links
        Use `ticket_cache` (if is not None) to store fetched tickets.
        '''
        self.env = env
        if not isinstance(tkt, Ticket):
            if ticket_cache is not None:
                tid = int(tkt)
                if tid not in ticket_cache:
                    ticket_cache[tid] = Ticket(self.env, tid)
                tkt = ticket_cache[tid]
            else:
                tkt = Ticket(self.env, tkt)
        self.tkt = tkt

        db = db or self.env.get_db_cnx()
        cursor = db.cursor()

        cursor.execute('SELECT dest FROM mastertickets WHERE source=%s ORDER BY dest', (self.tkt.id,))
        self.blocking = set([int(num) for num, in cursor])
        self._old_blocking = copy.copy(self.blocking)

        cursor.execute('SELECT source FROM mastertickets WHERE dest=%s ORDER BY source', (self.tkt.id,))
        self.blocked_by = set([int(num) for num, in cursor])
        self._old_blocked_by = copy.copy(self.blocked_by)

    def save(self, author, comment='', when=None, db=None):
        """Save new links."""
        if when is None:
            when = datetime.now(utc)
        when_ts = to_utimestamp(when)

        handle_commit = False
        if db is None:
            db = self.env.get_db_cnx()
            handle_commit = True
        cursor = db.cursor()

        new_blocking = set(int(n) for n in self.blocking if int(n) != self.tkt.id)
        new_blocked_by = set(int(n) for n in self.blocked_by if int(n) != self.tkt.id)

        to_check = [
            # new, old, field
            (new_blocking, self._old_blocking, 'blockedby', ('source', 'dest')),
            (new_blocked_by, self._old_blocked_by, 'blocking', ('dest', 'source')),
        ]

        commented_tickets = set()

        for new_ids, old_ids, field, sourcedest in to_check:
            for n in new_ids | old_ids:
                update_field = None
                if n in new_ids and n not in old_ids:
                    # New ticket added
                    cursor.execute('INSERT INTO mastertickets (%s, %s) VALUES (%%s, %%s)'%sourcedest, (self.tkt.id, n))
                    update_field = lambda tset: tset.add(str(self.tkt.id))
                elif n not in new_ids and n in old_ids:
                    # Old ticket removed
                    cursor.execute('DELETE FROM mastertickets WHERE %s=%%s AND %s=%%s'%sourcedest, (self.tkt.id, n))
                    update_field = lambda tset: tset.remove(str(self.tkt.id))

                if update_field is not None:
                    cursor.execute('SELECT value FROM ticket_custom WHERE ticket=%s AND name=%s',
                                   (n, str(field)))
                    res = cursor.fetchone()
                    old_value = res[0] if res and res[0] else ''
                    new_value = set([x.strip() for x in old_value.split(',') if x.strip()])
                    inconsistent = False
                    try:
                        update_field(new_value)
                    except KeyError, e:
                        inconsistent = True
                        self.env.log.warn('Inconsistent mastertickets data for ticket #%s. %s',
                                           self.tkt.id, exception_to_unicode(e))
                    new_value = ', '.join(sorted(new_value, key=lambda x: int(x)))

                    changed = old_value != new_value
                    if changed:
                        cursor.execute('INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue) VALUES (%s, %s, %s, %s, %s, %s)',
                                       (n, when_ts, author, field, old_value, new_value))

                        if comment and n not in commented_tickets:
                            cursor.execute('INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue) VALUES (%s, %s, %s, %s, %s, %s)',
                                           (n, when_ts, author, 'comment', '', '(In #%s) %s'%(self.tkt.id, comment)))
                            commented_tickets.add(n)

                    if not changed and not inconsistent:
                        continue

                    cursor.execute('UPDATE ticket_custom SET value=%s WHERE ticket=%s AND name=%s',
                                   (new_value, n, field))
                    updated = cursor.rowcount == 1

                    # refresh the changetime to prevent concurrent edits
                    cursor.execute('UPDATE ticket SET changetime=%s WHERE id=%s', (when_ts,n))

                    if not updated:
                        cursor.execute('INSERT INTO ticket_custom (ticket, name, value) VALUES (%s, %s, %s)',
                                       (n, field, new_value))

        if handle_commit:
            db.commit()

    def __nonzero__(self):
        return bool(self.blocking) or bool(self.blocked_by)

    def __repr__(self):
        def l(arr):
            arr2 = []
            for tkt in arr:
                if isinstance(tkt, Ticket):
                    tkt = tkt.id
                arr2.append(str(tkt))
            return '[%s]'%','.join(arr2)

        return '<mastertickets.model.TicketLinks #%s blocking=%s blocked_by=%s>'% \
               (self.tkt.id, l(getattr(self, 'blocking', [])), l(getattr(self, 'blocked_by', [])))

    @staticmethod
    def walk_tickets(env, tkt_ids, ticket_cache=None):
        """Return an iterable of all links reachable directly above or below those ones."""
        def visit(tkt, memo, next_fn):
            if tkt in memo:
                return False

            links = TicketLinks(env, tkt, ticket_cache)
            memo[tkt] = links

            for n in next_fn(links):
                visit(n, memo, next_fn)

        memo1 = {}
        memo2 = {}
        for id in tkt_ids:
            visit(id, memo1, lambda links: links.blocking)
            visit(id, memo2, lambda links: links.blocked_by)
        memo1.update(memo2)
        return memo1.itervalues()
