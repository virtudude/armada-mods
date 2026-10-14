"""Read-only, serialized model extraction kept off the companion socket loop."""
import importlib.util
from pathlib import Path
import queue
import threading
import sys


class ModelLoader:
    def __init__(self, game_dir, data_dir):
        self.game_dir = game_dir
        self.data_dir = data_dir
        self.requests = queue.Queue(maxsize=16)
        self.results = queue.Queue(maxsize=16)
        self.pending = set()
        self.thread = None

    def request(self, form_id):
        if form_id in self.pending:
            return
        try:
            self.requests.put_nowait(form_id)
        except queue.Full:
            return
        self.pending.add(form_id)
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='pipboy-model-assets', daemon=True)
            self.thread.start()

    def _run(self):
        try:
            path = Path(__file__).resolve().parents[1] / 'tools/model_assets.py'
            if str(path.parent) not in sys.path:
                sys.path.insert(0, str(path.parent))
            spec = importlib.util.spec_from_file_location('pipboy_model_assets', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            prepare = module.prepare_model
        except Exception as exc:
            prepare = None
            failure = str(exc)
        while True:
            form_id = self.requests.get()
            try:
                if prepare is None or not self.game_dir:
                    raise ValueError(failure if prepare is None else 'Game install unavailable')
                result = prepare(self.game_dir, self.data_dir, form_id)
            except Exception as exc:
                result = {'status': 'unsupported', 'reason': str(exc)}
            self.results.put((form_id, result))

    def drain(self):
        ready = {}
        while True:
            try:
                form_id, result = self.results.get_nowait()
            except queue.Empty:
                return ready
            self.pending.discard(form_id)
            ready[str(form_id)] = result


def inventory_has_form(inventory, form_id):
    if not isinstance(form_id, int) or isinstance(form_id, bool) or not 0 < form_id <= 0xffffffff:
        return False
    if not isinstance(inventory, dict):
        return False
    return any(isinstance(item, dict) and item.get('formID') == form_id
               for items in inventory.values() if isinstance(items, list)
               for item in items)
