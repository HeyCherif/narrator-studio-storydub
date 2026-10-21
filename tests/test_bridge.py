import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from backend.runtime import NarratorRuntime
from backend.library import LibraryPaths


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events = []
        self.runtime = NarratorRuntime(LibraryPaths(Path(self.tmp.name)), self.events.append)
        self.addCleanup(self.runtime.shutdown)

    def test_unknown_command_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown-command'):
            self.runtime.dispatch('__getattribute__', {})

    def test_locked_library_returns_a_readable_protocol_error(self):
        requests = '\n'.join(json.dumps({'id': i, 'command': c, 'payload': {}})
                             for i, c in enumerate(('bootstrap', 'shutdown')))
        result = subprocess.run([sys.executable, '-m', 'backend.bridge', '--library', self.tmp.name],
                                input=requests+'\n', capture_output=True, text=True, timeout=30)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(replies), 2)
        self.assertIn('library-in-use', replies[0]['error']['message'])

    def test_bootstrap_does_not_load_models(self):
        result = self.runtime.dispatch('bootstrap', {})
        self.assertIn('runtime', result)
        self.assertIsNone(self.runtime.core.worker.proc)
        self.assertIsNone(self.runtime.core.qwen_worker.proc)
        self.assertFalse(self.runtime.core.job['running'])

    def test_stdout_contains_only_protocol_lines(self):
        self.runtime.shutdown()
        requests = '\n'.join(json.dumps({'id': i, 'command': command, 'payload': {}})
                             for i, command in enumerate(('bootstrap', 'not-allowed', 'shutdown')))
        result = subprocess.run([sys.executable, '-m', 'backend.bridge', '--library', self.tmp.name],
                                input=requests+'\n', capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in replies if 'id' in r], [0, 1, 2])
        self.assertTrue(replies[0]['ok'])
        self.assertEqual(replies[1]['error']['code'], 'unknown-command')

    def test_cancel_ignores_late_job_events(self):
        self.runtime.job_id = 'new-job'
        self.runtime.emit_job('old-job', {'running': False})
        self.assertEqual(self.events, [])
        self.runtime.emit_job('new-job', {'running': True})
        self.assertEqual(self.events[0]['job_id'], 'new-job')

    def test_shutdown_drains_owned_workers(self):
        self.runtime.shutdown()
        self.assertIsNone(self.runtime.core.worker.proc)
        self.assertIsNone(self.runtime.core.qwen_worker.proc)
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            self.runtime.dispatch('bootstrap', {})

    def test_generate_validates_before_starting_worker(self):
        with self.assertRaisesRegex(ValueError, 'text-required'):
            self.runtime.dispatch('generate', {'text': '  '})
        self.assertIsNone(self.runtime.core.worker.proc)

    def test_new_job_does_not_reuse_previous_audio_result(self):
        import threading
        waiting = threading.Event()
        self.runtime.core._set_job(result={'filename': 'previous.wav'})
        self.runtime.core._warmup = lambda: waiting.wait(2)
        try:
            self.runtime.dispatch('generate', {'text': 'New narration'})
            self.assertIsNone(self.runtime.core.get_job().get('result'))
        finally:
            waiting.set()

    def test_shutdown_prevents_late_worker_start_and_retains_library_lock(self):
        import threading
        from backend.library import LibraryLock
        entered, release = threading.Event(), threading.Event()
        def blocked_clone(payload):
            entered.set()
            release.wait(3)
            self.runtime.core.qwen_worker.start()
        self.runtime.core.qwen_clone = blocked_clone
        self.runtime.dispatch('clone_voice', {})
        self.assertTrue(entered.wait(2))
        self.runtime.shutdown(timeout_seconds=0)
        try:
            with self.assertRaisesRegex(RuntimeError, 'library-in-use'):
                LibraryLock(Path(self.tmp.name))
        finally:
            release.set()
            self.runtime.operation.join(3)
        self.assertIsNone(self.runtime.core.qwen_worker.proc)
        lock = LibraryLock(Path(self.tmp.name))
        lock.close()

    def test_configure_stops_resident_workers_before_changing_paths(self):
        from unittest.mock import Mock
        for worker in (self.runtime.core.worker, self.runtime.core.qwen_worker, self.runtime.core.qc_worker):
            worker.stop = Mock()
        self.runtime.dispatch('configure', {'model_path': self.tmp.name})
        self.runtime.core.worker.stop.assert_called_once()
        self.assertEqual(self.runtime.core.config['model_path'], self.tmp.name)


if __name__ == '__main__': unittest.main()
