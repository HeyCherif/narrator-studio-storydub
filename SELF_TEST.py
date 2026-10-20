from __future__ import annotations

import ast
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
errors: list[str] = []
notes: list[str] = []
warnings: list[str] = []

# Static Python checks. qwen_tts_worker.py is deliberately included: the old
# self-test forgot it, so Qwen could be totally broken while preflight said OK.
for name in ("app.py", "backend/engine.py", "tts_worker.py", "qwen_tts_worker.py", "qc_worker.py", "quality_utils.py"):
    path = ROOT / name
    if not path.is_file():
        errors.append(f"fichier manquant: {name}")
        continue
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{name}: syntaxe invalide: {exc}")

# Qwen backend routes must actually exist in app.py. A qwen_tts_worker.py lying
# next to an OmniVoice-only backend is not an integration, merely decoration.
try:
    app_source = (ROOT / "backend/engine.py").read_text(encoding="utf-8")
    required_markers = (
        'QWEN_WORKER_SCRIPT',
        'class QwenWorker',
        '/api/qwen/status',
        '/api/qwen/clone',
        '/api/qwen/runtime',
        '/api/qwen/model-path',
        '/api/qwen/download-model',
        'def _generate_qwen_thread',
    )
    missing = [x for x in required_markers if x not in app_source]
    if missing:
        errors.append("backend Qwen incomplet: " + ", ".join(missing))
except Exception as exc:
    errors.append(f"lecture app.py impossible: {exc}")

# Frontend must expose the Qwen selector + clone tab and call the Qwen API.
try:
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    for marker in ('value="qwen"', 'data-tab="qwenClone"'):
        if marker not in index:
            errors.append(f"web/index.html: marqueur Qwen manquant: {marker}")
    for marker in ('/api/qwen/status', '/api/qwen/clone', '/api/engine'):
        if marker not in js:
            errors.append(f"web/app.js: route Qwen manquante: {marker}")
except Exception as exc:
    errors.append(f"frontend Qwen illisible: {exc}")

cfg_path = ROOT / "config.json"
cfg = {}
try:
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.is_file() else {}
except Exception as exc:
    warnings.append(f"config.json illisible: {exc}")

# Runtime Qwen: warn rather than block the whole app. The UI has a repair/download
# path; refusing to launch the UI because Qwen is missing would be peak software.
qwen_py = Path(str(cfg.get("qwen_runtime_python") or cfg.get("qwen_download_python") or ""))
if qwen_py.is_file():
    try:
        p = subprocess.run(
            [str(qwen_py), "-c", "import qwen_tts, torch; print('qwen_tts=OK cuda=' + str(torch.cuda.is_available()))"],
            capture_output=True,
            text=True,
            timeout=45,
        )
        out = ((p.stdout or "") + " " + (p.stderr or "")).strip().replace("\n", " | ")
        if p.returncode == 0:
            notes.append("runtime Qwen import OK: " + (out or str(qwen_py)))
        else:
            warnings.append("runtime Qwen trouvé mais import qwen_tts échoue: " + out[-1000:])
    except Exception as exc:
        warnings.append(f"test runtime Qwen impossible: {exc}")
else:
    warnings.append("runtime Qwen non trouvé dans config; utilise 'Cloner Qwen > Re-détecter runtime + modèle'.")

# Native HF snapshot check. GGUF/Q8 is intentionally not accepted by qwen_tts Python.
def native_model(path: Path) -> bool:
    if not path.is_dir() or not (path / "config.json").is_file():
        return False
    try:
        has_native = any(path.glob("*.safetensors")) or any(path.glob("*.bin")) or any(path.glob("*.safetensors.index.json"))
        has_gguf = any(path.glob("*.gguf"))
        return bool(has_native and not (has_gguf and not has_native))
    except OSError:
        return False

candidates = []
raw_model = str(cfg.get("qwen_model_path") or "").strip()
if raw_model:
    candidates.append(Path(raw_model))
candidates.extend([
    ROOT / "models" / "Qwen3-TTS-12Hz-0.6B-Base",
    ROOT / "models" / "Qwen3-TTS-0.6B-Base",
])
model = next((p for p in candidates if native_model(p)), None)
if model:
    notes.append(f"snapshot Qwen natif détecté: {model}")
elif raw_model and "q8" in raw_model.lower():
    warnings.append("qwen_model_path pointe vers un pack Q8/GGUF. Le worker qwen_tts Python exige le snapshot natif Qwen3-TTS-12Hz-0.6B-Base.")
else:
    warnings.append("snapshot Qwen Base natif non détecté; l'app pourra le télécharger depuis l'onglet Cloner Qwen.")

# Keep the useful QC regression tests from the current build.
try:
    sys.path.insert(0, str(ROOT))
    from quality_utils import split_text_aggressive, split_text_smart, text_similarity

    sample = "Two hundred years ago, three emperors feared one martial artist. Then everything changed."
    chunks = split_text_smart(sample, max_chars=140, max_words=30)
    rescue = split_text_aggressive(sample, max_chars=82, max_words=18)
    if any(len(x.split()) <= 2 for x in rescue):
        errors.append(f"rescue splitter crée encore un micro-chunk: {rescue}")
    same = text_similarity("Two hundred years ago", "200 years ago")["score"]
    if same < 0.90:
        errors.append(f"normalisation nombres QC insuffisante: {same}")
    notes.append(f"QC regression OK: {len(chunks)} chunk(s), rescue={rescue}, 200/two-hundred={same:.2f}")
except Exception as exc:
    errors.append("tests quality_utils: " + repr(exc))

if errors:
    print("SELF TEST FAILED")
    for e in errors:
        print(" -", e)
    if warnings:
        print("WARNINGS")
        for w in warnings:
            print(" -", w)
    raise SystemExit(1)

print("SELF TEST OK")
print(" - backend Qwen restauré")
print(" - frontend Qwen restauré")
for n in notes:
    print(" -", n)
if warnings:
    print("WARNINGS (l'app reste lançable)")
    for w in warnings:
        print(" -", w)
