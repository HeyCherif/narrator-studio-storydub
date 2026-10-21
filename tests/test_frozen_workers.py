import os
from pathlib import Path
import unittest
from unittest.mock import patch
from backend.engine import external_worker_popen

@unittest.skipUnless(os.name == 'nt', 'Windows DLL isolation contract')
class FrozenWorkerTests(unittest.TestCase):
    def test_external_worker_does_not_inherit_frozen_dll_search(self):
        calls=[]
        with patch('backend.engine.sys.frozen',True,create=True), patch('backend.engine.sys._MEIPASS',str(Path.cwd()),create=True), patch('backend.engine._set_dll_directory',side_effect=calls.append), patch('backend.engine.subprocess.Popen',return_value='process') as popen:
            self.assertEqual(external_worker_popen(['python','worker.py']),'process')
            self.assertEqual(calls,[None,str(Path.cwd())])
            popen.assert_called_once()

    def test_search_path_is_restored_if_spawn_fails(self):
        calls=[]
        with patch('backend.engine.sys.frozen',True,create=True), patch('backend.engine.sys._MEIPASS','bundle',create=True), patch('backend.engine._set_dll_directory',side_effect=calls.append), patch('backend.engine.subprocess.Popen',side_effect=OSError('cannot start')):
            with self.assertRaises(OSError):external_worker_popen(['missing'])
            self.assertEqual(calls,[None,'bundle'])
