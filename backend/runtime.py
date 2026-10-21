"""Headless owner of the existing synthesis pipeline; one library per instance."""
import importlib.util
from pathlib import Path
import threading
import time
import uuid

from .library import LibraryPaths, LibraryLock, read_history, inspect_legacy


class NarratorRuntime:
    def __init__(self, paths: LibraryPaths, emit, lazy=True):
        self.paths, self.emit, self.closed = paths, emit, False
        if paths.root.exists():
            errors = inspect_legacy(paths.root).errors
            if errors: raise ValueError('; '.join(errors))
        self.library_lock = LibraryLock(paths.root)
        self.job_id = ''
        self.operation = None
        self.operation_active = False
        self.lock = threading.RLock()
        spec = importlib.util.spec_from_file_location('narrator_engine_' + uuid.uuid4().hex,
                                                    Path(__file__).with_name('engine.py'))
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        engine.CONFIG_PATH = paths.config
        engine.HISTORY_DB = paths.history_db
        engine.HISTORY_DIR = paths.history
        engine.WORK_DIR = paths.history / '.work'
        engine.QWEN_VOICES_DIR = paths.voices
        engine.QWEN_DEFAULT_MODEL_DIR = paths.root / 'models/Qwen3-TTS-12Hz-0.6B-Base'
        self.core = engine.AppAPI(None, warmup=not lazy)
        for worker in (self.core.worker, self.core.qwen_worker, self.core.qc_worker):
            original_start = worker.start
            def guarded_start(worker=worker, original_start=original_start):
                with worker.lock:
                    if self.closed or self.core._cancelled(): raise RuntimeError('operation-cancelled')
                    return original_start()
            worker.start = guarded_start

    def emit_job(self, job_id, payload):
        if job_id == self.job_id and not self.closed:
            self.emit({'event': 'job', 'job_id': job_id, 'payload': payload})

    def _start(self, kind, payload):
        with self.lock:
            if self.closed: raise RuntimeError('closed')
            if self.operation_active:
                raise RuntimeError('operation-in-progress')
            if kind == 'generate' and not str(payload.get('text') or '').strip():
                raise ValueError('text-required')
            if kind == 'generate' and len(str(payload.get('text'))) > 500_000:
                raise ValueError('text-too-large')
            self.job_id = uuid.uuid4().hex
            self.operation_active = True
            job_id = self.job_id
            self.core._set_job(running=True, cancel_requested=False, result=None, error='', stage='Preparation', progress=0)

            def run():
                try:
                    if kind == 'clone':
                        result = self.core.qwen_clone(payload)
                        self.core._set_job(running=False, stage='Voice ready', result=result, kind='clone')
                    else:
                        engine = payload.get('engine', self.core.active_engine)
                        if engine not in {'omnivoice', 'qwen'}: raise ValueError('invalid-engine')
                        self.core.active_engine = engine
                        self.core._warmup()
                        if self.core._cancelled(): return
                        if not self.core.job.get('ready'): raise RuntimeError(self.core.job.get('error') or 'runtime-unavailable')
                        target = self.core._generate_qwen_thread if engine == 'qwen' else self.core._generate_thread
                        target(dict(payload))
                except Exception as exc:
                    self.core._set_job(running=False, stage='Error', error=str(exc))
                finally:
                    with self.lock:
                        self.core._set_job(running=False)
                        if self.closed:
                            for worker in (self.core.worker, self.core.qwen_worker, self.core.qc_worker): worker.kill()
                            self.library_lock.close()
                        self.operation_active = False
                        self.emit_job(job_id, dict(self.core.get_job()))

            self.operation = threading.Thread(target=run, daemon=True)
            self.operation.start()

            def monitor():
                previous = None
                while not self.closed:
                    with self.lock:
                        if not self.operation_active or self.job_id != job_id: break
                        snapshot = dict(self.core.get_job(), running=True)
                        if snapshot != previous:
                            self.emit_job(job_id, snapshot)
                            previous = snapshot
                    time.sleep(.15)
            threading.Thread(target=monitor, daemon=True).start()
            return {'accepted': True, 'job_id': job_id}

    def dispatch(self, command: str, payload: dict):
        if self.closed: raise RuntimeError('closed')
        if not isinstance(payload, dict): raise ValueError('invalid-payload')
        if command == 'bootstrap':
            result = self.core.get_bootstrap()
            result['version'] = '2.0.0-beta.1'
            result['library_root'] = str(self.paths.root)
            with self.lock:
                result['job_id'] = self.job_id
                result['job'] = dict(self.core.get_job(), running=self.operation_active)
            return result
        if command == 'history': return read_history(self.paths)
        if command == 'voices':
            return {'omnivoice': self.core.get_bootstrap()['voices'], 'qwen': self.core.qwen_status()['voices']}
        if command == 'set_engine': return self.core.set_engine(payload.get('engine', 'omnivoice'))
        if command == 'generate': return self._start('generate', payload)
        if command == 'clone_voice': return self._start('clone', payload)
        if command == 'cancel_generate':
            self.core._set_job(cancel_requested=True, stage='Cancelling')
            for worker in (self.core.worker, self.core.qwen_worker, self.core.qc_worker): worker.kill()
            return {'ok': True}
        if command == 'configure':
            with self.lock:
                if self.operation_active: raise RuntimeError('operation-in-progress')
                allowed = {'qwen_runtime_python', 'qwen_model_path', 'runtime_python', 'model_path', 'qc_runtime_python', 'qc_model_path'}
                if any(key not in allowed or not isinstance(value, str) for key, value in payload.items()):
                    raise ValueError('invalid-configuration')
                for key, value in payload.items():
                    path = Path(value)
                    if not (path.is_file() if key.endswith('python') else path.is_dir()):
                        raise ValueError('configuration-path-missing: ' + key)
                for worker in (self.core.worker, self.core.qwen_worker, self.core.qc_worker): worker.stop()
                self.core.config.update(payload)
                self.core._persist_config()
                return {'ok': True}
        if command == 'shutdown':
            self.shutdown()
            return {'ok': True}
        raise ValueError('unknown-command')

    def shutdown(self, timeout_seconds=5):
        if self.closed: return
        self.closed = True
        self.core._set_job(cancel_requested=True)
        for worker in (self.core.worker, self.core.qwen_worker, self.core.qc_worker): worker.kill()
        if self.operation and self.operation is not threading.current_thread(): self.operation.join(timeout_seconds)
        for worker in (self.core.worker, self.core.qwen_worker, self.core.qc_worker): worker.kill()
        if not self.operation or not self.operation.is_alive(): self.library_lock.close()
