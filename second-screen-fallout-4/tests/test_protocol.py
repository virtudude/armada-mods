import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bridge'))
from protocol import Database, Framer, ProtocolError, packet, local_map
from actions import Actions
from main import Bridge, screen_packet


def scalar(ident, value):
    return struct.pack('<BIi', 3, ident, value)


def obj(ident, entries, removed=()):
    result = struct.pack('<BIH', 8, ident, len(entries))
    for name, ref in entries.items():
        result += struct.pack('<I', ref) + name.encode() + b'\0'
    return result + struct.pack('<H', len(removed)) + b''.join(struct.pack('<I', r) for r in removed)


class ProtocolTests(unittest.TestCase):
    def test_fragmented_and_coalesced_frames(self):
        wire = packet(1, b'{"version":"test"}') + packet(0) + packet(3, b'abc')
        f = Framer()
        actual = []
        for byte in wire:
            actual.extend(f.feed(bytes([byte])))
        self.assertEqual(actual, [(1, b'{"version":"test"}'), (0, b''), (3, b'abc')])
        self.assertEqual(Framer().feed(wire), actual)
        f = Framer(host=True)
        self.assertEqual(f.feed(screen_packet(16, {'action': 'cancel'}))[0][0], 16)

    def test_bad_lengths_and_magic(self):
        with self.assertRaises(ProtocolError):
            Framer().feed(struct.pack('<IB', 0xffffffff, 3))
        with self.assertRaises(ProtocolError):
            Framer(True).feed(b'x' * 16)

    def test_partial_object_updates_references_and_removal(self):
        db = Database()
        db.update(scalar(2, 10) + scalar(3, 20) + obj(1, {'a': 2, 'b': 3}) + obj(0, {'parent': 1}))
        db.update(scalar(2, 11) + scalar(4, 30) + obj(1, {'c': 4}, [3]))
        self.assertEqual(db.resolve(), {'_id': 0, 'parent': {'_id': 1, 'a': 11, 'c': 30}})

    def test_malformed_packet_is_atomic(self):
        db = Database()
        db.update(scalar(1, 10))
        for bad in (b'\x06\x01\0\0\0unterminated', b'\xff\0\0\0\0', b'\x03\0'):
            with self.assertRaises(ProtocolError):
                db.update(scalar(1, 20) + bad)
            self.assertEqual(db.resolve(1), 10)

    def test_all_types_and_cycles(self):
        db = Database()
        data = b''
        for typ, fmt, value in [(0,'B',1), (1,'b',-100), (2,'B',255), (3,'i',-100000), (4,'I',0xffffffff), (5,'f',1.25)]:
            data += struct.pack('<BI' + fmt, typ, typ + 1, value)
        data += struct.pack('<BI', 6, 7) + 'café'.encode() + b'\0'
        data += struct.pack('<BIH7I', 7, 8, 7, *range(1,8))
        db.update(data)
        self.assertEqual(db.resolve(8), [True,-100,255,-100000,0xffffffff,1.25,'café'])
        db.update(obj(0, {'cycle': 0}))
        with self.assertRaises(ProtocolError):
            db.resolve()

    def test_live_map_png_and_validation(self):
        payload = struct.pack('<II6f', 2, 2, -1, 1, 1, 1, -1, -1) + bytes([0,64,128,255])
        png, meta = local_map(payload)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertEqual(meta['extents']['NWX'], -1)
        with self.assertRaises(ProtocolError):
            local_map(payload[:-1])


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.actions = Actions()
        self.item = {'_id': 20, 'HandleID': 42, 'StackID': [7], 'filterFlag': 8, 'text': 'Test aid', 'count': 2}
        self.root = {'Status': {}, 'Inventory': {'Version': 5, '48': [self.item]},
                     'Radio': [{'_id': 30, 'inRange': True}],
                     'Quests': [{'_id': 40, 'formID': 11, 'instance': 12, 'type': 13}],
                     'Map': {'World': {'Locations': [{'_id': 50, 'Visible': True, 'Discovered': True, 'Name': 'Test'}]}}}
        self.use = {'action': 'use', 'id': 20, 'version': 5}

    def confirm(self):
        return self.actions.handle({'action': 'confirm', 'token': self.actions.confirmation()['token']}, self.root)

    def test_equip_is_direct_and_uses_actual_stack(self):
        self.item['filterFlag'] = 2
        self.assertEqual(self.actions.handle(self.use, self.root), (0, [42, 7, 5]))

    def test_consumable_confirmation_single_use(self):
        self.assertIsNone(self.actions.handle(self.use, self.root))
        token = self.actions.confirmation()['token']
        self.assertEqual(self.confirm(), (0, [42, 7, 5]))
        with self.assertRaises(ValueError):
            self.actions.handle({'action': 'confirm', 'token': token}, self.root)

    def test_stale_inventory_and_expiry(self):
        self.actions.handle(self.use, self.root)
        self.root['Inventory']['Version'] += 1
        with self.assertRaisesRegex(ValueError, 'Inventory changed'):
            self.confirm()
        self.root['Inventory']['Version'] = 5
        self.actions.handle(self.use, self.root)
        self.actions.deadline = 0
        self.assertIsNone(self.actions.confirmation())

    def test_locked_game_and_untrusted_id(self):
        for flag in ('IsLoading','IsPlayerPipboyLocked','IsPipboyNotEquipped','IsPlayerDead','IsPlayerInDialogue'):
            self.root['Status'] = {flag: True}
            with self.assertRaises(ValueError):
                self.actions.handle(self.use, self.root)
        self.root['Status'] = {}
        with self.assertRaises(ValueError):
            self.actions.handle({**self.use, 'id': 30}, self.root)

    def test_quest_radio_and_travel(self):
        self.assertEqual(self.actions.handle({'action':'quest','id':40}, self.root), (5,[11,12,13]))
        self.assertEqual(self.actions.handle({'action':'radio','id':30}, self.root), (12,[30]))
        self.actions.handle({'action':'travel','id':50}, self.root)
        self.assertEqual(self.confirm(), (9,[50]))
        self.root['Radio'][0]['inRange'] = False
        with self.assertRaises(ValueError):
            self.actions.handle({'action':'radio','id':30}, self.root)

    def test_cancel_and_recheck_after_selection(self):
        self.actions.handle(self.use, self.root)
        token = self.actions.confirmation()['token']
        self.actions.handle({'action':'cancel'}, self.root)
        with self.assertRaises(ValueError):
            self.actions.handle({'action':'confirm','token':token}, self.root)
        self.actions.handle(self.use, self.root)
        self.root['Status']['IsLoading'] = True
        with self.assertRaises(ValueError):
            self.confirm()

    def test_status_aid_uses_game_object_id_and_confirmation(self):
        self.root['Inventory'].update(stimpakObjectID=20, stimpakObjectIDIsValid=True)
        self.assertIsNone(self.actions.handle({'action':'stimpak','version':5}, self.root))
        self.assertEqual(self.confirm(), (0,[42,7,5]))
        self.root['Inventory']['stimpakObjectIDIsValid'] = False
        with self.assertRaisesRegex(ValueError, 'No stimpak'):
            self.actions.handle({'action':'stimpak','version':5}, self.root)

    def test_marker_rejects_invalid_coordinates(self):
        for x in (None, float('nan'), float('inf'), 1e30, '1'):
            with self.assertRaises(ValueError):
                self.actions.handle({'action':'marker','x':x,'y':0}, self.root)


class BridgeTests(unittest.TestCase):
    def test_disconnect_clears_state_pending_and_map(self):
        with tempfile.TemporaryDirectory() as d:
            bridge = Bridge(d)
            bridge.root = {'PlayerInfo': {'PlayerName': 'Test'}}
            bridge.connected = True
            bridge.local = {'url':'stale.png'}
            bridge.close_game('disconnected')
            state = bridge.state()
            self.assertFalse(state['connected'])
            self.assertNotIn('PlayerInfo', state['data'])
            self.assertIsNone(state['localMap'])
            self.assertIsNone(state['confirm'])

    def test_filter_does_not_mutate_database_or_reveal_spoilers(self):
        with tempfile.TemporaryDirectory() as d:
            bridge = Bridge(d)
            bridge.root = {'Perks': [{'Rank':0}, {'Rank':1}], 'Map':{'World':{'Locations':[{'Visible':False},{'Visible':True}]}}}
            original = copy.deepcopy(bridge.root)
            state = bridge.state()
            self.assertEqual(len(state['data']['Perks']), 1)
            self.assertEqual(len(state['data']['Map']['World']['Locations']), 1)
            self.assertEqual(bridge.root, original)


if __name__ == '__main__':
    unittest.main()
