import tempfile
from pathlib import Path
import unittest
from backend.library import LibraryLock

class LibraryLockTests(unittest.TestCase):
    def test_second_writer_is_rejected_and_close_releases(self):
        with tempfile.TemporaryDirectory() as root:
            first = LibraryLock(Path(root))
            with self.assertRaisesRegex(RuntimeError, 'library-in-use'):
                LibraryLock(Path(root))
            first.close()
            second = LibraryLock(Path(root))
            second.close()
