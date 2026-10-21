"""Collect dependency license texts from installed source metadata, never a user library."""
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
def main():
    sections=['Narrator Studio — third-party notices\nModels, voice data and external AI environments are not included in this distribution.\n']
    metadata=json.loads(subprocess.check_output(['cargo','metadata','--locked','--format-version','1','--filter-platform','x86_64-pc-windows-msvc','--features','desktop','--manifest-path',str(ROOT/'src-tauri/Cargo.toml')],cwd=ROOT,text=True,encoding='utf-8'))
    for package in metadata['packages']:
        if package.get('source') is None:continue
        folder=Path(package['manifest_path']).parent
        texts=[]
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.name.lower().startswith(('license','copying','notice')):
                texts.append(path.read_text(encoding='utf-8',errors='replace'))
        sections.append(f"\n=== {package['name']} {package['version']} · {package.get('license')} ===\n"+'\n'.join(texts))
    for name in ['@tabler/core','@tabler/icons-webfont','@tauri-apps/api']:
        folder=ROOT/'desktop/node_modules'/name
        package=json.loads((folder/'package.json').read_text(encoding='utf-8'))
        texts=[p.read_text(encoding='utf-8',errors='replace') for p in folder.iterdir() if p.is_file() and p.name.lower().startswith(('license','copying','notice'))]
        if name=='@tabler/core' and not texts:
            with urlopen('https://raw.githubusercontent.com/tabler/tabler/dev/LICENSE',timeout=30) as response:texts=[response.read().decode('utf-8')]
        sections.append(f"\n=== {name} {package['version']} · {package.get('license')} ===\n"+'\n'.join(texts))
    for name in ['pyinstaller']:
        dist=importlib.metadata.distribution(name)
        texts=[Path(dist.locate_file(p)).read_text(encoding='utf-8',errors='replace') for p in dist.files or [] if Path(p).name.lower().startswith(('copying','license')) and Path(dist.locate_file(p)).is_file()]
        sections.append(f'\n=== {name} {dist.version} ===\n'+'\n'.join(texts))
    license_file=Path(sys.base_prefix)/'LICENSE.txt'
    if license_file.exists():sections.append('\n=== Python ===\n'+license_file.read_text(encoding='utf-8',errors='replace'))
    target=ROOT/'src-tauri/resources/THIRD_PARTY_NOTICES.txt'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('\n'.join(sections),encoding='utf-8')
    print(f'Dependency notices collected: {len(sections)-1} components')
if __name__=='__main__':main()
