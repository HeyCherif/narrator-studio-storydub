"""Verify an explicit Windows delivery folder, with no access to user libraries."""
import argparse
import hashlib
import json
from pathlib import Path

VERSION = '2.0.0-beta.1'
ALLOWED = {'NarratorStudio.exe', 'narrator-bridge.exe', 'README.txt', 'THIRD_PARTY_NOTICES.txt',
           'SHA256SUMS.txt', 'distribution.json'}

def verify(root: Path):
    files = [p for p in root.rglob('*') if p.is_file()]
    for path in files:
        name = path.name
        if name not in ALLOWED and not (name.startswith('Narrator Studio_') and name.endswith('_x64-setup.exe')):
            raise ValueError('Unexpected distribution file: ' + str(path.relative_to(root)))
    for name in ('NarratorStudio.exe', 'narrator-bridge.exe'):
        path = root / name
        if not path.is_file() or path.read_bytes()[:2] != b'MZ':
            raise ValueError('Missing Windows executable: ' + name)
    return {'version': VERSION, 'files': {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files if p.name not in {'distribution.json', 'SHA256SUMS.txt'}}}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    result = verify(args.folder)
    (args.folder / 'distribution.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (args.folder / 'SHA256SUMS.txt').write_text(''.join(f'{digest}  {name}\n' for name, digest in result['files'].items()), encoding='utf-8')
    print(f"Validated {len(result['files'])} files · {VERSION}")
