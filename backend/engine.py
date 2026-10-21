from __future__ import annotations

import json
import os
import base64
import binascii
import sys
import importlib
import shutil
import socket
import random
import wave
import subprocess
import threading
import time
import uuid
from array import array
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


from quality_utils import (
    clean_text,
    qc_soft_floor,
    qc_threshold,
    split_text_aggressive,
    split_text_smart,
    speech_safe_variant,
    text_similarity,
    wav_sanity,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
HISTORY_DIR = ROOT / "history"
HISTORY_DB = ROOT / "history.json"
WEB_DIR = ROOT / "web"
WORKER_SCRIPT = ROOT / "tts_worker.py"
QWEN_WORKER_SCRIPT = ROOT / "qwen_tts_worker.py"
QC_WORKER_SCRIPT = ROOT / "qc_worker.py"
QWEN_VOICES_DIR = ROOT / "qwen_voices"
QWEN_MODEL_REPO = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
QWEN_DEFAULT_MODEL_DIR = ROOT / "models" / "Qwen3-TTS-12Hz-0.6B-Base"
WORK_DIR = HISTORY_DIR / ".work"



def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def hidden_popen_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": si, "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}


# The two StoryDub narrator profiles validated by the Story Recapper TTS patches.
# We still verify them on disk at runtime; these IDs are identities, not guessed paths.
STORYDUB_NARRATORS = (
    ("voice_ee40c6612ca1235e0c7a", "Male EN Narrator 1"),
    ("voice_73c9c20e2de552c1815d", "Male EN Narrator 2"),
)


def _existing_dir(value: Any) -> Path | None:
    try:
        p = Path(str(value or "")).expanduser().resolve()
    except Exception:
        return None
    return p if p.is_dir() else None


def _latest_storyrecap_project(story_root: Path) -> Path:
    projects = story_root / "projects"
    if not projects.is_dir():
        return story_root
    rows: list[Path] = []
    try:
        for p in projects.iterdir():
            if p.is_dir() and ((p / "project.json").is_file() or (p / "tts").is_dir()):
                rows.append(p)
    except OSError:
        return story_root
    if not rows:
        return story_root
    rows.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return rows[0]


