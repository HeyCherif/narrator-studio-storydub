from pathlib import Path
import tempfile
import unittest
from scripts.verify_distribution import verify

class DistributionTests(unittest.TestCase):
    def test_personal_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'config.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                verify(root)

    def test_missing_bridge_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'NarratorStudio.exe').write_bytes(b'MZtest')
            with self.assertRaisesRegex(ValueError, 'narrator-bridge'):
                verify(root)
