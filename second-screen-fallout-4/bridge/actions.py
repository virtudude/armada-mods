"""Allowlisted actions resolved from current state, never caller-supplied RPCs."""
import math
import secrets
import time

LOCKS = ('IsDataUnavailable', 'IsLoading', 'IsPlayerDead', 'IsPipboyNotEquipped',
         'IsPlayerPipboyLocked', 'IsPlayerInDialogue', 'IsInVats', 'IsInVatsPlayback',
         'IsInAnimation', 'IsPlayerMovementLocked')


def locked(root):
    status = root.get('Status')
    return not isinstance(status, dict) or any(status.get(k, False) for k in LOCKS)


def find(entries, ident):
    return next((v for v in entries if isinstance(v, dict) and v.get('_id') == ident), None)


class Actions:
    def __init__(self):
        self.pending = None
        self.deadline = 0

    def cancel(self):
        self.pending = None

    def confirmation(self):
        if self.pending and time.monotonic() >= self.deadline:
            self.cancel()
        if not self.pending:
            return None
        return {k: self.pending[k] for k in ('token', 'label', 'expires')}

    def handle(self, msg, root):
        if not isinstance(msg, dict):
            raise ValueError('Invalid input')
        action = msg.get('action')
        if action == 'cancel':
            self.cancel()
            return None
        confirmed = False
        if action == 'confirm':
            pending = self.pending
            self.cancel()  # Single use, including stale or invalid attempts.
            if not pending or time.monotonic() >= self.deadline or msg.get('token') != pending['token']:
                raise ValueError('Confirmation expired')
            msg, confirmed = pending['request'], True
            action = msg['action']
        else:
            self.cancel()
        if action == 'localmap':
            return 13, []
        if locked(root):
            raise ValueError('Pip-Boy controls are unavailable right now')
        if action in ('stimpak', 'radaway'):
            inv = root.get('Inventory', {})
            if not inv.get(action + 'ObjectIDIsValid'):
                raise ValueError('No ' + action + ' available')
            msg = {**msg, 'action': 'use', 'id': inv.get(action + 'ObjectID')}
            action = 'use'
        ident = msg.get('id')
        needs_confirmation = False
        if action == 'use':
            inv = root.get('Inventory', {})
            if type(msg.get('version')) is not int or msg['version'] != inv.get('Version'):
                raise ValueError('Inventory changed; select the item again')
            items = [item for key, group in inv.items() if key.isdecimal() and isinstance(group, list) for item in group]
            item = find(items, ident)
            if not item or not item.get('StackID') or item.get('count', 0) <= 0:
                raise ValueError('Item is no longer available')
            flags = item.get('filterFlag', 0)
            if not flags & (2 | 4 | 8 | 128 | 8192):
                raise ValueError('This item cannot be used from the companion')
            rpc = (0, [item['HandleID'], item['StackID'][0], inv['Version']])
            needs_confirmation = not flags & (2 | 4)
            label = 'Use ' + str(item.get('text', 'item')) + '?'
        elif action == 'radio':
            station = find(root.get('Radio', []), ident)
            if not station or not station.get('inRange'):
                raise ValueError('Radio station is out of range')
            rpc = (12, [ident])
        elif action == 'quest':
            quest = find(root.get('Quests', []), ident)
            if not quest or not all(k in quest for k in ('formID', 'instance', 'type')):
                raise ValueError('Quest is no longer available')
            rpc = (5, [quest['formID'], quest['instance'], quest['type']])
        elif action == 'travel':
            loc = find(root.get('Map', {}).get('World', {}).get('Locations', []), ident)
            if not loc or not loc.get('Visible') or not loc.get('Discovered'):
                raise ValueError('Location is not available for travel')
            rpc = (9, [ident])
            needs_confirmation = True
            label = 'Fast travel to ' + str(loc.get('Name', 'location')) + '?'
        elif action == 'marker':
            x, y = msg.get('x'), msg.get('y')
            if not all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1e8 for v in (x, y)):
                raise ValueError('Invalid marker coordinates')
            rpc = (6, [x, y, bool(msg.get('local'))])
        elif action == 'clear-marker':
            rpc = (7, [])
        else:
            raise ValueError('Unknown action')
        if needs_confirmation and not confirmed:
            self.deadline = time.monotonic() + 5
            self.pending = {'token': secrets.token_hex(12), 'label': label,
                            'expires': time.time() + 5, 'request': dict(msg)}
            return None
        return rpc
