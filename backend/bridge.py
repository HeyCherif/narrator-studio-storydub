"""Private JSON-lines sidecar. No network listener or unrestricted command dispatch."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import threading

from .library import LibraryPaths
from .runtime import NarratorRuntime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', required=True)
    args = parser.parse_args()
    output, lock = sys.stdout, threading.Lock()
    sys.stdout = sys.stderr

    def send(value):
        with lock:
            output.write(json.dumps(value, ensure_ascii=True) + '\n')
            output.flush()

    runtime, startup_error = None, None
    try:
        with redirect_stdout(sys.stderr):
            runtime = NarratorRuntime(LibraryPaths(Path(args.library)), send)
    except Exception as exc:
        startup_error = str(exc)
    try:
        for line in sys.stdin:
            if len(line) > 32_000_000:
                send({'id': None, 'ok': False, 'error': {'code': 'message-too-large'}})
                continue
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict): raise ValueError('invalid-request')
                command = request.get('command')
                if startup_error:
                    send({'id': request.get('id'), 'ok': False,
                          'error': {'code': 'library-unavailable', 'message': startup_error}})
                    if command == 'shutdown': break
                    continue
                with redirect_stdout(sys.stderr):
                    result = runtime.dispatch(command, request.get('payload', {}))
                send({'id': request.get('id'), 'ok': True, 'result': result})
                if command == 'shutdown': break
            except Exception as exc:
                code = str(exc) if str(exc) in {'unknown-command', 'invalid-request', 'invalid-payload', 'text-required', 'operation-in-progress'} else 'runtime-error'
                send({'id': request.get('id') if isinstance(request, dict) else None, 'ok': False,
                      'error': {'code': code, 'message': str(exc)}})
    finally:
        if runtime:
            with redirect_stdout(sys.stderr): runtime.shutdown()
    return 0


if __name__ == '__main__': raise SystemExit(main())

