#!/usr/bin/env python3
"""Local Fallout companion -> Armada screen-host bridge (Python stdlib only)."""
import json
import os
from pathlib import Path
import select
import signal
import socket
import struct
import sys
import time

from models import ModelLoader, inventory_has_form
from actions import Actions
from protocol import Database, Framer, ProtocolError, local_map, packet


def json_bytes(obj):
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def screen_packet(kind, obj):
    data = json_bytes(obj)
    if len(data) > 1024 * 1024:
        raise ProtocolError('Pip-Boy state exceeds screen-host limit')
    return struct.pack('<4sHHII', b'A2SS', kind, 0, len(data), 0) + data


class Bridge:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.assets = json.loads((self.data_dir / 'assets/manifest.json').read_text())
        except (OSError, ValueError):
            self.assets = {}
        self.host = self.game = None
        self.host_frames = Framer(host=True)
        self.game_frames = Framer()
        self.db = Database()
        self.root = {}
        self.actions = Actions()
        self.local = None
        self.map_context = None
        self.map_revision = 0
        self.connected = False
        self.message = 'Waiting for Fallout 4’s Pip-Boy service…'
        self.notice = ''
        self.notice_until = 0
        self.next_game = self.next_host = self.heartbeat = self.last_received = 0
        self.dirty = True
        self.last_publish = self.last_action = self.last_map_request = 0
        self.request_id = 0
        self.running = True
        self.models = ModelLoader(os.environ.get("ARMADA_MOD_GAME_DIR"), self.data_dir)

    def close_game(self, message):
        if self.game:
            self.game.close()
        self.game = None
        self.connected = False
        self.root = {}
        self.db = Database()
        self.game_frames = Framer()
        self.local = self.map_context = None
        self.actions.cancel()
        self.message = message
        self.dirty = True
        self.next_game = time.monotonic() + 3

    def rpc(self, typ, args):
        if not self.game or not self.connected:
            raise ValueError('Game disconnected')
        self.request_id += 1
        self.game.sendall(packet(5, json_bytes({'type': typ, 'args': args, 'id': self.request_id})))

    def connect(self, now):
        if self.host is None and now >= self.next_host:
            self.next_host = now + 1
            try:
                self.host = socket.create_connection(('127.0.0.1', int(os.environ.get('ARMADA_SECOND_SCREEN_PORT', '47800'))), .5)
                self.host.settimeout(2)
                self.host.sendall(screen_packet(1, {'appid': 377160}))
                self.host_frames = Framer(host=True)
                self.dirty = True
            except OSError:
                if self.host:
                    self.host.close()
                self.host = None
        if self.game is None and now >= self.next_game:
            self.next_game = now + 3
            try:
                # Never discover/broadcast or connect to another player's game.
                self.game = socket.create_connection(('127.0.0.1', 27000), .5)
                self.game.settimeout(2)
                self.last_received = now
                self.heartbeat = 0
                self.message = 'Connecting to Pip-Boy…'
                self.dirty = True
            except OSError:
                self.close_game('Waiting for Fallout 4’s companion service. Start or restart Fallout 4 with this mod enabled.')

    def game_message(self, kind, body):
        if kind == 1:
            meta = json.loads(body)
            print('Pip-Boy connection accepted:', meta, flush=True)
            self.connected = True
            self.message = 'Load a save to use your Pip-Boy.'
        elif kind == 2:
            self.close_game('Another Pip-Boy app is connected. Disconnect it to use the bottom screen.')
        elif kind == 3:
            self.db.update(body)
            root = self.db.resolve()
            if isinstance(root, dict):
                self.root = root
                self.message = '' if root.get('PlayerInfo') else 'Load a save to use your Pip-Boy.'
                current_map = (root.get('Map', {}).get('CurrWorldspace'), root.get('Map', {}).get('CurrCell'))
                if self.map_context != current_map:
                    self.local = None
                    self.map_context = current_map
        elif kind == 4:
            png, meta = local_map(body)
            target = self.data_dir / 'local-map.png'
            temp = target.with_suffix('.tmp')
            temp.write_bytes(png)
            temp.replace(target)
            self.map_revision += 1
            meta['url'] = 'local-map.png?v=' + str(self.map_revision)
            self.local = meta
        elif kind == 6:
            response = json.loads(body)
            self.notice = response.get('message') or ('Action accepted.' if response.get('success') else 'The game could not perform that action.')
            self.notice_until = time.monotonic() + 5
        self.dirty = True

    def input(self, body):
        now = time.monotonic()
        try:
            msg = json.loads(body)
            if not self.connected:
                raise ValueError('Game disconnected')
            if msg.get('action') == 'preview_model':
                form_id = msg.get('formID')
                if inventory_has_form(self.root.get('Inventory'), form_id):
                    existing = self.assets.get('models', {}).get(str(form_id))
                    if existing is None:
                        self.models.request(form_id)
                return
            if now - self.last_action < .2:
                return
            self.last_action = now
            if msg.get('action') == 'localmap':
                if now - self.last_map_request < 1:
                    return
                self.last_map_request = now
            rpc = self.actions.handle(msg, self.root)
            if rpc:
                self.rpc(*rpc)
                self.notice = 'Sent to game.'
                self.notice_until = now + 2
        except (ValueError, KeyError, TypeError) as exc:
            self.notice = str(exc)
            self.notice_until = now + 5
        self.dirty = True

    def state(self):
        # Unlearned perks and undiscovered/invisible locations dominate the wire
        # database. Keep them internally for validation; do not reveal spoilers.
        data = dict(self.root)
        data['Perks'] = [p for p in data.get('Perks', []) if isinstance(p, dict) and p.get('Rank', 0) > 0 and p.get('ListVisible', True)]
        if isinstance(data.get('Map'), dict):
            data['Map'] = dict(data['Map'])
            world = dict(data['Map'].get('World') or {})
            world['Locations'] = [p for p in world.get('Locations', []) if isinstance(p, dict) and p.get('Visible')]
            data['Map']['World'] = world
        return {'connected': self.connected, 'message': self.message, 'data': data,
                'assets': self.assets, 'localMap': self.local, 'notice': self.notice,
                'confirm': self.actions.confirmation()}

    def wire_state(self):
        # Thousands of immutable quest-frame paths are already in the native
        # host's local manifest. Only newly prepared model descriptors vary.
        snapshot = self.state()
        snapshot.pop('assets', None)
        snapshot['models'] = self.assets.get('models', {})
        return snapshot

    def run(self):
        while self.running:
            now = time.monotonic()
            completed_models = self.models.drain()
            if completed_models:
                self.assets.setdefault('models', {}).update(completed_models)
                self.dirty = True
            self.connect(now)
            if self.game:
                try:
                    if now - self.last_received > 12:
                        raise OSError('Pip-Boy timed out')
                    if now >= self.heartbeat:
                        self.game.sendall(packet(0))
                        self.heartbeat = now + 1
                except OSError as exc:
                    self.close_game(str(exc))
            if self.actions.pending and self.actions.confirmation() is None:
                self.dirty = True
            if self.notice and now >= self.notice_until:
                self.notice = ''
                self.dirty = True
            if self.host and self.dirty and now - self.last_publish >= .15:
                try:
                    self.host.sendall(screen_packet(3, self.wire_state()))
                    self.dirty = False
                    self.last_publish = now
                except (OSError, ProtocolError) as exc:
                    print('screen-host:', exc, file=sys.stderr, flush=True)
                    self.host.close()
                    self.host = None
            peers = [s for s in (self.host, self.game) if s]
            ready, _, _ = select.select(peers, [], [], .1)
            for peer in ready:
                try:
                    body = peer.recv(65536)
                    if not body:
                        raise OSError('Connection closed')
                    if peer is self.game:
                        self.last_received = time.monotonic()
                        for kind, payload in self.game_frames.feed(body):
                            self.game_message(kind, payload)
                            if self.game is None:
                                break
                    else:
                        for kind, payload in self.host_frames.feed(body):
                            if kind == 16:
                                self.input(payload)
                except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
                    if peer is self.game:
                        print('Pip-Boy:', exc, file=sys.stderr, flush=True)
                        self.close_game('Pip-Boy disconnected. Reconnecting…')
                    else:
                        peer.close()
                        self.host = None
                        self.actions.cancel()
        for peer in (self.host, self.game):
            if peer:
                peer.close()


if __name__ == '__main__':
    bridge = Bridge(os.environ['ARMADA_MOD_DATA_DIR'])
    signal.signal(signal.SIGTERM, lambda *_: setattr(bridge, 'running', False))
    signal.signal(signal.SIGINT, lambda *_: setattr(bridge, 'running', False))
    bridge.run()