def _storyrecap_roots(config: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    for raw in (
        os.environ.get("STORY_RECAP_ROOT"),
        config.get("storyrecap_root"),
        Path(str(config.get("storydub_root") or "")) / "StoryRecapper_Pipeline_Current"
        if config.get("storydub_root") else None,
        r"D:\manhwa studio\StoryDub\StoryRecapper_Pipeline_Current",
    ):
        if not raw:
            continue
        try:
            p = Path(raw).expanduser().resolve()
        except Exception:
            continue
        if p not in candidates:
            candidates.append(p)
    return candidates


def detect_from_storyrecapper(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reuse the detection path already used by Story Recapper patches.

    Preferred source of truth:
      simple_ui/script_studio_023.py::tts_capabilities(project)
      simple_ui/script_studio_023.py::_dubroom_root()

    Only if that module cannot be loaded do we fall back to the same validated
    DubRoom file layout. Nothing is downloaded and no model path is invented.
    """
    resolved = dict(config)
    diag: dict[str, Any] = {
        "source": "",
        "storyrecap_root": "",
        "project_probe": "",
        "runner": "",
        "model_root": "",
        "messages": [],
    }

    story_root: Path | None = None
    for candidate in _storyrecap_roots(config):
        if (candidate / "simple_ui" / "script_studio_023.py").is_file():
            story_root = candidate
            break
    if story_root:
        diag["storyrecap_root"] = str(story_root)
        simple_ui = story_root / "simple_ui"
        project_probe = _latest_storyrecap_project(story_root)
        diag["project_probe"] = str(project_probe)
        try:
            simple_text = str(simple_ui)
            if simple_text not in sys.path:
                sys.path.insert(0, simple_text)
            module = importlib.import_module("script_studio_023")
            caps = module.tts_capabilities(project_probe) if hasattr(module, "tts_capabilities") else {}
            if isinstance(caps, dict):
                py = str(caps.get("python") or "").strip()
                runner = str(caps.get("runner") or "").strip()
                model_root = str(caps.get("model_root") or "").strip()
                if py:
                    resolved["runtime_python"] = py
                if runner:
                    diag["runner"] = runner
                if model_root:
                    diag["model_root"] = model_root
                    mr = Path(model_root)
                    model_dir = mr / "model"
                    resolved["model_path"] = str(model_dir if model_dir.is_dir() else mr)
                diag["caps_ready"] = bool(caps.get("ready"))
                diag["caps_missing"] = list(caps.get("missing") or [])
            if hasattr(module, "_dubroom_root"):
                dubroom = Path(module._dubroom_root()).resolve()
                resolved["dubroom_root"] = str(dubroom)
                if not str(resolved.get("runtime_python") or ""):
                    runtime_candidates = (
                        dubroom / "data" / "environments" / "tts-omnivoice-hq-torch28-v53" / "venv" / "Scripts" / "python.exe",
                        dubroom / "data" / "environments" / "tts-omnivoice-hq" / "venv" / "Scripts" / "python.exe",
                    )
                    resolved["runtime_python"] = str(next((p for p in runtime_candidates if p.is_file()), runtime_candidates[0]))
                if not diag["runner"]:
                    diag["runner"] = str(dubroom / "scripts" / "engines" / "run-tts.py")
                if not diag["model_root"]:
                    model_root = dubroom / "models" / "tts-omnivoice-hq"
                    diag["model_root"] = str(model_root)
                    resolved["model_path"] = str(model_root / "model")
            diag["source"] = "StoryRecapper · script_studio_023.tts_capabilities"
        except Exception as exc:
            diag["messages"].append(f"script_studio_023: {exc}")

    # Fallback uses the exact DubRoom layout already exercised by run-tts.py.
    if not diag["source"]:
        dubroom_candidates: list[Path] = []
        for raw in (
            resolved.get("dubroom_root"),
            os.environ.get("DUBROOM_ROOT"),
            r"D:\manhwa studio\anime_manga_manhua_dubbing_app",
        ):
            if not raw:
                continue
            try:
                p = Path(str(raw)).expanduser().resolve()
            except Exception:
                continue
            if p not in dubroom_candidates:
                dubroom_candidates.append(p)
        for dubroom in dubroom_candidates:
            runner = dubroom / "scripts" / "engines" / "run-tts.py"
            runtime_candidates = (
                dubroom / "data" / "environments" / "tts-omnivoice-hq-torch28-v53" / "venv" / "Scripts" / "python.exe",
                dubroom / "data" / "environments" / "tts-omnivoice-hq" / "venv" / "Scripts" / "python.exe",
            )
            python = next((p for p in runtime_candidates if p.is_file()), runtime_candidates[0])
            model_roots = [
                dubroom / "data" / "models" / "tts-omnivoice-hq",
                dubroom / "models" / "tts-omnivoice-hq",
            ]
            model_root = next((m for m in model_roots if (m / "model").is_dir()), None)
            if runner.is_file() and model_root is not None and python.is_file():
                resolved["dubroom_root"] = str(dubroom)
                resolved["runtime_python"] = str(python)
                resolved["model_path"] = str(model_root / "model")
                diag["runner"] = str(runner)
                diag["model_root"] = str(model_root)
                diag["source"] = "StoryRecapper fallback · validated DubRoom layout"
                break

    # Reuse the Faster-Whisper Turbo runtime/model already validated by Story Recapper.
    dubroom_for_qc = _existing_dir(resolved.get("dubroom_root"))
    if dubroom_for_qc:
        qc_python = dubroom_for_qc / "data" / "environments" / "faster-whisper-turbo" / "venv" / "Scripts" / "python.exe"
        qc_models = [
            dubroom_for_qc / "models" / "faster-whisper-turbo" / "snapshot",
            dubroom_for_qc / "data" / "models" / "faster-whisper-turbo" / "snapshot",
        ]
        qc_model = next((x for x in qc_models if x.is_dir()), None)
        if qc_python.is_file():
            resolved["qc_runtime_python"] = str(qc_python)
        if qc_model is not None:
            resolved["qc_model_path"] = str(qc_model)
        diag["qc_runtime_python"] = str(qc_python)
        diag["qc_model_path"] = str(qc_model or qc_models[0])
        diag["qc_ready"] = bool(qc_python.is_file() and qc_model is not None)

    # Narrator discovery reuses the exact StoryDub profile store used in the patch
    # requests: StoryDub/data/narrator_voices/<voice_id>/{reference.wav,omnivoice_prompt.pt}.
    storydub_candidates: list[Path] = []
    for raw in (
        resolved.get("storydub_root"),
        story_root.parent if story_root else None,
        r"D:\manhwa studio\StoryDub",
    ):
        if not raw:
            continue
        try:
            p = Path(str(raw)).expanduser().resolve()
        except Exception:
            continue
        if p not in storydub_candidates:
            storydub_candidates.append(p)

    detected_voices: list[dict[str, Any]] = []
    for storydub in storydub_candidates:
        voice_root = storydub / "data" / "narrator_voices"
        rows: list[dict[str, Any]] = []
        for voice_id, name in STORYDUB_NARRATORS:
            folder = voice_root / voice_id
            prompt = folder / "omnivoice_prompt.pt"
            reference = folder / "reference.wav"
            rows.append({
                "id": voice_id,
                "name": name,
                "prompt_path": str(prompt),
                "reference_path": str(reference),
                "profile_dir": str(folder),
            })
        if any(Path(r["prompt_path"]).is_file() for r in rows):
            detected_voices = rows
            resolved["storydub_root"] = str(storydub)
            break

    if detected_voices:
        resolved["voices"] = detected_voices
        diag["voices_source"] = "StoryDub/data/narrator_voices · PATCH045/PATCH062 profiles"
    else:
        diag["voices_source"] = "config fallback"

    defaults = dict(resolved.get("defaults") or {})
    if not any(v.get("id") == defaults.get("voice_id") for v in resolved.get("voices") or []):
        defaults["voice_id"] = STORYDUB_NARRATORS[0][0]
    resolved["defaults"] = defaults
    return resolved, diag



def _is_native_qwen_model(path: Path | str | None) -> bool:
    try:
        p = Path(str(path or "")).expanduser().resolve()
    except Exception:
        return False
    if not p.is_dir() or not (p / "config.json").is_file():
        return False
    # qwen_tts.from_pretrained needs a native Hugging Face snapshot, not a GGUF-only Q8 pack.
    if any(p.glob("*.gguf")) and not (list(p.glob("*.safetensors")) or list(p.glob("*.bin"))):
        return False
    return bool(
        list(p.glob("*.safetensors"))
        or list(p.glob("*.bin"))
        or (p / "model.safetensors.index.json").is_file()
        or (p / "pytorch_model.bin.index.json").is_file()
    )


def _qwen_q8_candidate(config: dict[str, Any]) -> Path | None:
    rows: list[Path] = []
    raw = config.get("qwen_model_path")
    if raw:
        try:
            rows.append(Path(str(raw)).expanduser().resolve())
        except Exception:
            pass
    models = ROOT / "models"
    if models.is_dir():
        try:
            rows.extend(p for p in models.iterdir() if p.is_dir() and ("q8" in p.name.lower() or any(p.glob("*.gguf"))))
        except OSError:
            pass
    for p in rows:
        if p.is_dir() and ("q8" in p.name.lower() or any(p.glob("*.gguf"))):
            return p
    return None


def _detect_qwen_model(config: dict[str, Any]) -> Path | None:
    candidates: list[Path] = []
    for raw in (
        config.get("qwen_model_path"),
        QWEN_DEFAULT_MODEL_DIR,
        ROOT / "models" / "Qwen3-TTS-0.6B-Base",
        Path(str(config.get("dubroom_root") or "")) / "models" / "Qwen3-TTS-12Hz-0.6B-Base"
        if config.get("dubroom_root") else None,
        Path(str(config.get("dubroom_root") or "")) / "data" / "models" / "Qwen3-TTS-12Hz-0.6B-Base"
        if config.get("dubroom_root") else None,
    ):
        if not raw:
            continue
        try:
            p = Path(raw).expanduser().resolve()
        except Exception:
            continue
        if p not in candidates:
            candidates.append(p)
    models = ROOT / "models"
    if models.is_dir():
        try:
            for p in models.iterdir():
                if p.is_dir() and "qwen3-tts" in p.name.lower() and p not in candidates:
                    candidates.append(p)
        except OSError:
            pass
    return next((p for p in candidates if _is_native_qwen_model(p)), None)


def _detect_qwen_runtime(config: dict[str, Any]) -> Path | None:
    candidates: list[Path] = []
    for raw in (
        config.get("qwen_runtime_python"),
        config.get("qwen_download_python"),
        Path(str(config.get("dubroom_root") or ""))
        / "data" / "environments" / "tts-qwen3-0.6b-base" / "venv" / "Scripts" / "python.exe"
        if config.get("dubroom_root") else None,
        r"D:\manhwa studio\anime_manga_manhua_dubbing_app\data\environments\tts-qwen3-0.6b-base\venv\Scripts\python.exe",
    ):
        if not raw:
            continue
        try:
            p = Path(raw).expanduser().resolve()
        except Exception:
            continue
        if p not in candidates:
            candidates.append(p)
    return next((p for p in candidates if p.is_file()), None)


def _history_voice_names() -> dict[str, str]:
    rows = read_json(HISTORY_DB, [])
    out: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            if str(row.get("engine") or "") != "qwen":
                continue
            vid = str(row.get("voice_id") or "").strip()
            name = str(row.get("voice_name") or "").strip()
            if vid and name and vid not in out:
                out[vid] = name
    return out


def _scan_qwen_voices() -> list[dict[str, Any]]:
    known_names = _history_voice_names()
    voices: list[dict[str, Any]] = []
    try:
        folders = sorted((p for p in QWEN_VOICES_DIR.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
    except OSError:
        folders = []
    for folder in folders:
        meta: dict[str, Any] = {}
        for meta_name in ("voice.json", "profile.json", "metadata.json", "config.json"):
            mp = folder / meta_name
            if mp.is_file():
                value = read_json(mp, {})
                if isinstance(value, dict):
                    meta = value
                    break
        pts = list(folder.glob("*.pt"))
        preferred = [
            folder / "qwen_prompt.pt",
            folder / "qwen_icl_prompt.pt",
            folder / "icl_prompt.pt",
            folder / "prompt.pt",
        ]
        prompt = next((p for p in preferred if p.is_file()), None)
        if prompt is None:
            prompt = next((p for p in pts if "xvec" not in p.name.lower() and "xvector" not in p.name.lower()), None)
        if prompt is None:
            continue
        xvec = next((p for p in pts if "xvec" in p.name.lower() or "xvector" in p.name.lower()), None)
        voice_id = str(meta.get("id") or meta.get("voice_id") or folder.name).strip()
        if not voice_id:
            voice_id = folder.name
        name = str(meta.get("name") or known_names.get(voice_id) or voice_id).strip()
        voices.append({
            "id": voice_id,
            "name": name,
            "engine": "qwen",
            "prompt_path": str(prompt.resolve()),
            "xvec_prompt_path": str(xvec.resolve()) if xvec else "",
            "reference_path": str(meta.get("reference_path") or ""),
            "language": str(meta.get("language") or "en"),
            "ref_text": str(meta.get("ref_text") or meta.get("transcript") or ""),
        })

    # Compatibility with a flat qwen_voices directory.
    if not voices:
        try:
            pts = [p for p in QWEN_VOICES_DIR.glob("*.pt") if "xvec" not in p.name.lower() and "xvector" not in p.name.lower()]
        except OSError:
            pts = []
        for p in pts:
            vid = p.stem
            voices.append({
                "id": vid,
                "name": known_names.get(vid, vid),
                "engine": "qwen",
                "prompt_path": str(p.resolve()),
                "xvec_prompt_path": "",
                "reference_path": "",
                "language": "en",
                "ref_text": "",
            })
    return voices


class AppHandler(SimpleHTTPRequestHandler):
    """Static UI + tiny localhost JSON API.

    The browser UI talks to Python over ordinary HTTP on 127.0.0.1. This is
    deliberately independent from ``window.pywebview.api``: PyWebView is only
    the desktop shell, so changes in its JS bridge cannot break the application.
    """

    server_version = "NarratorStudio/1.9-qwen-restored"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    @property
    def app_api(self):
        api = getattr(self.server, "app_api", None)
        if api is None:
            raise RuntimeError("API locale pas encore initialisée")
        return api

    def _json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _body_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(max(0, min(length, 48_000_000))) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {}
        return data if isinstance(data, dict) else {}

    def _audio_file(self, *, attachment: bool) -> None:
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(self.path).query)
        name = Path(str((query.get("filename") or [""])[0])).name
        path = HISTORY_DIR / name
        if not name or path.suffix.lower() != ".wav" or not path.is_file():
            self._json({"ok": False, "error": "Audio introuvable."}, 404)
            return
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        with path.open("rb") as fh:
            shutil.copyfileobj(fh, self.wfile, length=1024 * 256)

    def do_GET(self) -> None:
        from urllib.parse import urlsplit
        route = urlsplit(self.path).path
        try:
            if route == "/api/bootstrap":
                return self._json(self.app_api.get_bootstrap())
            if route == "/api/job":
                return self._json(self.app_api.get_job())
            if route == "/api/history":
                return self._json(self.app_api.get_history())
            if route == "/api/qwen/status":
                return self._json(self.app_api.qwen_status())
            if route == "/api/audio":
                return self._audio_file(attachment=False)
            if route == "/api/download":
                return self._audio_file(attachment=True)
            return super().do_GET()
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self) -> None:
        from urllib.parse import urlsplit
        route = urlsplit(self.path).path
        body = self._body_json()
        try:
            if route == "/api/generate":
                return self._json(self.app_api.start_generate(body))
            if route == "/api/engine":
                return self._json(self.app_api.set_engine(str(body.get("engine") or "")))
            if route == "/api/qwen/rescan-runtime":
                return self._json(self.app_api.qwen_rescan())
            if route == "/api/qwen/runtime":
                return self._json(self.app_api.qwen_set_runtime(str(body.get("python_path") or "")))
            if route == "/api/qwen/model-path":
                return self._json(self.app_api.qwen_set_model_path(str(body.get("model_path") or "")))
            if route == "/api/qwen/download-model":
                return self._json(self.app_api.qwen_download_model())
            if route == "/api/qwen/clone":
                return self._json(self.app_api.qwen_clone(body))
            if route == "/api/cancel":
                return self._json(self.app_api.cancel_generate())
            if route == "/api/delete":
                return self._json(self.app_api.delete_history(str(body.get("filename") or "")))
            if route == "/api/save":
                return self._json(self.app_api.save_audio(str(body.get("filename") or "")))
            if route == "/api/open-folder":
                return self._json(self.app_api.open_history_folder())
            return self._json({"ok": False, "error": "Route API inconnue."}, 404)
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)}, 500)


class LocalServer:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        self.server.app_api = None
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="NarratorStudio-HTTP")

    def bind_api(self, api) -> None:
        self.server.app_api = api

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class OmniWorker:
    def __init__(self, config: dict[str, Any], on_event=None):
        self.config = config
        self.on_event = on_event
        self.proc: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self.reader_lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            python = Path(str(self.config.get("runtime_python") or ""))
            if not python.is_file():
                raise FileNotFoundError(f"OmniVoice Python introuvable: {python}")
            if not WORKER_SCRIPT.is_file():
                raise FileNotFoundError(f"Worker introuvable: {WORKER_SCRIPT}")
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
            self.proc = subprocess.Popen(
                [str(python), "-u", str(WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(ROOT),
                env=env,
                **hidden_popen_kwargs(),
            )

    def stop(self):
        with self.lock:
            p = self.proc
            self.proc = None
        if not p:
            return
        try:
            if p.poll() is None and p.stdin:
                rid = uuid.uuid4().hex
                p.stdin.write(json.dumps({"cmd": "shutdown", "request_id": rid}) + "\n")
                p.stdin.flush()
                p.wait(timeout=2)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass

    def kill(self):
        with self.lock:
            p = self.proc
            self.proc = None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.reader_lock:
            self.start()
            p = self.proc
            if not p or not p.stdin or not p.stdout:
                raise RuntimeError("Le worker OmniVoice n'a pas démarré")
            rid = str(payload.get("request_id") or uuid.uuid4().hex)
            payload["request_id"] = rid
            p.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            p.stdin.flush()

            while True:
                line = p.stdout.readline()
                if not line:
                    code = p.poll()
                    raise RuntimeError(f"OmniVoice worker arrêté (code {code})")
                line = line.strip()
                try:
                    ev = json.loads(line)
                except Exception:
                    if self.on_event:
                        self.on_event({"event": "log", "message": line[-1000:]})
                    continue
                if self.on_event:
                    self.on_event(ev)
                if str(ev.get("request_id") or "") != rid:
                    continue
                if ev.get("event") in {"completed", "ready", "error", "shutdown"}:
                    if ev.get("event") == "error" or ev.get("ok") is False:
                        raise RuntimeError(str(ev.get("error") or "Erreur OmniVoice"))
                    return ev



class QwenWorker:
    def __init__(self, config: dict[str, Any], on_event=None):
        self.config = config
        self.on_event = on_event
        self.proc: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self.reader_lock = threading.Lock()

    def available(self) -> bool:
        python = _detect_qwen_runtime(self.config)
        model = _detect_qwen_model(self.config)
        return bool(python and model and QWEN_WORKER_SCRIPT.is_file())

    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            python = _detect_qwen_runtime(self.config)
            if not python:
                raise FileNotFoundError("Runtime Qwen introuvable. Utilise Re-détecter runtime + modèle.")
            model = _detect_qwen_model(self.config)
            if not model:
                raise FileNotFoundError("Modèle Qwen Base natif introuvable. Le pack Q8/GGUF ne suffit pas au worker Python.")
            self.config["qwen_runtime_python"] = str(python)
            self.config["qwen_model_path"] = str(model)
            if not QWEN_WORKER_SCRIPT.is_file():
                raise FileNotFoundError(f"Worker Qwen introuvable: {QWEN_WORKER_SCRIPT}")
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
            self.proc = subprocess.Popen(
                [str(python), "-u", str(QWEN_WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(ROOT),
                env=env,
                **hidden_popen_kwargs(),
            )

    def stop(self):
        with self.lock:
            p = self.proc
            self.proc = None
        if not p:
            return
        try:
            if p.poll() is None and p.stdin:
                rid = uuid.uuid4().hex
                p.stdin.write(json.dumps({"cmd": "shutdown", "request_id": rid}) + "\n")
                p.stdin.flush()
                p.wait(timeout=3)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass

    def kill(self):
        with self.lock:
            p = self.proc
            self.proc = None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.reader_lock:
            self.start()
            p = self.proc
            if not p or not p.stdin or not p.stdout:
                raise RuntimeError("Le worker Qwen n'a pas démarré")
            rid = str(payload.get("request_id") or uuid.uuid4().hex)
            payload["request_id"] = rid
            p.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            p.stdin.flush()
            while True:
                line = p.stdout.readline()
                if not line:
                    code = p.poll()
                    raise RuntimeError(f"Qwen worker arrêté (code {code})")
                line = line.strip()
                try:
                    ev = json.loads(line)
                except Exception:
                    if self.on_event:
                        self.on_event({"event": "qwen_log", "message": line[-1500:]})
                    continue
                if self.on_event:
                    self.on_event(ev)
                if str(ev.get("request_id") or "") != rid:
                    continue
                if ev.get("event") in {"completed", "ready", "prompt_created", "error", "shutdown"}:
                    if ev.get("event") == "error" or ev.get("ok") is False:
                        raise RuntimeError(str(ev.get("error") or "Erreur Qwen3-TTS"))
                    return ev


class QCWorker:
    def __init__(self, config: dict[str, Any], on_event=None):
        self.config = config
        self.on_event = on_event
        self.proc: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self.reader_lock = threading.Lock()

    def available(self) -> bool:
        return (
            Path(str(self.config.get("qc_runtime_python") or "")).is_file()
            and Path(str(self.config.get("qc_model_path") or "")).is_dir()
            and QC_WORKER_SCRIPT.is_file()
        )

    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            python = Path(str(self.config.get("qc_runtime_python") or ""))
            if not python.is_file():
                raise FileNotFoundError(f"Faster-Whisper Python introuvable: {python}")
            if not QC_WORKER_SCRIPT.is_file():
                raise FileNotFoundError(f"Worker QC introuvable: {QC_WORKER_SCRIPT}")
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
            self.proc = subprocess.Popen(
                [str(python), "-u", str(QC_WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(ROOT),
                env=env,
                **hidden_popen_kwargs(),
            )

    def stop(self):
        with self.lock:
            p = self.proc
            self.proc = None
        if not p:
            return
        try:
            if p.poll() is None and p.stdin:
                rid = uuid.uuid4().hex
                p.stdin.write(json.dumps({"cmd": "shutdown", "request_id": rid}) + "\n")
                p.stdin.flush()
                p.wait(timeout=3)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass

    def kill(self):
        with self.lock:
            p = self.proc
            self.proc = None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.reader_lock:
            self.start()
            p = self.proc
            if not p or not p.stdin or not p.stdout:
                raise RuntimeError("Le worker Faster-Whisper QC n'a pas démarré")
            rid = str(payload.get("request_id") or uuid.uuid4().hex)
            payload["request_id"] = rid
            p.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            p.stdin.flush()
            while True:
                line = p.stdout.readline()
                if not line:
                    code = p.poll()
                    raise RuntimeError(f"Faster-Whisper QC arrêté (code {code})")
                line = line.strip()
                try:
                    ev = json.loads(line)
                except Exception:
                    if self.on_event:
                        self.on_event({"event": "qc_log", "message": line[-1000:]})
                    continue
                if self.on_event:
                    self.on_event(ev)
                if str(ev.get("request_id") or "") != rid:
                    continue
                if ev.get("event") in {"transcribed", "ready", "error", "shutdown"}:
                    if ev.get("event") == "error" or ev.get("ok") is False:
                        raise RuntimeError(str(ev.get("error") or "Erreur Faster-Whisper QC"))
                    return ev


class AppAPI:
    def __init__(self, server: LocalServer | None, *, warmup: bool = True):
        self.server = server
        self.lazy = not warmup
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        QWEN_VOICES_DIR.mkdir(parents=True, exist_ok=True)
        raw_config = read_json(CONFIG_PATH, {})
        self.config, self.detection = detect_from_storyrecapper(raw_config)

        qwen_runtime = _detect_qwen_runtime(self.config)
        qwen_model = _detect_qwen_model(self.config)
        if qwen_runtime:
            self.config["qwen_runtime_python"] = str(qwen_runtime)
            self.config.setdefault("qwen_download_python", str(qwen_runtime))
        if qwen_model:
            self.config["qwen_model_path"] = str(qwen_model)

        defaults = dict(self.config.get("defaults") or {})
        requested_engine = str(defaults.get("engine") or "omnivoice").lower()
        self.active_engine = "qwen" if requested_engine == "qwen" and qwen_runtime and qwen_model else "omnivoice"
        defaults["engine"] = self.active_engine
        self.config["defaults"] = defaults

        self.window = None
        self.job_lock = threading.RLock()
        self.job: dict[str, Any] = {
            "running": False,
            "stage": "Démarrage",
            "progress": 0,
            "error": "",
            "ready": False,
            "qc_ready": False,
            "cancel_requested": False,
            "active_engine": self.active_engine,
        }
        self.worker = OmniWorker(self.config, self._worker_event)
        self.qwen_worker = QwenWorker(self.config, self._worker_event)
        self.qc_worker = QCWorker(self.config, self._worker_event)
        self.qc_disabled_for_job = False
        self.qwen_download: dict[str, Any] = {
            "running": False,
            "progress": 0,
            "stage": "",
            "error": "",
            "bytes_done": 0,
            "total_bytes": 0,
            "speed_bps": 0,
            "eta_seconds": None,
        }
        self._warm_thread = threading.Thread(target=self._warmup, daemon=True)
        if warmup:
            self._warm_thread.start()

    def bind_window(self, window):
        self.window = window

    def _set_job(self, **kwargs):
        with self.job_lock:
            self.job.update(kwargs)

    def _cancelled(self) -> bool:
        with self.job_lock:
            return bool(self.job.get("cancel_requested"))

    def _worker_event(self, ev: dict[str, Any]):
        name = str(ev.get("event") or "")
        if name == "runtime":
            self._set_job(ready=True, active_engine="omnivoice", gpu=str(ev.get("gpu") or self.job.get("gpu") or "CUDA"))
        elif name == "qwen_runtime":
            self._set_job(ready=True, active_engine="qwen", gpu=str(ev.get("gpu") or self.job.get("gpu") or "CUDA"))
        elif name == "qc_runtime":
            self._set_job(
                qc_ready=True,
                qc_device=str(ev.get("device") or ""),
                qc_compute_type=str(ev.get("compute_type") or ""),
            )
        elif name in {"log", "qc_log", "qwen_log"}:
            self._set_job(log=str(ev.get("message") or ""))

    def _warmup(self):
        try:
            if self.active_engine == "qwen":
                self.worker.stop()
                status = self.qwen_status()
                if status.get("ready"):
                    self._set_job(
                        ready=True,
                        stage="Qwen3-TTS 0.6B prêt · chargement au premier audio",
                        progress=0,
                        error="",
                        active_engine="qwen",
                        qc_available=self.qc_worker.available(),
                    )
                else:
                    reason = "Runtime Qwen manquant" if not status.get("runtime_python_exists") else "Poids Qwen Base natifs manquants"
                    self._set_job(ready=False, stage="Runtime Qwen incomplet", error=reason, active_engine="qwen")
                return

            self.qwen_worker.stop()
            self._set_job(stage="Chargement OmniVoice…", progress=0, error="", active_engine="omnivoice")
            result = self.worker.request({"cmd": "init", "model_path": self.config.get("model_path")})
            self._set_job(
                ready=True,
                stage="OmniVoice HQ prêt · Auto-QC au lancement audio",
                model_load_seconds=result.get("load_seconds"),
                gpu=result.get("gpu") or "CUDA",
                qc_available=self.qc_worker.available(),
                active_engine="omnivoice",
                error="",
            )
        except Exception as exc:
            self._set_job(ready=False, stage="Runtime indisponible", error=str(exc), active_engine=self.active_engine)

    def get_bootstrap(self) -> dict[str, Any]:
        voices = []
        for v in self.config.get("voices") or []:
            row = dict(v)
            row["prompt_exists"] = Path(str(row.get("prompt_path") or "")).is_file()
            row["reference_exists"] = Path(str(row.get("reference_path") or "")).is_file()
            voices.append(row)
        qstat = self.qwen_status()
        return {
            "ok": True,
            "version": "1.9-qwen-restored",
            "voices": voices,
            "qwen_voices": qstat.get("voices") or [],
            "active_engine": self.active_engine,
            "defaults": self.config.get("defaults") or {},
            "runtime": {
                "python_exists": Path(str(self.config.get("runtime_python") or "")).is_file(),
                "model_exists": Path(str(self.config.get("model_path") or "")).is_dir(),
                "model_path": self.config.get("model_path"),
                "runtime_python": self.config.get("runtime_python"),
                "runner": self.detection.get("runner"),
                "detection_source": self.detection.get("source"),
                "storyrecap_root": self.detection.get("storyrecap_root"),
                "project_probe": self.detection.get("project_probe"),
                "caps_ready": self.detection.get("caps_ready"),
                "caps_missing": self.detection.get("caps_missing") or [],
                "messages": self.detection.get("messages") or [],
                "qc_python_exists": Path(str(self.config.get("qc_runtime_python") or "")).is_file(),
                "qc_model_exists": Path(str(self.config.get("qc_model_path") or "")).is_dir(),
                "qc_runtime_python": self.config.get("qc_runtime_python"),
                "qc_model_path": self.config.get("qc_model_path"),
                "qc_ready": self.qc_worker.available(),
                "qwen_ready": bool(qstat.get("ready")),
                "qwen_python_exists": bool(qstat.get("runtime_python_exists")),
                "qwen_runtime_python": qstat.get("runtime_python") or "",
                "qwen_model_exists": bool(qstat.get("model_exists")),
                "qwen_model_path": qstat.get("model_path") or "",
                "qwen_q8_detected": bool(qstat.get("q8_detected")),
                "qwen_q8_path": qstat.get("q8_path") or "",
                "qwen_download_capable": bool(qstat.get("download_capable")),
            },
            "voice_detection_source": self.detection.get("voices_source"),
            "job": self.get_job(),
            "history": self.get_history(),
            "qwen_download": dict(self.qwen_download),
            "base_url": f"http://127.0.0.1:{self.server.port}" if self.server else None,
        }

    def get_job(self) -> dict[str, Any]:
        with self.job_lock:
            return dict(self.job)

    def _persist_config(self) -> None:
        current = read_json(CONFIG_PATH, {})
        if not isinstance(current, dict):
            current = {}
        # Preserve any keys that detection added while writing the explicit user-facing paths.
        current.update({k: v for k, v in self.config.items() if k in {
            "storydub_root", "dubroom_root", "runtime_python", "model_path", "voices",
            "qwen_runtime_python", "qwen_download_python", "qwen_model_path", "qc_runtime_python", "qc_model_path", "defaults"
        }})
        write_json(CONFIG_PATH, current)

    def set_engine(self, engine: str) -> dict[str, Any]:
        engine = "qwen" if str(engine).lower() == "qwen" else "omnivoice"
        if self.get_job().get("running"):
            raise RuntimeError("Impossible de changer de moteur pendant une génération.")
        if engine == "qwen":
            status = self.qwen_status()
            if not status.get("runtime_python_exists"):
                raise RuntimeError("Runtime Qwen introuvable.")
            if not status.get("model_exists"):
                if status.get("q8_detected"):
                    raise RuntimeError("Le pack Q8/GGUF est détecté, mais Qwen Python a besoin du snapshot Base natif.")
                raise RuntimeError("Poids Qwen3-TTS 0.6B Base natifs introuvables.")
            self.worker.stop()
        else:
            self.qwen_worker.stop()
        self.active_engine = engine
        defaults = dict(self.config.get("defaults") or {})
        defaults["engine"] = engine
        self.config["defaults"] = defaults
        self._persist_config()
        self._set_job(active_engine=engine, ready=False, error="", stage="Changement de moteur…")
        if not self.lazy:
            threading.Thread(target=self._warmup, daemon=True).start()
        return {"ok": True, "engine": engine}

    def qwen_status(self) -> dict[str, Any]:
        runtime = _detect_qwen_runtime(self.config)
        model = _detect_qwen_model(self.config)
        q8 = _qwen_q8_candidate(self.config)
        voices = _scan_qwen_voices()
        return {
            "ok": True,
            "ready": bool(runtime and model and QWEN_WORKER_SCRIPT.is_file()),
            "runtime_python_exists": bool(runtime),
            "runtime_python": str(runtime) if runtime else str(self.config.get("qwen_runtime_python") or ""),
            "model_exists": bool(model),
            "model_path": str(model) if model else "",
            "q8_detected": bool(q8),
            "q8_path": str(q8) if q8 else "",
            "download_capable": bool(runtime),
            "voices": voices,
            "download": dict(self.qwen_download),
            "active": self.active_engine == "qwen",
        }

    def qwen_rescan(self) -> dict[str, Any]:
        runtime = _detect_qwen_runtime(self.config)
        model = _detect_qwen_model(self.config)
        if runtime:
            self.config["qwen_runtime_python"] = str(runtime)
            self.config["qwen_download_python"] = str(runtime)
        if model:
            self.config["qwen_model_path"] = str(model)
        self._persist_config()
        return self.qwen_status()

    def qwen_set_runtime(self, python_path: str) -> dict[str, Any]:
        p = Path(str(python_path or "")).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"python.exe Qwen introuvable: {p}")
        probe = subprocess.run(
            [str(p), "-c", "import qwen_tts, torch; print('OK', torch.cuda.is_available())"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=45, **hidden_popen_kwargs(),
        )
        if probe.returncode != 0:
            raise RuntimeError("Ce Python ne peut pas importer qwen_tts: " + (probe.stderr or probe.stdout)[-1200:])
        self.qwen_worker.stop()
        self.config["qwen_runtime_python"] = str(p)
        self.config["qwen_download_python"] = str(p)
        self._persist_config()
        return self.qwen_status()

    def qwen_set_model_path(self, model_path: str) -> dict[str, Any]:
        p = Path(str(model_path or "")).expanduser().resolve()
        if not _is_native_qwen_model(p):
            if p.is_dir() and ("q8" in p.name.lower() or any(p.glob("*.gguf"))):
                raise RuntimeError("Ce dossier est un pack Q8/GGUF. qwen_tts Python exige le snapshot natif Qwen3-TTS-12Hz-0.6B-Base.")
            raise RuntimeError("Dossier Qwen Base natif invalide: config.json + poids safetensors/bin requis.")
        self.qwen_worker.stop()
        self.config["qwen_model_path"] = str(p)
        self._persist_config()
        return self.qwen_status()

    def qwen_download_model(self) -> dict[str, Any]:
        if self.qwen_download.get("running"):
            return {"ok": True, **self.qwen_status()}
        runtime = _detect_qwen_runtime(self.config)
        if not runtime:
            raise RuntimeError("Runtime Qwen introuvable; impossible de lancer le téléchargement officiel.")
        target = QWEN_DEFAULT_MODEL_DIR
        target.mkdir(parents=True, exist_ok=True)
        self.qwen_download.update({"running": True, "progress": 1, "stage": "Connexion au dépôt officiel Qwen…", "error": ""})

        def run():
            try:
                code = (
                    "from huggingface_hub import snapshot_download;"
                    f"snapshot_download(repo_id={QWEN_MODEL_REPO!r}, local_dir={str(target)!r}, "
                    "local_dir_use_symlinks=False, resume_download=True)"
                )
                proc = subprocess.run(
                    [str(runtime), "-c", code],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    cwd=str(ROOT),
                    timeout=7200,
                    **hidden_popen_kwargs(),
                )
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or proc.stdout or "Téléchargement Qwen échoué")[-3000:])
                if not _is_native_qwen_model(target):
                    raise RuntimeError("Téléchargement terminé mais snapshot Qwen natif incomplet.")
                self.config["qwen_model_path"] = str(target.resolve())
                self._persist_config()
                self.qwen_download.update({"running": False, "progress": 100, "stage": "Qwen3-TTS 0.6B Base prêt.", "error": ""})
            except Exception as exc:
                self.qwen_download.update({"running": False, "stage": "Échec téléchargement", "error": str(exc)})
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, **self.qwen_status()}

    def qwen_clone(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        language = str(payload.get("language") or "en").lower().split("-", 1)[0]
        filename = Path(str(payload.get("filename") or "reference.wav")).name
        data_url = str(payload.get("audio_base64") or "")
        if not name:
            raise ValueError("Nom de voix manquant.")
        status = self.qwen_status()
        if not status.get("ready"):
            raise RuntimeError("Qwen n'est pas prêt: runtime ou snapshot Base natif manquant.")
        if "," not in data_url:
            raise ValueError("Audio de référence invalide.")
        header, encoded = data_url.split(",", 1)
        try:
            raw = base64.b64decode(encoded, validate=False)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Audio base64 invalide.") from exc
        if not raw or len(raw) > 30_000_000:
            raise ValueError("Référence audio vide ou trop lourde (30 Mo max).")

        voice_id = "qwen_" + uuid.uuid4().hex[:16]
        folder = QWEN_VOICES_DIR / voice_id
        folder.mkdir(parents=True, exist_ok=False)
        ext = Path(filename).suffix.lower()
        if ext not in {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus"}:
            ext = ".wav"
        reference = folder / ("reference" + ext)
        reference.write_bytes(raw)
        transcript = ""
        try:
            self.worker.stop()
            self.qwen_worker.stop()
            if not self.qc_worker.available():
                raise RuntimeError("Faster-Whisper n'est pas disponible pour transcrire la référence.")
            qc = self.qc_worker.request({
                "cmd": "transcribe",
                "model_path": self.config.get("qc_model_path"),
                "audio_path": str(reference),
                "language": language,
            })
            transcript = str(qc.get("text") or "").strip()
            if not transcript:
                raise RuntimeError("Faster-Whisper n'a retourné aucune transcription.")
            self.qc_worker.stop()

            icl = folder / "qwen_prompt.pt"
            if self._cancelled(): raise RuntimeError("Génération annulée")
            xvec = folder / "qwen_xvector.pt"
            model = _detect_qwen_model(self.config)
            if not model:
                raise RuntimeError("Snapshot Qwen Base natif introuvable.")
            self.qwen_worker.request({
                "cmd": "create_prompts",
                "model_path": str(model),
                "ref_audio_path": str(reference),
                "ref_text": transcript,
                "icl_prompt_path": str(icl),
                "xvec_prompt_path": str(xvec),
            })
            meta = {
                "id": voice_id,
                "name": name,
                "engine": "qwen",
                "language": language,
                "prompt_path": str(icl.resolve()),
                "xvec_prompt_path": str(xvec.resolve()),
                "reference_path": str(reference.resolve()),
                "ref_text": transcript,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            write_json(folder / "voice.json", meta)
            return {"ok": True, "voice": meta, "transcript": transcript}
        except Exception:
            if not (folder / "qwen_prompt.pt").is_file():
                shutil.rmtree(folder, ignore_errors=True)
            raise

    def start_generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        engine = str(payload.get("engine") or self.active_engine or "omnivoice").lower()
        engine = "qwen" if engine == "qwen" else "omnivoice"
        with self.job_lock:
            if self.job.get("running"):
                return {"ok": False, "error": "Une génération est déjà en cours."}
            self.job.update({
                "running": True,
                "progress": 0,
                "stage": "Préparation Auto-QC…",
                "error": "",
                "result": None,
                "cancel_requested": False,
                "retries": 0,
                "rescued_chunks": 0,
                "qc_scores": [],
                "active_engine": engine,
            })
        if engine == "qwen":
            thread = threading.Thread(target=self._generate_qwen_thread, args=(dict(payload or {}),), daemon=True)
        else:
            thread = threading.Thread(target=self._generate_thread, args=(dict(payload or {}),), daemon=True)
        thread.start()
        return {"ok": True}

    @staticmethod
    def _merge_wavs(paths: list[Path], output: Path, gap_ms: int) -> float:
        if not paths:
            raise RuntimeError("Aucun chunk audio validé à assembler.")
        params = None
        chunks: list[bytes] = []
        sample_rate = 0
        channels = 1
        sample_width = 2
        for path in paths:
            with wave.open(str(path), "rb") as wf:
                current = (wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getcomptype())
                if current[1] != 2 or current[0] != 1:
                    raise RuntimeError(f"Format WAV inattendu pour {path.name}: {current}")
                if params is None:
                    params = current
                    channels, sample_width, sample_rate, _ = current
                elif current != params:
                    raise RuntimeError(f"Formats WAV incompatibles: {path.name}")
                chunks.append(wf.readframes(wf.getnframes()))
        gap_frames = max(0, int(sample_rate * max(0, min(500, gap_ms)) / 1000.0))
        silence = b"\x00" * gap_frames * channels * sample_width
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_name(output.stem + ".tmp.wav")
        with wave.open(str(tmp), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            for i, data in enumerate(chunks):
                if i and silence:
                    wf.writeframesraw(silence)
                wf.writeframesraw(data)
        os.replace(tmp, output)
        with wave.open(str(output), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())

    @staticmethod
    def _clean_narrator2_master_start(path: Path, trim_ms: int = 35, fade_ms: int = 110) -> float:
        """Remove Narrator 2's pre-speech OmniVoice transient.

        The unwanted low thump is not always at sample zero: measured outputs put
        it around 40-180 ms, followed by a long quiet gap before real speech. Find
        that quiet gap and the sustained speech onset instead of relying on a fixed
        trim. Keep a short clean preroll so the first phoneme is never clipped.
        """
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            comptype = wf.getcomptype()
            frames = wf.getnframes()
            raw = wf.readframes(frames)
        if channels != 1 or sample_width != 2 or comptype != "NONE" or sample_rate <= 0:
            return frames / float(sample_rate or 1)

        samples = array("h")
        samples.frombytes(raw)
        if not samples:
            return 0.0

        window = max(1, int(sample_rate * 0.010))
        search_samples = min(len(samples), int(sample_rate * 1.500))
        rms_windows: list[float] = []
        for start in range(0, search_samples, window):
            block = samples[start:min(search_samples, start + window)]
            if not block:
                break
            energy = sum(float(value) * float(value) for value in block) / len(block)
            rms_windows.append((energy ** 0.5) / 32768.0)

        # A real speech onset follows at least 150 ms of near silence and remains
        # active in most of the next 80 ms. The short initial thump cannot satisfy
        # the preceding-silence condition, so it is discarded with the preroll.
        silence_run = 0
        onset_window: int | None = None
        for index, rms in enumerate(rms_windows):
            if rms < 0.0015:
                silence_run += 1
                continue
            lookahead = rms_windows[index:index + 8]
            sustained = sum(value >= 0.006 for value in lookahead) >= 5
            if silence_run >= 15 and sustained:
                onset_window = index
                break
            silence_run = 0

        adaptive = onset_window is not None
        if adaptive:
            preroll = int(sample_rate * 0.060)
            trim = max(0, onset_window * window - preroll)
        else:
            # Already-cleaned chunks have only the 60 ms preroll, not the long
            # post-transient silence. Leave them untouched so a second pass on
            # the merged master cannot eat the first phoneme.
            trim = 0
        trim = min(len(samples) - 1, trim)
        if trim:
            samples = array("h", samples[trim:])

        effective_fade_ms = 60 if adaptive else 0
        fade = min(len(samples), max(0, int(sample_rate * effective_fade_ms / 1000.0)))
        # Smoothstep fade: starts at absolute zero and rises gently, which suppresses
        # both a click and the short low-frequency "koum" transient.
        for i in range(fade):
            x = i / float(max(1, fade - 1))
            gain = x * x * (3.0 - 2.0 * x)
            samples[i] = int(round(samples[i] * gain))

        tmp = path.with_name(path.stem + ".startfix.tmp.wav")
        with wave.open(str(tmp), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(samples.tobytes())
        os.replace(tmp, path)
        return len(samples) / float(sample_rate)

    def _qc_transcribe(self, wav: Path, language: str) -> dict[str, Any] | None:
        if self.qc_disabled_for_job or not self.qc_worker.available():
            return None
        return self.qc_worker.request({
            "cmd": "transcribe",
            "model_path": self.config.get("qc_model_path"),
            "audio_path": str(wav),
            "language": language,
        })

    def _attempt_steps(self, base_steps: int) -> list[int]:
        base = max(8, min(64, int(base_steps)))
        rows = [base, base, max(base, 20), max(base, 32)]
        out: list[int] = []
        for value in rows:
            if value not in out or value == base and len(out) < 2:
                out.append(value)
        return out

    def _render_piece(
        self,
        *,
        text: str,
        voice_id: str,
        voice: dict[str, Any],
        speed: float,
        steps: int,
        language: str,
        work_dir: Path,
        label: str,
        allow_rescue_split: bool = True,
    ) -> tuple[list[Path], list[dict[str, Any]]]:
        if self._cancelled():
            raise RuntimeError("Génération annulée")

        attempts = self._attempt_steps(steps)
        threshold = qc_threshold(text)
        soft_floor = qc_soft_floor(text)
        best: tuple[float, Path, dict[str, Any]] | None = None
        attempt_reports: list[dict[str, Any]] = []

        for attempt_no, attempt_steps in enumerate(attempts, start=1):
            if self._cancelled():
                raise RuntimeError("Génération annulée")
            seed = random.SystemRandom().randint(1, 2_000_000_000)
            wav = work_dir / f"{label}_try{attempt_no}_{attempt_steps}s.wav"
            self._set_job(stage=f"{label} · génération {attempt_no}/{len(attempts)} · {attempt_steps} steps")
            # Narrator 2 is more sensitive to fresh-generation boundaries.
            # OmniVoice's own default edge fade is 100 ms. The previous 2 ms
            # (and even the first 12 ms patch) was far too short to suppress the
            # tiny onset thump heard at the beginning of some chunks.
            is_narrator_2 = voice_id == "voice_73c9c20e2de552c1815d"
            pad_duration = 0.060 if is_narrator_2 else 0.12
            fade_duration = 0.100 if is_narrator_2 else 0.002
            render = self.worker.request({
                "cmd": "generate_chunk",
                "model_path": self.config.get("model_path"),
                "voice_id": voice_id,
                "prompt_path": voice.get("prompt_path"),
                "output_path": str(wav),
                "text": text,
                "language": language,
                "speed": speed,
                "steps": attempt_steps,
                "seed": seed,
                "pad_duration": pad_duration,
                "fade_duration": fade_duration,
            })
            # The worker echoes the exact num_step value it passed to OmniVoice.
            # Fail loudly if the backend ever disagrees with the UI/orchestrator
            # instead of silently making the Steps control decorative.
            engine_steps = int(render.get("steps") or -1)
            if engine_steps != int(attempt_steps):
                raise RuntimeError(
                    f"Steps OmniVoice incohérents: demandé={attempt_steps}, moteur={engine_steps}"
                )
            sanity = wav_sanity(wav, text, speed)
            heard = ""
            sim = {"score": 1.0, "char_ratio": 1.0, "word_f1": 1.0}
            qc_mode = "acoustic"
            qc_error = ""
            if not self.qc_disabled_for_job and self.qc_worker.available() and sanity.get("ok"):
                self._set_job(stage=f"{label} · vérification prononciation…")
                try:
                    qc = self._qc_transcribe(wav, language)
                    if qc:
                        heard = str(qc.get("text") or "")
                        sim = text_similarity(text, heard)
                        qc_mode = f"whisper-{qc.get('device') or 'auto'}"
                except Exception as exc:
                    qc_error = str(exc)
                    # Do not destroy a usable render just because the QC model has
                    # an environment issue. Acoustic sanity remains active.
                    self.qc_worker.kill()
                    self.qc_disabled_for_job = True
                    qc_mode = "acoustic-fallback"

            score = float(sim.get("score") or 0.0) if sanity.get("ok") else 0.0
            accepted = bool(sanity.get("ok")) and (score >= threshold if qc_mode.startswith("whisper") else True)
            report = {
                "text": text,
                "heard": heard,
                "score": round(score, 4),
                "threshold": threshold,
                "steps": attempt_steps,
                "engine_steps": engine_steps,
                "seed": seed,
                "attempt": attempt_no,
                "accepted": accepted,
                "sanity": sanity,
                "qc_mode": qc_mode,
                "qc_error": qc_error,
                "duration": render.get("duration"),
            }
            attempt_reports.append(report)
            self._set_job(
                stage=(f"{label} · QC {round(score*100)}%" if qc_mode.startswith("whisper") else f"{label} · contrôle audio OK"),
                last_qc=report,
            )
            if sanity.get("ok") and (best is None or score > best[0]):
                best = (score, wav, report)
            if accepted:
                if is_narrator_2:
                    report["start_cleanup"] = "adaptive-per-chunk"
                    report["cleaned_duration"] = round(
                        self._clean_narrator2_master_start(wav), 3
                    )
                return [wav], attempt_reports
            self._set_job(retries=int(self.get_job().get("retries") or 0) + 1)

        # Repeated failure: split the exact troublesome clause more aggressively.
        if allow_rescue_split:
            smaller = split_text_aggressive(text, max_chars=82, max_words=18)
            if len(smaller) > 1:
                self._set_job(
                    stage=f"{label} · rescue: découpage plus fin",
                    rescued_chunks=int(self.get_job().get("rescued_chunks") or 0) + 1,
                )
                accepted_paths: list[Path] = []
                reports = list(attempt_reports)
                for sub_i, sub in enumerate(smaller, start=1):
                    paths, sub_reports = self._render_piece(
                        text=sub,
                        voice_id=voice_id,
                        voice=voice,
                        speed=speed,
                        steps=max(steps, 16),
                        language=language,
                        work_dir=work_dir,
                        label=f"{label}.{sub_i}",
                        allow_rescue_split=False,
                    )
                    accepted_paths.extend(paths)
                    reports.extend(sub_reports)
                return accepted_paths, reports

        # Last-resort spoken-only rewrite for a tiny set of repeatedly proven
        # unstable constructions. The saved script remains untouched.
        safe_variant = speech_safe_variant(text)
        if safe_variant != text:
            self._set_job(stage=f"{label} · rescue: formulation TTS sûre")
            paths, safe_reports = self._render_piece(
                text=safe_variant,
                voice_id=voice_id,
                voice=voice,
                speed=speed,
                steps=max(steps, 20),
                language=language,
                work_dir=work_dir,
                label=f"{label}.safe",
                allow_rescue_split=False,
            )
            for row in safe_reports:
                row["source_text"] = text
                row["spoken_variant"] = safe_variant
            return paths, attempt_reports + safe_reports

        # A small Whisper mismatch can be a name/transcription issue. Accept only
        # if the audio itself is sane and the best score stays above a conservative
        # soft floor. Truly bizarre/non-speech output is rejected.
        if best is not None and best[0] >= soft_floor:
            best[2]["accepted"] = True
            best[2]["soft_accept"] = True
            if voice_id == "voice_73c9c20e2de552c1815d":
                best[2]["start_cleanup"] = "adaptive-per-chunk"
                best[2]["cleaned_duration"] = round(
                    self._clean_narrator2_master_start(best[1]), 3
                )
            return [best[1]], attempt_reports

        # Final fail-open for QC only: if OmniVoice produced a structurally sane
        # WAV, a low Whisper text score must not abort the whole narration.
        # Whisper can be wrong on proper names, numbers and short fragments.
        # We keep the best acoustically valid render, mark it clearly as a
        # warning/forced accept, and let the full script complete. Real audio
        # failures (no sane WAV at all) still raise an error below.
        if best is not None and bool(best[2].get("sanity", {}).get("ok")):
            best_score = round(best[0] * 100)
            best[2]["accepted"] = True
            best[2]["soft_accept"] = True
            best[2]["forced_qc_accept"] = True
            best[2]["qc_warning"] = (
                f"Whisper QC faible ({best_score}%), meilleur WAV acoustiquement valide conservé"
            )
            if voice_id == "voice_73c9c20e2de552c1815d":
                best[2]["start_cleanup"] = "adaptive-per-chunk"
                best[2]["cleaned_duration"] = round(
                    self._clean_narrator2_master_start(best[1]), 3
                )
            self._set_job(
                stage=f"{label} · QC incertain {best_score}% · meilleur audio conservé",
                last_qc=best[2],
            )
            return [best[1]], attempt_reports

        # No acoustically sane WAV exists: this is a genuine generation/audio
        # failure, not a mere Whisper disagreement, so stopping is appropriate.
        best_score = round((best[0] if best else 0.0) * 100)
        raise RuntimeError(
            f"Audio invalide après plusieurs essais ({best_score}% QC): {text[:140]}"
        )

    def _render_qwen_piece(
        self,
        *,
        text: str,
        voice: dict[str, Any],
        language: str,
        work_dir: Path,
        label: str,
        allow_rescue_split: bool = True,
    ) -> tuple[list[Path], list[dict[str, Any]]]:
        if self._cancelled():
            raise RuntimeError("Génération annulée")
        threshold = qc_threshold(text)
        best: tuple[float, Path, dict[str, Any]] | None = None
        reports: list[dict[str, Any]] = []
        attempts = [(0.90, 1.05), (0.82, 1.06), (1.00, 1.08)]
        model = _detect_qwen_model(self.config)
        if not model:
            raise RuntimeError("Snapshot Qwen Base natif introuvable.")
        prompt_path = Path(str(voice.get("prompt_path") or ""))
        if not prompt_path.is_file():
            raise FileNotFoundError(f"Prompt Qwen introuvable: {prompt_path}")

        for attempt_no, (temperature, rep) in enumerate(attempts, start=1):
            seed = random.SystemRandom().randint(1, 2_000_000_000)
            wav = work_dir / f"{label}_qwen_try{attempt_no}.wav"
            self._set_job(stage=f"{label} · Qwen {attempt_no}/{len(attempts)}")
            render = self.qwen_worker.request({
                "cmd": "generate_chunk",
                "model_path": str(model),
                "prompt_path": str(prompt_path),
                "output_path": str(wav),
                "text": text,
                "language": language,
                "seed": seed,
                "temperature": temperature,
                "repetition_penalty": rep,
                "max_new_tokens": 2048,
            })
            sanity = wav_sanity(wav, text, 1.0)
            heard = ""
            sim = {"score": 1.0}
            qc_mode = "acoustic"
            qc_error = ""
            if not self.qc_disabled_for_job and self.qc_worker.available() and sanity.get("ok"):
                try:
                    qc = self._qc_transcribe(wav, language)
                    if qc:
                        heard = str(qc.get("text") or "")
                        sim = text_similarity(text, heard)
                        qc_mode = f"whisper-{qc.get('device') or 'auto'}"
                except Exception as exc:
                    # Qwen owns most VRAM; if Whisper cannot coexist, keep acoustic QC.
                    qc_error = str(exc)
                    self.qc_worker.kill()
                    self.qc_disabled_for_job = True
                    qc_mode = "acoustic-fallback"

            score = float(sim.get("score") or 0.0) if sanity.get("ok") else 0.0
            accepted = bool(sanity.get("ok")) and (score >= threshold if qc_mode.startswith("whisper") else True)
            report = {
                "text": text,
                "heard": heard,
                "score": round(score, 4),
                "threshold": threshold,
                "steps": None,
                "temperature": temperature,
                "repetition_penalty": rep,
                "qwen_prompt_mode": "icl",
                "engine": "qwen",
                "seed": seed,
                "attempt": attempt_no,
                "accepted": accepted,
                "sanity": sanity,
                "qc_mode": qc_mode,
                "qc_error": qc_error,
                "duration": render.get("duration"),
            }
            reports.append(report)
            self._set_job(stage=f"{label} · QC {round(score*100)}%" if qc_mode.startswith("whisper") else f"{label} · audio OK", last_qc=report)
            if sanity.get("ok") and (best is None or score > best[0]):
                best = (score, wav, report)
            if accepted:
                return [wav], reports
            self._set_job(retries=int(self.get_job().get("retries") or 0) + 1)

        if allow_rescue_split:
            smaller = split_text_aggressive(text, max_chars=82, max_words=18)
            if len(smaller) > 1:
                self._set_job(
                    stage=f"{label} · Qwen rescue",
                    rescued_chunks=int(self.get_job().get("rescued_chunks") or 0) + 1,
                )
                paths: list[Path] = []
                all_reports = list(reports)
                for sub_i, sub in enumerate(smaller, 1):
                    p, r = self._render_qwen_piece(
                        text=sub, voice=voice, language=language, work_dir=work_dir,
                        label=f"{label}.{sub_i}", allow_rescue_split=False,
                    )
                    paths.extend(p)
                    all_reports.extend(r)
                return paths, all_reports

        # Never throw away a sane Qwen render merely because Whisper disliked a name.
        if best is not None and best[2].get("sanity", {}).get("ok"):
            best[2]["accepted"] = True
            best[2]["soft_accept"] = True
            best[2]["forced_qc_accept"] = True
            return [best[1]], reports
        raise RuntimeError(f"Qwen n'a produit aucun WAV sain pour: {text[:140]}")

    def _generate_qwen_thread(self, payload: dict[str, Any]):
        started_all = time.perf_counter()
        work_dir: Path | None = None
        try:
            text = clean_text(str(payload.get("text") or ""))
            if not text:
                raise ValueError("Colle d'abord un texte à lire.")
            if len(text) > 50000:
                raise ValueError("Texte trop long pour une seule génération (50 000 caractères max).")
            status = self.qwen_status()
            if not status.get("runtime_python_exists"):
                raise RuntimeError("Runtime Qwen introuvable.")
            if not status.get("model_exists"):
                if status.get("q8_detected"):
                    raise RuntimeError("Ton dossier Q8/GGUF n'est pas le modèle natif attendu par qwen_tts.")
                raise RuntimeError("Snapshot Qwen3-TTS-12Hz-0.6B-Base introuvable.")

            voices = {str(v.get("id")): v for v in status.get("voices") or []}
            voice_id = str(payload.get("voice_id") or "")
            voice = voices.get(voice_id)
            if not voice:
                raise ValueError("Voix Qwen inconnue. Recrée ou resélectionne la voix Qwen.")

            language = str(payload.get("language") or voice.get("language") or "en").lower().split("-", 1)[0]
            defaults = self.config.get("defaults") or {}
            max_chars = int(defaults.get("max_chunk_chars") or 140)
            max_words = int(defaults.get("max_chunk_words") or 30)
            gap_ms = min(35, int(defaults.get("gap_ms") or 25))
            chunks = split_text_smart(text, max_chars=max_chars, max_words=max_words, merge_sentences=False)
            if not chunks:
                raise RuntimeError("Aucun passage Qwen générable.")

            # Qwen and OmniVoice are heavy GPU models. Never keep both resident.
            self.worker.stop()
            self.active_engine = "qwen"
            self._set_job(active_engine="qwen", ready=True, stage="Démarrage Qwen3-TTS…")
            now = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{now}_qwen_{uuid.uuid4().hex[:6]}.wav"
            output = HISTORY_DIR / filename
            work_dir = WORK_DIR / uuid.uuid4().hex
            work_dir.mkdir(parents=True, exist_ok=True)
            self.qc_disabled_for_job = False

            accepted: list[Path] = []
            reports: list[dict[str, Any]] = []
            for i, chunk in enumerate(chunks, 1):
                if self._cancelled():
                    raise RuntimeError("Génération annulée")
                self._set_job(stage=f"Qwen · passage {i}/{len(chunks)}", progress=int((i-1)*94/max(1,len(chunks))), chunk=i, chunks=len(chunks))
                paths, piece_reports = self._render_qwen_piece(
                    text=chunk, voice=voice, language=language, work_dir=work_dir,
                    label=f"Passage {i}/{len(chunks)}",
                )
                accepted.extend(paths)
                reports.extend(piece_reports)
                self._set_job(progress=int(i*94/max(1,len(chunks))))

            self._set_job(stage="Assemblage WAV Qwen…", progress=97)
            duration = self._merge_wavs(accepted, output, gap_ms=gap_ms)
            accepted_reports = [r for r in reports if r.get("accepted")]
            whisper_scores = [float(r.get("score") or 0.0) for r in accepted_reports if str(r.get("qc_mode") or "").startswith("whisper")]
            qc_avg = sum(whisper_scores)/len(whisper_scores) if whisper_scores else None
            qc_min = min(whisper_scores) if whisper_scores else None
            retries = max(0, len(reports)-len(accepted_reports))
            rescue_count = sum(1 for r in accepted_reports if r.get("soft_accept"))
            entry = {
                "id": filename,
                "filename": filename,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "text": text,
                "preview": text[:180] + ("…" if len(text)>180 else ""),
                "voice_id": voice_id,
                "voice_name": voice.get("name") or voice_id,
                "engine": "qwen",
                "model": QWEN_MODEL_REPO,
                "speed": 1.0,
                "steps": None,
                "language": language,
                "duration": round(duration, 3),
                "elapsed": round(time.perf_counter()-started_all, 3),
                "chunks": len(accepted),
                "source_chunks": len(chunks),
                "retries": retries,
                "rescued_chunks": int(self.get_job().get("rescued_chunks") or 0),
                "soft_accepts": rescue_count,
                "qc_enabled": bool(whisper_scores),
                "qc_average": round(qc_avg, 4) if qc_avg is not None else None,
                "qc_min": round(qc_min, 4) if qc_min is not None else None,
                "qc_device": self.get_job().get("qc_device"),
                "quality_report": reports,
                "url": f"/history/{filename}",
            }
            history = read_json(HISTORY_DB, [])
            if not isinstance(history, list):
                history = []
            history.insert(0, entry)
            write_json(HISTORY_DB, history[:50])
            self._set_job(
                running=False, ready=True, stage="Audio Qwen prêt · contrôle qualité terminé",
                progress=100, result=entry, error="", cancel_requested=False, active_engine="qwen",
            )
        except Exception as exc:
            cancelled = self._cancelled()
            if cancelled or str(exc) == "Génération annulée":
                self._set_job(running=False, stage="Annulé", error="", progress=0, cancel_requested=False)
            else:
                self._set_job(running=False, stage="Erreur", error=str(exc), progress=0, active_engine="qwen")
        finally:
            self.qc_worker.stop()
            if work_dir is not None:
                shutil.rmtree(work_dir, ignore_errors=True)

    def _generate_thread(self, payload: dict[str, Any]):
        started_all = time.perf_counter()
        work_dir: Path | None = None
        try:
            text = clean_text(str(payload.get("text") or ""))
            if not text:
                raise ValueError("Colle d'abord un texte à lire.")
            if len(text) > 50000:
                raise ValueError("Texte trop long pour une seule génération (50 000 caractères max).")

            voice_id = str(payload.get("voice_id") or (self.config.get("defaults") or {}).get("voice_id") or "")
            voices = {str(v.get("id")): v for v in self.config.get("voices") or []}
            voice = voices.get(voice_id)
            if not voice:
                raise ValueError("Voix narrateur inconnue.")
            if not Path(str(voice.get("prompt_path") or "")).is_file():
                raise FileNotFoundError("Prompt OmniVoice du narrateur introuvable.")

            speed = max(0.70, min(1.35, float(payload.get("speed") or 1.0)))
            steps = max(8, min(64, int(payload.get("steps") or 12)))
            language = str(payload.get("language") or "en").lower().split("-", 1)[0]
            defaults = self.config.get("defaults") or {}
            max_chars = int(defaults.get("max_chunk_chars") or 140)
            max_words = int(defaults.get("max_chunk_words") or 30)
            gap_ms = int(defaults.get("gap_ms") or 55)
            is_narrator_2 = voice_id == "voice_73c9c20e2de552c1815d"
            if is_narrator_2:
                # Do NOT restart OmniVoice after every period for Narrator 2.
                # Pack roughly 2-3 sentences / ~15-20 s per render instead.
                # This removes most places where the voice can emit its onset thump.
                max_chars = max(max_chars, 300)
                max_words = max(max_words, 55)
                gap_ms = min(gap_ms, 20)
            chunks = split_text_smart(
                text,
                max_chars=max_chars,
                max_words=max_words,
                merge_sentences=is_narrator_2,
            )
            if not chunks:
                raise RuntimeError("Aucun passage TTS générable.")

            now = time.strftime("%Y%m%d_%H%M%S")
            short_voice = "n1" if voice_id == "voice_ee40c6612ca1235e0c7a" else ("n2" if voice_id == "voice_73c9c20e2de552c1815d" else "voice")
            filename = f"{now}_{short_voice}_{uuid.uuid4().hex[:6]}.wav"
            output = HISTORY_DIR / filename
            work_dir = WORK_DIR / uuid.uuid4().hex
            work_dir.mkdir(parents=True, exist_ok=True)

            self.qc_disabled_for_job = False
            qc_available = self.qc_worker.available()
            if qc_available:
                self._set_job(stage="Chargement Faster-Whisper Auto-QC…", qc_available=True)
                try:
                    qc_init = self.qc_worker.request({"cmd": "init", "model_path": self.config.get("qc_model_path")})
                    self._set_job(
                        qc_ready=True,
                        qc_device=str(qc_init.get("device") or ""),
                        qc_compute_type=str(qc_init.get("compute_type") or ""),
                    )
                except Exception as exc:
                    self.qc_worker.kill()
                    self.qc_disabled_for_job = True
                    qc_available = False
                    self._set_job(qc_ready=False, qc_warning=str(exc))

            accepted: list[Path] = []
            reports: list[dict[str, Any]] = []
            for i, chunk in enumerate(chunks, start=1):
                if self._cancelled():
                    raise RuntimeError("Génération annulée")
                base_progress = int((i - 1) * 94 / max(1, len(chunks)))
                self._set_job(
                    stage=f"Passage {i}/{len(chunks)}",
                    progress=base_progress,
                    chunk=i,
                    chunks=len(chunks),
                )
                paths, piece_reports = self._render_piece(
                    text=chunk,
                    voice_id=voice_id,
                    voice=voice,
                    speed=speed,
                    steps=steps,
                    language=language,
                    work_dir=work_dir,
                    label=f"Passage {i}/{len(chunks)}",
                )
                accepted.extend(paths)
                reports.extend(piece_reports)
                self._set_job(progress=int(i * 94 / max(1, len(chunks))))

            self._set_job(stage="Assemblage WAV validé…", progress=97)
            duration = self._merge_wavs(accepted, output, gap_ms=gap_ms)
            if is_narrator_2:
                self._set_job(stage="Nettoyage du démarrage Narrateur 2…", progress=98)
                duration = self._clean_narrator2_master_start(output, trim_ms=35, fade_ms=110)

            accepted_reports = [r for r in reports if r.get("accepted")]
            whisper_scores = [float(r.get("score") or 0.0) for r in accepted_reports if str(r.get("qc_mode") or "").startswith("whisper")]
            qc_avg = (sum(whisper_scores) / len(whisper_scores)) if whisper_scores else None
            qc_min = min(whisper_scores) if whisper_scores else None
            retries = max(0, len(reports) - len(accepted_reports))
            rescue_count = sum(1 for r in accepted_reports if r.get("soft_accept"))

            entry = {
                "id": filename,
                "filename": filename,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "text": text,
                "preview": text[:180] + ("…" if len(text) > 180 else ""),
                "voice_id": voice_id,
                "voice_name": voice.get("name") or voice_id,
                "engine": "omnivoice",
                "model": "OmniVoice HQ",
                "speed": speed,
                "steps": steps,
                "language": language,
                "duration": round(duration, 3),
                "elapsed": round(time.perf_counter() - started_all, 3),
                "chunks": len(accepted),
                "source_chunks": len(chunks),
                "retries": retries,
                "rescued_chunks": int(self.get_job().get("rescued_chunks") or 0),
                "soft_accepts": rescue_count,
                "qc_enabled": bool(whisper_scores),
                "qc_average": round(qc_avg, 4) if qc_avg is not None else None,
                "qc_min": round(qc_min, 4) if qc_min is not None else None,
                "qc_device": self.get_job().get("qc_device"),
                "quality_report": reports,
                "url": f"/history/{filename}",
            }
            history = read_json(HISTORY_DB, [])
            if not isinstance(history, list):
                history = []
            history.insert(0, entry)
            history = history[:50]
            write_json(HISTORY_DB, history)
            self._set_job(
                running=False,
                ready=True,
                stage="Audio prêt · contrôle qualité terminé",
                progress=100,
                result=entry,
                error="",
                cancel_requested=False,
            )
        except Exception as exc:
            cancelled = self._cancelled()
            if cancelled or str(exc) == "Génération annulée":
                self._set_job(running=False, stage="Annulé", error="", progress=0, cancel_requested=False)
            else:
                self._set_job(running=False, stage="Erreur", error=str(exc), progress=0)
        finally:
            # Faster-Whisper is kept for the whole script, then released so it does
            # not permanently consume VRAM next to OmniVoice / Ollama.
            self.qc_worker.stop()
            if work_dir is not None:
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                except Exception:
                    pass

    def cancel_generate(self) -> dict[str, Any]:
        with self.job_lock:
            if not self.job.get("running"):
                return {"ok": True}
            self.job.update({"running": False, "stage": "Annulé", "error": "", "progress": 0, "cancel_requested": True})
        self.worker.kill()
        self.qwen_worker.kill()
        self.qc_worker.kill()
        # Restart only the selected engine. QC remains lazy and frees VRAM.
        if not self.lazy:
            threading.Thread(target=self._warmup, daemon=True).start()
        return {"ok": True}

    def get_history(self) -> list[dict[str, Any]]:
        history = read_json(HISTORY_DB, [])
        if not isinstance(history, list):
            return []
        valid = []
        for item in history[:50]:
            if Path(HISTORY_DIR / str(item.get("filename") or "")).is_file():
                valid.append(item)
        return valid

    def save_audio(self, filename: str) -> dict[str, Any]:
        """Copy a generated WAV to the user's Downloads folder.

        No GUI bridge is used here. The operation is invoked through the local
        HTTP API, so it keeps working even if PyWebView changes its JS bridge.
        """
        source = HISTORY_DIR / Path(str(filename or "")).name
        if not source.is_file():
            return {"ok": False, "error": "Audio introuvable."}
        target_dir = Path.home() / "Downloads"
        if not target_dir.is_dir():
            target_dir = Path.home() / "Desktop"
        if not target_dir.is_dir():
            target_dir = HISTORY_DIR
        target = target_dir / source.name
        stem, suffix = source.stem, source.suffix
        index = 2
        while target.exists():
            target = target_dir / f"{stem}_{index}{suffix}"
            index += 1
        shutil.copy2(source, target)
        return {"ok": True, "path": str(target)}

    def delete_history(self, filename: str) -> dict[str, Any]:
        name = Path(str(filename or "")).name
        path = HISTORY_DIR / name
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        history = read_json(HISTORY_DB, [])
        if isinstance(history, list):
            history = [x for x in history if str(x.get("filename") or "") != name]
            write_json(HISTORY_DB, history)
        return {"ok": True, "history": self.get_history()}

    def open_history_folder(self) -> dict[str, Any]:
        try:
            if os.name == "nt":
                os.startfile(str(HISTORY_DIR))
            else:
                subprocess.Popen(["xdg-open", str(HISTORY_DIR)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def shutdown(self):
        self.qc_worker.stop()
        self.qwen_worker.stop()
        self.worker.stop()


def main() -> int:
    import webview
    from backend.library import LibraryLock
    library_lock = LibraryLock(ROOT)
    server = LocalServer()
    api = AppAPI(server)
    server.bind_api(api)
    server.start()
    url = f"http://127.0.0.1:{server.port}/web/index.html"
    # PyWebView is now only the native window. No js_api bridge is required.
    window = webview.create_window(
        "Narrator Studio · StoryDub",
        url=url,
        width=1480,
        height=920,
        min_size=(1050, 680),
        background_color="#f7f7f5",
    )
    api.bind_window(window)
    try:
        webview.start(debug=False)
    finally:
        api.shutdown()
        server.stop()
        library_lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
