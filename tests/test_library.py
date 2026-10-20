import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from backend.library import LibraryPaths, inspect_legacy, adopt_legacy, read_history


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'Données Studio'
        self.root.mkdir()
        (self.root / 'history').mkdir()
        (self.root / 'qwen_voices').mkdir()
        (self.root / 'config.json').write_text(json.dumps({'custom': {'keep': 7}}))
        (self.root / 'history.json').write_text(json.dumps([{'id': 'old', 'filename': 'missing.wav'}]))

    def test_inspection_is_read_only(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = inspect_legacy(self.root)
        self.assertEqual(result.history_count, 1)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_unknown_config_fields_survive(self):
        settings = Path(self.tmp.name) / 'settings.json'
        result = adopt_legacy(self.root, settings)
        self.assertEqual(json.loads((self.root / 'config.json').read_text(encoding='utf-8')), {'custom': {'keep': 7}})
        self.assertEqual(json.loads(settings.read_text(encoding='utf-8'))['library_root'], str(self.root.resolve()))
        self.assertEqual(len(result.backups), 2)
        self.assertEqual(json.loads(result.backups[0].read_text(encoding='utf-8')), {'custom': {'keep': 7}})

    def test_missing_audio_remains_visible(self):
        entry = read_history(LibraryPaths(self.root))[0]
        self.assertEqual(entry['id'], 'old')
        self.assertFalse(entry['available'])

    def test_corrupt_history_is_not_overwritten(self):
        (self.root / 'history.json').write_text('{broken')
        result = inspect_legacy(self.root)
        self.assertTrue(result.errors)
        with self.assertRaises(ValueError):
            adopt_legacy(self.root, Path(self.tmp.name) / 'settings.json')
        self.assertEqual((self.root / 'history.json').read_text(encoding='utf-8'), '{broken')

    def test_unicode_external_paths_are_preserved(self):
        model = Path(self.tmp.name) / 'Modèles externes'
        model.mkdir()
        (model / 'weights.dat').write_bytes(b'unchanged-model')
        (self.root / 'config.json').write_text(json.dumps({'qwen_model_path': str(model)}))
        adopt_legacy(self.root, Path(self.tmp.name) / 'settings.json')
        self.assertEqual(json.loads((self.root / 'config.json').read_text(encoding='utf-8'))['qwen_model_path'], str(model))
        self.assertEqual((model / 'weights.dat').read_bytes(), b'unchanged-model')
        self.assertFalse((self.root / 'models').exists())

    def test_history_traversal_is_unavailable(self):
        outside = self.root.parent / 'outside.wav'
        outside.write_bytes(b'private')
        (self.root / 'history.json').write_text(json.dumps([{'filename': '../../outside.wav'}]))
        self.assertFalse(read_history(LibraryPaths(self.root))[0]['available'])


if __name__ == '__main__':
    unittest.main()
