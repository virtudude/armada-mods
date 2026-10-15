import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from main import Bridge, screen_packet
from models import inventory_has_form

class ModelBridgeTests(unittest.TestCase):
    def test_only_owned_inventory_forms_are_requested_without_game_rpc(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge(d); b.connected=True
            b.root={'Inventory':{'Version':3,'1':[{'formID':42}]}}
            b.models=Mock(); b.rpc=Mock()
            for form in [True,-1,0,43,'42',0x100000000]:
                b.input(json.dumps({'action':'preview_model','formID':form}))
            b.models.request.assert_not_called()
            b.input(json.dumps({'action':'preview_model','formID':42}))
            b.models.request.assert_called_once_with(42)
            b.rpc.assert_not_called()
            self.assertEqual(b.last_action,0)

    def test_static_artwork_never_expands_live_packet(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge(d)
            b.assets={'animations':{'quests':'x'*2_000_000},'models':{'42':{'status':'ready','path':'assets/models/42.json'}}}
            packet=screen_packet(3,b.wire_state())
            self.assertLess(len(packet),1000)
            decoded=json.loads(packet[16:])
            self.assertNotIn('assets',decoded)
            self.assertEqual(decoded['models'],b.assets['models'])
