"""Conservative access to an existing narrator library. Inspection never writes."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid


@dataclass(frozen=True)
class LibraryPaths:
    root: Path

    def __post_init__(self):
        object.__setattr__(self, 'root', Path(self.root).resolve())

    @property
    def config(self): return self.root / 'config.json'
    @property
    def history_db(self): return self.root / 'history.json'
    @property
    def history(self): return self.root / 'history'
    @property
    def voices(self): return self.root / 'qwen_voices'


@dataclass
class LegacyInspection:
    root: str
    history_count: int
    voice_count: int
    errors: list[str]
    fingerprints: dict[str, str]


@dataclass
class AdoptionResult:
    root: Path
    backups: list[Path]


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path: Path, expected, default):
    if not path.exists(): return default
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, expected): raise ValueError(f'Invalid format: {path.name}')
    return value


def inspect_legacy(root: Path) -> LegacyInspection:
    paths = LibraryPaths(root)
    errors, fingerprints = [], {}
    history = []
    if not paths.root.is_dir(): errors.append('Library folder does not exist')
    for path, kind, default in ((paths.config, dict, {}), (paths.history_db, list, [])):
        try:
            value = _read(path, kind, default)
            if path == paths.history_db: history = value
            if path.is_file(): fingerprints[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
    voices = sum(1 for p in paths.voices.glob('*/meta.json') if p.is_file())
    return LegacyInspection(str(paths.root), len(history), voices, errors, fingerprints)


def adopt_legacy(root: Path, settings_path: Path) -> AdoptionResult:
    paths = LibraryPaths(root)
    inspection = inspect_legacy(paths.root)
    if inspection.errors: raise ValueError('; '.join(inspection.errors))
    backup_root = paths.root / '.narrator-backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backups = []
    for source in (paths.config, paths.history_db):
        if source.is_file():
            backup_root.mkdir(parents=True, exist_ok=True)
            target = backup_root / source.name
            shutil.copy2(source, target)
            backups.append(target)
    settings = _read(settings_path, dict, {})
    settings.update({'schema_version': 1, 'library_root': str(paths.root)})
    atomic_json(settings_path, settings)
    return AdoptionResult(paths.root, backups)


def read_history(paths: LibraryPaths) -> list[dict]:
    items = _read(paths.history_db, list, [])
    entries = []
    for item in items:
        if not isinstance(item, dict): continue
        entry = dict(item)
        name = str(entry.get('filename') or '')
        safe = bool(name) and Path(name).name == name and '/' not in name and '\\' not in name
        audio = (paths.history / name).resolve() if safe else None
        entry['available'] = bool(audio and audio.parent == paths.history.resolve() and audio.is_file())
        entry.setdefault('id', name)
        entries.append(entry)
    return entries
