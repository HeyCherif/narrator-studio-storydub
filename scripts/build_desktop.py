"""Explicit Windows build; all output comes from a fixed allowlist."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
VERSION='2.0.0-beta.1'
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--version',default=VERSION)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.version!=VERSION:parser.error('Version must match the source package')
    for command in [['npm.cmd','ci','--prefix','desktop'],['npm.cmd','test','--prefix','desktop'],
                    ['npm.cmd','run','build','--prefix','desktop'],[sys.executable,'scripts/build_bridge.py'],[sys.executable,'scripts/collect_notices.py'],
                    [str(ROOT/'desktop/node_modules/.bin/tauri.cmd'),'build','--features','desktop','--bundles','nsis']]:
        subprocess.run(command,cwd=ROOT,check=True)
    args.output.mkdir(parents=True,exist_ok=True)
    for name in ['NarratorStudio.exe','narrator-bridge.exe']:
        shutil.copy2(ROOT/'src-tauri/target/release'/name,args.output/name)
    for installer in (ROOT/'src-tauri/target/release/bundle/nsis').glob('*.exe'):
        shutil.copy2(installer,args.output/installer.name)
    shutil.copy2(ROOT/'src-tauri/resources/THIRD_PARTY_NOTICES.txt',args.output/'THIRD_PARTY_NOTICES.txt')
    subprocess.run([sys.executable,'scripts/verify_distribution.py',str(args.output.resolve())],cwd=ROOT,check=True)
