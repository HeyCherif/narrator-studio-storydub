import os
from pathlib import Path
import unittest
from unittest.mock import patch
from backend.engine import external_worker_popen

@unittest.skipUnless(os.name == 'nt', 'Windows DLL isolation contract')
class FrozenWorkerTests(unittest.TestCase):
    def test_cancelling_worker_also_stops_its_owned_child(self):
        import subprocess, sys, ctypes
        from backend.engine import OmniWorker
        code='import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);print(p.pid,flush=True);time.sleep(30)'
        process=subprocess.Popen([sys.executable,'-u','-c',code],stdout=subprocess.PIPE,text=True)
        child=int(process.stdout.readline())
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x100000,False,child)
        self.assertTrue(handle)
        try:
            worker=OmniWorker({});worker.proc=process;worker.kill()
            self.assertEqual(kernel.WaitForSingleObject(handle,3000),0)
        finally:
            subprocess.run(['taskkill','/PID',str(child),'/T','/F'],capture_output=True)
            if process.poll() is None:process.kill()
            process.wait(timeout=5)
            process.stdout.close()
            kernel.CloseHandle(handle)

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
