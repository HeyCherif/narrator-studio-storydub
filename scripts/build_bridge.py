"""Package only the stdlib bridge and explicit worker sources; never user data."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    out = ROOT / 'src-tauri/binaries'
    out.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
            '--name', 'narrator-bridge-x86_64-pc-windows-msvc', '--distpath', str(out),
            '--workpath', str(ROOT / '.superpowers/pyinstaller'),
            '--specpath', str(ROOT / '.superpowers'), '--paths', str(ROOT),
            '--hidden-import', 'quality_utils', '--hidden-import', 'backend.engine']
    for source, destination in [('backend/engine.py', 'backend'), ('tts_worker.py', '.'),
                                ('qwen_tts_worker.py', '.'), ('qc_worker.py', '.'),
                                ('quality_utils.py', '.')]:
        args += ['--add-data', f'{ROOT / source};{destination}']
    subprocess.run(args + [str(ROOT / 'scripts/bridge_entry.py')], cwd=ROOT, check=True)
