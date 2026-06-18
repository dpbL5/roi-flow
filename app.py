from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import base64
import hashlib
import stat
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


load_local_env(ROOT / ".env")

PROJECTS_DIR = ROOT / "projects"
WEB_DIR = ROOT / "web"
HOST = "127.0.0.1"
PORT = int(os.environ.get("FLOW_VEO_PORT", "8765"))
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
APP_CONFIG_DIR = Path(os.environ.get("FLOW_VEO_CONFIG_DIR") or (LOCAL_APPDATA / "FlowVeoStudio"))
PROMPT_SETTINGS_PATH = APP_CONFIG_DIR / "prompt_settings.json"
PROJECT_SETTINGS_PATH = APP_CONFIG_DIR / "project_settings.json"
GOOGLE_AI_API_BASE = os.environ.get("GOOGLE_AI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GOOGLE_AI_MODEL = os.environ.get("GOOGLE_AI_MODEL") or "gemini-3.5-flash"
GOOGLE_AI_TEMPERATURE = float(os.environ.get("FLOW_PROMPT_TEMPERATURE", "0.4"))
GOOGLE_AI_MAX_TOKENS = int(os.environ.get("FLOW_PROMPT_MAX_TOKENS", "4000"))

EXTENSION_RUN_LOCK = threading.RLock()
EXTENSION_RUN = {
    "status": "idle",
    "phase": "idle",
    "message": "Chế độ visual bằng tiện ích đang chờ.",
    "project_path": None,
    "flow_project_url": None,
    "batch_count": 30,
    "started_at": None,
    "updated_at": None,
    "finished_at": None,
    "stop_requested": False,
    "connected_at": None,
    "tab_url": "",
    "user_agent": "",
    "last_index": None,
    "submitted_in_batch": 0,
    "awaiting_user_action": False,
    "pending_action": None,
    "audio_cue": None,
    "resume_phase": None,
    "counts": None,
    "auto_mode": False,
    "log": [],
}
EXTENSION_FINAL_RETRY_MAX_ATTEMPTS = int(os.environ.get("FLOW_EXTENSION_FINAL_RETRY_MAX_ATTEMPTS", "3"))
EXTENSION_ROUND_BATCH = int(os.environ.get("FLOW_EXTENSION_ROUND_BATCH", "30"))
EXTENSION_REGEN_MAX = int(os.environ.get("FLOW_EXTENSION_REGEN_MAX", "2"))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def secure_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def load_prompt_settings() -> dict:
    if not PROMPT_SETTINGS_PATH.exists():
        return {}
    try:
        data = read_json(PROMPT_SETTINGS_PATH)
    except Exception:
        traceback.print_exc()
        return {}
    return data if isinstance(data, dict) else {}


def save_prompt_settings(updates: dict) -> dict:
    settings = load_prompt_settings()
    for key, value in updates.items():
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = value
    settings["updated_at"] = utc_now()
    secure_write_json(PROMPT_SETTINGS_PATH, settings)
    return settings


def configured_google_ai_key() -> str:
    settings = load_prompt_settings()
    return (
        str(settings.get("google_ai_api_key") or "").strip()
        or os.environ.get("GOOGLE_AI_API_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )


def configured_google_ai_model() -> str:
    settings = load_prompt_settings()
    return str(settings.get("google_ai_model") or GOOGLE_AI_MODEL).strip() or GOOGLE_AI_MODEL


def configured_google_ai_base() -> str:
    settings = load_prompt_settings()
    return str(settings.get("google_ai_base") or GOOGLE_AI_API_BASE).strip().rstrip("/") or GOOGLE_AI_API_BASE


def masked_secret_tail(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return "****" + value[-4:]


def public_prompt_settings() -> dict:
    api_key = configured_google_ai_key()
    return {
        "provider": "google_ai_studio",
        "configured": bool(api_key),
        "api_key_tail": masked_secret_tail(api_key),
        "model": configured_google_ai_model(),
        "base_url": configured_google_ai_base(),
        "settings_path": str(PROMPT_SETTINGS_PATH),
    }


def load_project_settings() -> dict:
    if not PROJECT_SETTINGS_PATH.exists():
        return {}
    try:
        data = read_json(PROJECT_SETTINGS_PATH)
    except Exception:
        traceback.print_exc()
        return {}
    return data if isinstance(data, dict) else {}


def save_project_settings(updates: dict) -> dict:
    settings = load_project_settings()
    for key, value in updates.items():
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = value
    settings["updated_at"] = utc_now()
    secure_write_json(PROJECT_SETTINGS_PATH, settings)
    return settings


def default_frames_path() -> str:
    for key in ("FLOW_VEO_FRAMES_DIR", "FLOW_VEO_DEFAULT_FRAMES_DIR"):
        value = os.environ.get(key, "").strip()
        if value:
            return str(Path(value))
    local_default = ROOT / "projects" / "default" / "frames"
    local_default.mkdir(parents=True, exist_ok=True)
    return str(local_default)


def configured_frames_path() -> str:
    settings = load_project_settings()
    return str(settings.get("frames_path") or default_frames_path()).strip()


def same_frames_path(left: str, right: str) -> bool:
    if not left or not right:
        return False
    try:
        return resolve_frames_project(left)["frames_dir"].resolve() == resolve_frames_project(right)["frames_dir"].resolve()
    except Exception:
        return str(left).strip().lower() == str(right).strip().lower()


def public_project_settings() -> dict:
    settings = load_project_settings()
    frames_path = configured_frames_path()
    state_flow_url = saved_flow_project_url(frames_path) if frames_path else ""
    settings_flow_url = clean_flow_project_url(str(settings.get("flow_project_url") or ""))
    return {
        "frames_path": frames_path,
        "flow_project_url": state_flow_url or settings_flow_url,
        "project_name": str(settings.get("project_name") or "composer_project"),
        "prompt_batch_count": int(settings.get("prompt_batch_count") or 20),
        "visual_batch_count": int(settings.get("visual_batch_count") or EXTENSION_ROUND_BATCH),
        "settings_path": str(PROJECT_SETTINGS_PATH),
    }


def save_project_settings_from_body(body: dict) -> dict:
    current = public_project_settings()
    frames_path = str(
        body.get("frames_path")
        or body.get("project_path")
        or body.get("path")
        or current.get("frames_path")
        or ""
    ).strip()
    if not frames_path:
        raise ValueError("Missing frames folder path.")

    project = resolve_frames_project(frames_path)
    frames_path = str(project["frames_dir"])
    updates = {
        "frames_path": frames_path,
        "project_name": safe_project_name(str(body.get("project_name") or current.get("project_name") or "composer_project")),
        "prompt_batch_count": max(1, int(body.get("prompt_batch_count") or current.get("prompt_batch_count") or 20)),
        "visual_batch_count": max(1, int(body.get("visual_batch_count") or current.get("visual_batch_count") or EXTENSION_ROUND_BATCH)),
    }

    if "flow_project_url" in body or "url" in body:
        flow_url = require_flow_project_url(body.get("flow_project_url") or body.get("url") or "")
        updates["flow_project_url"] = flow_url
        save_flow_project_url(frames_path, flow_url)

    save_project_settings(updates)
    return public_project_settings()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_utc_datetime(value: str | None):
    if not value:
        return None
    try:
        normalized = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def json_response(handler: BaseHTTPRequestHandler, status: int, payload) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, status: int, body: str, content_type: str) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def safe_console_write(text: str) -> None:
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def safe_error_write(text: str) -> None:
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except Exception:
        pass


def safe_project_name(value: str) -> str:
    value = value.strip() or "default_project"
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)
    return value.strip("._") or "default_project"


def resolve_frames_project(path_value: str):
    path = Path(path_value)
    if path.suffix.lower() == ".json":
        sentences_path = path
        frames_dir = path.parent
    else:
        frames_dir = path
        sentences_path = frames_dir / "sentences.json"

    return {
        "frames_dir": frames_dir,
        "sentences_path": sentences_path,
        "prompts_path": frames_dir / "veo_prompts.json",
        "state_path": frames_dir / "flow_veo_state.json",
        "clips_dir": frames_dir,
        "work_dir": frames_dir / "_flow_veo_studio",
        "downloads_dir": frames_dir / "_flow_veo_studio" / "downloads",
    }


def load_project_state(path_value: str) -> dict:
    project = resolve_frames_project(path_value)
    state_path = project["state_path"]
    if not state_path.exists():
        return {}
    try:
        data = read_json(state_path)
    except Exception:
        traceback.print_exc()
        return {}
    return data if isinstance(data, dict) else {}


def save_project_state(path_value: str, updates: dict) -> dict:
    project = resolve_frames_project(path_value)
    state = load_project_state(path_value)
    state.update(updates)
    state["updated_at"] = utc_now()
    write_json(project["state_path"], state)
    return state


def saved_flow_project_url(path_value: str) -> str:
    return clean_flow_project_url(str(load_project_state(path_value).get("flow_project_url") or ""))


def save_flow_project_url(path_value: str, url: str | None) -> str:
    clean_url = require_flow_project_url(url)
    state = save_project_state(path_value, {"flow_project_url": clean_url})
    return str(state.get("flow_project_url") or "").strip()


DEFAULT_SCRIPT_PROMPT_STYLE = (
    "Create realistic, cinematic English prompts for Google Veo. "
    "Adapt each script fragment into a concrete visual scene with varied camera scale, "
    "practical motion, natural sound details, and no music, no dialogue, no voiceover. "
    "Every prompt must start with the exact index marker in this format: \"#000,\"."
)

DEFAULT_SHOT_CYCLE = [
    "extreme close-up",
    "close-up",
    "medium shot",
    "medium-wide shot",
    "wide shot",
    "overhead shot",
]


def load_sentences(path_value: str):
    project = resolve_frames_project(path_value)
    path = project["sentences_path"]
    if not path.exists():
        prompts_path = project["prompts_path"]
        if prompts_path.exists():
            prompts = load_existing_prompts(path_value)
            return [{"index": int(p["index"]), "text": str(p.get("source_text", ""))} for p in prompts if "index" in p]
        raise FileNotFoundError(f"Không tìm thấy tệp sentences.json: {path}")
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError("sentences.json phải là một mảng")

    normalized = []
    for item in data:
        if not isinstance(item, dict) or "index" not in item or "text" not in item:
            raise ValueError("Mỗi mục trong sentences.json phải có index và text")
        normalized.append({"index": int(item["index"]), "text": str(item["text"])})
    return normalized


def sentence_items_to_text(items) -> str:
    return "\n".join(str(item.get("text", "")).strip() for item in items if str(item.get("text", "")).strip())


def parse_sentence_text(script_text: str):
    lines = [line.strip() for line in (script_text or "").splitlines()]
    fragments = [line for line in lines if line]
    if not fragments:
        raise ValueError("Kịch bản trống. Hãy nhập ít nhất một đoạn.")
    return [{"index": index, "text": text} for index, text in enumerate(fragments)]


def load_script_for_editor(path_value: str):
    project = resolve_frames_project(path_value)
    path = project["sentences_path"]
    if not path.exists():
        return {
            "exists": False,
            "items": [],
            "script_text": "",
            "frames_dir": str(project["frames_dir"]),
            "sentences_path": str(path),
        }
    items = load_sentences(path_value)
    return {
        "exists": True,
        "items": items,
        "script_text": sentence_items_to_text(items),
        "frames_dir": str(project["frames_dir"]),
        "sentences_path": str(path),
    }


def save_script_from_editor(path_value: str, script_text: str):
    project = resolve_frames_project(path_value)
    path = project["sentences_path"]
    items = parse_sentence_text(script_text)
    backup_path = None
    if path.exists():
        backup_path = project["work_dir"] / "sentences.backup.json"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path.exists():
            backup_path.unlink()
        path.rename(backup_path)
    write_json(path, items)
    return {
        "ok": True,
        "items": items,
        "total": len(items),
        "script_text": sentence_items_to_text(items),
        "frames_dir": str(project["frames_dir"]),
        "sentences_path": str(path),
        "backup_path": str(backup_path) if backup_path else "",
    }


def load_existing_prompts(path_value: str):
    project = resolve_frames_project(path_value)
    prompts_path = project["prompts_path"]
    if not prompts_path.exists():
        return []
    data = read_json(prompts_path)
    if not isinstance(data, list):
        raise ValueError(f"Tệp prompt phải là một mảng: {prompts_path}")
    return data


def project_status(path_value: str):
    project = resolve_frames_project(path_value)
    project_state = load_project_state(path_value)
    existing = load_existing_prompts(path_value)
    try:
        sentences = load_sentences(path_value)
    except FileNotFoundError:
        sentences = [{"index": int(p["index"]), "text": str(p.get("source_text", ""))} for p in existing if "index" in p]
    sentence_indexes = [int(item["index"]) for item in sentences]
    generated_indexes = {
        int(item["index"])
        for item in existing
        if item.get("veo_prompt") and item.get("status") != "failed"
    }
    missing = [idx for idx in sentence_indexes if idx not in generated_indexes]
    next_start = missing[0] if missing else None
    status_counts = {
        "prompt_ready": 0,
        "submitted": 0,
        "downloaded": 0,
        "failed": 0,
        "other": 0,
    }
    for item in existing:
        status = item.get("status") or "other"
        if status in status_counts:
            status_counts[status] += 1
        else:
            status_counts["other"] += 1
    mp4_count = 0
    if project["clips_dir"].exists():
        mp4_count = sum(1 for item in project["clips_dir"].glob("*.mp4") if item.is_file())
    return {
        "total": len(sentences),
        "generated_count": len(generated_indexes),
        "missing_count": len(missing),
        "next_start_index": next_start,
        "counts": status_counts,
        "mp4_count": mp4_count,
        "frames_dir": str(project["frames_dir"]),
        "sentences_path": str(project["sentences_path"]),
        "prompts_path": str(project["prompts_path"]),
        "clips_dir": str(project["clips_dir"]),
        "state_path": str(project["state_path"]),
        "flow_project_url": saved_flow_project_url(path_value),
    }


def pick_range(sentences, start_index: int, count: int):
    selected = [item for item in sentences if item["index"] >= start_index]
    return selected[:count]


def pick_missing_range(sentences, project_path: str, start_index: int, count: int):
    existing = load_existing_prompts(project_path)
    generated_indexes = {
        int(item["index"])
        for item in existing
        if item.get("veo_prompt") and item.get("status") != "failed"
    }
    selected = [
        item for item in sentences
        if item["index"] >= start_index and item["index"] not in generated_indexes
    ]
    return selected[:count]


def with_neighbors(sentences, selected):
    by_index = {item["index"]: item["text"] for item in sentences}
    result = []
    for item in selected:
        idx = item["index"]
        result.append(
            {
                "index": idx,
                "previous": by_index.get(idx - 1),
                "text": item["text"],
                "next": by_index.get(idx + 1),
            }
        )
    return result


def build_user_prompt(items, style_override: str = ""):
    style = style_override.strip() or DEFAULT_SCRIPT_PROMPT_STYLE
    return (
        "Generate Google Veo prompts for these script fragments.\n\n"
        "Use this project prompt style as the highest priority:\n"
        f"{style}\n\n"
        "Use previous/current/next text to understand the meaning. The current text is the main target.\n"
        "Do not make a literal translation. Invent a visual scene that fits the source text.\n"
        "Return JSON only through the required schema.\n\n"
        "Rules for each item:\n"
        "- index must match the input index.\n"
        "- title_slug must be lowercase English words joined by underscores, 4-8 words, no index.\n"
        "- veo_prompt must start with the exact 3-digit index, for example \"#000,\".\n"
        "- veo_prompt must be one English sentence, ready to paste into Google Flow / Veo.\n"
        "- Include a camera shot scale and vary it across the batch.\n"
        "- Include ASMR natural sound details.\n"
        "- Explicitly include: no music, no dialogue, no voiceover.\n"
        "- Do not include quotes around the prompt text inside veo_prompt.\n\n"
        f"Preferred shot cycle: {json.dumps(DEFAULT_SHOT_CYCLE, ensure_ascii=False)}\n\n"
        "Script fragments:\n"
        f"{json.dumps(items, ensure_ascii=False, indent=2)}"
    )


def strip_model_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json|JSON)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def parse_model_json_object(text: str):
    value = strip_model_fence(text)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            return json.loads(value[start : end + 1])
        raise


def google_ai_prompt_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["prompts"],
        "properties": {
            "prompts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["index", "title_slug", "veo_prompt"],
                    "properties": {
                        "index": {"type": "integer"},
                        "title_slug": {"type": "string"},
                        "veo_prompt": {"type": "string"},
                    },
                },
            }
        },
    }


def google_ai_model_path(model: str | None) -> str:
    clean = (model or configured_google_ai_model()).strip()
    if clean.startswith("models/"):
        return clean
    return f"models/{clean}"


def google_ai_generate_url(model: str | None) -> str:
    api_key = configured_google_ai_key()
    if not api_key:
        raise RuntimeError("Google AI Studio API key is not configured.")
    return f"{configured_google_ai_base()}/{google_ai_model_path(model)}:generateContent?{urlencode({'key': api_key})}"


def extract_google_ai_text(response_data: dict) -> str:
    chunks = []
    for candidate in response_data.get("candidates", []):
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            if part.get("text"):
                chunks.append(str(part["text"]))
    return "".join(chunks).strip()


def post_google_ai_generate(payload: dict, model: str | None = None, timeout: int = 180) -> dict:
    req = request.Request(
        google_ai_generate_url(model),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google AI Studio API error {exc.code}: {detail}") from exc


def call_google_ai_text(system_prompt: str, user_prompt: str, model: str | None = None):
    schema = google_ai_prompt_schema()
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        system_prompt
                        + "\nReturn only a JSON object that follows this schema: "
                        + json.dumps(schema)
                    )
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": GOOGLE_AI_TEMPERATURE,
            "maxOutputTokens": GOOGLE_AI_MAX_TOKENS,
        },
    }
    data = post_google_ai_generate(payload, model=model)
    output_text = extract_google_ai_text(data)
    if not output_text:
        raise RuntimeError(f"Google AI Studio returned no text: {data}")
    return parse_model_json_object(output_text)


def call_google_ai_vision(
    image_bytes: bytes,
    mime_type: str,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
) -> str:
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": GOOGLE_AI_TEMPERATURE,
            "maxOutputTokens": GOOGLE_AI_MAX_TOKENS,
        },
    }
    data = post_google_ai_generate(payload, model=model)
    output_text = extract_google_ai_text(data)
    if not output_text:
        raise RuntimeError(f"Google AI Studio returned no vision text: {data}")
    return strip_model_fence(output_text)

COMPOSER_PLATFORMS = {
    "veo_3_1": {
        "label": "Veo 3.1",
        "target": "Google Veo 3.1 / Flow",
        "audio_rule": "Include natural production sound when useful; no music, no dialogue, no voiceover.",
    },
}

COMPOSER_ORIENTATIONS = {
    "landscape": "horizontal 16:9",
    "portrait": "vertical 9:16",
}


def composer_platform(platform_id: str | None) -> dict:
    return COMPOSER_PLATFORMS.get(platform_id or "", COMPOSER_PLATFORMS["veo_3_1"])


def composer_orientation(orientation_id: str | None) -> str:
    return COMPOSER_ORIENTATIONS.get(orientation_id or "", COMPOSER_ORIENTATIONS["landscape"])


def composer_model(body: dict) -> str:
    return str(body.get("model") or body.get("prompt_model") or configured_google_ai_model()).strip() or configured_google_ai_model()


def slugify_title(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", (value or "").lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug[:80].strip("_") or fallback


def next_prompt_index(project_path: str) -> int:
    try:
        existing = load_existing_prompts(project_path)
    except Exception:
        existing = []
    indexes = [int(item["index"]) for item in existing if isinstance(item, dict) and "index" in item]
    return max(indexes) + 1 if indexes else 0


def decode_data_url(data_url: str) -> tuple[str, bytes]:
    if "," in data_url:
        header, encoded = data_url.split(",", 1)
        match = re.search(r"data:([^;]+)", header)
        mime_type = match.group(1) if match else "image/png"
    else:
        encoded = data_url
        mime_type = "image/png"
    return mime_type, base64.b64decode(encoded)


def safe_upload_filename(filename: str, index: int, mime_type: str) -> str:
    raw_name = Path(filename or "").name
    suffix = Path(raw_name).suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(mime_type) or ".png"
    stem = slugify_title(Path(raw_name).stem, f"image_{index:03d}")
    return f"{stem}{suffix}"


def normalize_prompt_marker(index: int, prompt: str) -> str:
    value = strip_model_fence(prompt).strip().strip('"')
    value = re.sub(r"^\s*#?\d{1,4}\s*,?\s*", "", value)
    if not value:
        raise RuntimeError("AI returned an empty prompt")
    return f"#{index:03d}, {value}"


def append_required_audio_rule(platform: dict, prompt: str) -> str:
    if platform.get("target") != COMPOSER_PLATFORMS["veo_3_1"]["target"]:
        return prompt
    lowered = prompt.lower()
    required = "no music, no dialogue, no voiceover"
    if required not in lowered:
        prompt = prompt.rstrip(" .") + f", {required}."
    return prompt


def build_composer_ai_request(index: int, body: dict, image_context: str | None = None) -> tuple[str, str]:
    user_prompt = str(body.get("prompt") or "").strip()
    platform = composer_platform(str(body.get("platform") or "veo_3_1"))
    orientation = composer_orientation(str(body.get("orientation") or "landscape"))
    mode = str(body.get("mode") or "text_to_video")

    system_prompt = (
        "You are a senior video prompt writer. Create production-ready prompts for video generation. "
        "Return structured JSON only."
    )
    user_parts = [
        f"Create exactly one prompt item for index {index}.",
        f"Mode: {mode}.",
        f"Target platform: {platform['target']}.",
        f"Aspect/orientation: {orientation}.",
        "Improvise from the user input instead of merely rephrasing it.",
        "The scene must be concrete, cinematic, physically plausible, and easy for a video model to follow.",
        "Describe subject, setting, camera shot or movement, lighting, visible motion, and mood.",
        platform["audio_rule"],
        f'veo_prompt must start with "#{index:03d}," exactly.',
        "title_slug must be lowercase English words joined by underscores, 4-8 words, no index.",
    ]
    if user_prompt:
        user_parts.append(f"User text: {user_prompt}")
    if image_context:
        user_parts.append(
            "Image reference description. Preserve the important visible subject, composition, colors, "
            f"and mood from this reference while turning it into video motion: {image_context}"
        )
    return system_prompt, "\n".join(user_parts)


def composer_item_from_ai(index: int, body: dict, source_text: str, raw_item: dict, source_images=None) -> dict:
    platform_id = str(body.get("platform") or "veo_3_1")
    mode = str(body.get("mode") or "text_to_video")
    orientation_id = str(body.get("orientation") or "landscape")
    platform = composer_platform(platform_id)
    prompt = normalize_prompt_marker(index, str(raw_item.get("veo_prompt") or ""))
    prompt = append_required_audio_rule(platform, prompt)
    slug_seed = raw_item.get("title_slug") or source_text or prompt
    slug = slugify_title(str(slug_seed), f"scene_{index:03d}")
    item = {
        "index": index,
        "source_text": source_text,
        "title_slug": slug,
        "flow_title": f"{index:03d}_{slug}",
        "veo_prompt": prompt,
        "status": "prompt_ready",
        "attempts": 0,
        "regen_count": 0,
        "downloaded_path": "",
        "flow_error": "",
        "platform": platform_id,
        "platform_label": platform["label"],
        "generation_mode": mode,
        "orientation": orientation_id,
    }
    if source_images:
        item["source_images"] = list(source_images)
    return item


def composer_raw_prompt_to_item(index: int, body: dict, source_text: str, prompt_text: str, source_images=None) -> dict:
    return composer_item_from_ai(
        index,
        body,
        source_text,
        {
            "title_slug": source_text or f"scene_{index:03d}",
            "veo_prompt": prompt_text,
        },
        source_images=source_images,
    )


def generate_text_composer_item(index: int, body: dict) -> dict:
    system_prompt, user_prompt = build_composer_ai_request(index, body)
    raw = call_google_ai_text(system_prompt, user_prompt, composer_model(body))
    prompts = raw.get("prompts") or []
    if not prompts:
        raise RuntimeError("AI did not return any prompt items")
    source_text = str(body.get("prompt") or "").strip()
    return composer_item_from_ai(index, body, source_text, prompts[0])


def generate_image_composer_item(index: int, body: dict, image_bytes: bytes, mime_type: str, source_text: str, source_images) -> dict:
    platform = composer_platform(str(body.get("platform") or "veo_3_1"))
    orientation = composer_orientation(str(body.get("orientation") or "landscape"))
    system_prompt = (
        "You are a senior video prompt writer with image understanding. "
        "Analyze the reference image and output only one final English video-generation prompt."
    )
    user_prompt = (
        f"Target platform: {platform['target']}.\n"
        f"Aspect/orientation: {orientation}.\n"
        f"User text: {source_text or 'Use the image as the main creative reference.'}\n"
        "Create a cinematic video prompt grounded in the visible image. Include subject, setting, camera movement, "
        f"lighting, motion, mood, and this audio rule: {platform['audio_rule']} "
        f"The prompt may include the marker #{index:03d}, but no title, commentary, markdown, or JSON."
    )
    prompt_text = call_google_ai_vision(image_bytes, mime_type, system_prompt, user_prompt, composer_model(body))
    return composer_raw_prompt_to_item(index, body, source_text, prompt_text, source_images=source_images)


def generate_composer_prompts(body: dict):
    project_path = body.get("project_path") or body.get("path")
    if not project_path:
        raise ValueError("Thiếu project_path")

    mode = str(body.get("mode") or "text_to_video")
    prompt = str(body.get("prompt") or "").strip()
    images = body.get("images") or []
    if not prompt and mode == "text_to_video":
        raise ValueError("Hãy nhập prompt trước khi tạo Text To Video")
    if mode == "text_image_to_video" and not images:
        raise ValueError("Hãy chọn ít nhất một hình ảnh cho Text + Image to Video")

    project = resolve_frames_project(project_path)
    project["frames_dir"].mkdir(parents=True, exist_ok=True)

    start_index = next_prompt_index(project_path)
    generated = []
    source_images = []

    if mode == "text_image_to_video":
        upload_dir = project["work_dir"] / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        for offset, image in enumerate(images):
            filename = str(image.get("filename") or f"image_{offset:03d}.png")
            data_url = str(image.get("base64") or "")
            if not data_url:
                continue
            index = start_index + len(generated)
            mime_type, image_bytes = decode_data_url(data_url)
            safe_name = safe_upload_filename(filename, index, mime_type)
            image_path = upload_dir / f"{index:03d}_{safe_name}"
            image_path.write_bytes(image_bytes)
            source_images.append(str(image_path))
            item = generate_image_composer_item(
                index,
                body,
                image_bytes,
                mime_type,
                prompt or filename,
                [str(image_path)],
            )
            generated.append(item)
    else:
        # Batch: split input by lines, send all in one API call
        lines = [line.strip() for line in prompt.splitlines() if line.strip()]
        if len(lines) > 1:
            system_prompt = (
                "You are a senior video prompt writer. "
                "Generate Veo video prompts for EACH of the following user items. "
                "Output a JSON array with objects containing 'index', 'veo_prompt', and 'title_slug'. "
                "Keep prompts cinematic, practical, and include appropriate audio instructions."
            )
            user_lines = "\n".join(f"[{i}] {line}" for i, line in enumerate(lines))
            user_prompt = (
                f"Target platform: Google Veo 3.1 / Flow.\n"
                f"Aspect/orientation: {composer_orientation(str(body.get('orientation') or 'landscape'))}.\n"
                f"Generate one video prompt per item below. Number them starting from 0.\n\n{user_lines}"
            )
            model = composer_model(body)
            raw = call_google_ai_text(system_prompt, user_prompt, model)
            raw_prompts = raw.get("prompts") or []
            for offset, line_text in enumerate(lines):
                index = start_index + len(generated)
                raw_item = raw_prompts[offset] if offset < len(raw_prompts) else {}
                source_text = line_text
                prompt_text = normalize_prompt_marker(index, str(raw_item.get("veo_prompt") or line_text))
                platform = composer_platform(str(body.get("platform") or "veo_3_1"))
                prompt_text = append_required_audio_rule(platform, prompt_text)
                slug_seed = raw_item.get("title_slug") or source_text or prompt_text
                slug = slugify_title(str(slug_seed), f"scene_{index:03d}")
                item = {
                    "index": index,
                    "source_text": source_text,
                    "title_slug": slug,
                    "flow_title": f"{index:03d}_{slug}",
                    "veo_prompt": prompt_text,
                    "status": "prompt_ready",
                    "attempts": 0,
                    "platform": str(body.get("platform") or "veo_3_1"),
                }
                if body.get("images"):
                    item["source_images"] = source_images
                generated.append(item)
        else:
            generated.append(generate_text_composer_item(start_index, body))

    if not generated:
        raise ValueError("Không tạo được prompt nào")

    project_name = body.get("project_name") or "composer_project"
    prompts_path, all_prompts = merge_project_prompts(project_path, project_name, generated)
    return {
        "saved_to": str(prompts_path),
        "frames_dir": str(project["frames_dir"]),
        "clips_dir": str(project["clips_dir"]),
        "source_images": source_images,
        "generated": generated,
        "prompts": all_prompts,
        "status": project_status(project_path),
    }


def normalize_generated(raw_prompts, selected_by_index):
    result = []
    for item in raw_prompts:
        idx = int(item["index"])
        source = selected_by_index.get(idx, "")
        slug = re.sub(r"[^a-z0-9_]+", "_", item["title_slug"].lower()).strip("_")
        slug = re.sub(r"_+", "_", slug) or f"scene_{idx:03d}"
        prompt = item["veo_prompt"].strip().strip('"')
        expected = f"#{idx:03d},"
        if not prompt.startswith(expected):
            prompt = f"{expected} {prompt.lstrip('#0123456789, ')}"
        result.append(
            {
                "index": idx,
                "source_text": source,
                "title_slug": slug,
                "flow_title": f"{idx:03d}_{slug}",
                "veo_prompt": prompt,
                "status": "prompt_ready",
                "attempts": 0,
                "regen_count": 0,
            }
        )
    return sorted(result, key=lambda x: x["index"])


def merge_project_prompts(project_path: str, project_name: str, generated):
    if project_path:
        project = resolve_frames_project(project_path)
        prompts_path = project["prompts_path"]
        project["clips_dir"].mkdir(parents=True, exist_ok=True)
    else:
        project_dir = PROJECTS_DIR / safe_project_name(project_name)
        prompts_path = project_dir / "prompts.json"

    existing = []
    if prompts_path.exists():
        existing = read_json(prompts_path)

    by_index = {int(item["index"]): item for item in existing}
    for item in generated:
        previous = by_index.get(item["index"], {})
        merged = {**previous, **item}
        by_index[item["index"]] = merged

    final = [by_index[idx] for idx in sorted(by_index)]
    write_json(prompts_path, final)
    return prompts_path, final


def flow_queue_status(project_path: str):
    project = resolve_frames_project(project_path)
    sync_prompts_with_existing_clips(project_path)
    hold_stale_retries_for_flow_search(project_path)
    prompts = load_existing_prompts(project_path)
    counts = {
        "prompt_ready": 0,
        "submitted": 0,
        "failed": 0,
        "downloaded": 0,
        "other": 0,
    }
    for item in prompts:
        status = item.get("status") or "other"
        if status in counts:
            counts[status] += 1
        else:
            counts["other"] += 1
    now = datetime.now(timezone.utc)
    next_ready = next(
        (
            int(item["index"])
            for item in prompts
            if item.get("status") == "prompt_ready" and prompt_retry_is_due(item, now)
        ),
        None,
    )
    return {
        "prompts_path": str(project["prompts_path"]),
        "clips_dir": str(project["clips_dir"]),
        "total_prompts": len(prompts),
        "counts": counts,
        "next_ready_index": next_ready,
    }


def flow_queue_indexes(project_path: str):
    prompts = load_existing_prompts(project_path)
    by_status = {
        "prompt_ready_indexes": [],
        "submitted_indexes": [],
        "downloaded_indexes": [],
        "failed_indexes": [],
        "search_indexes": [],
    }
    for item in prompts:
        if "index" not in item:
            continue
        idx = int(item["index"])
        status = item.get("status")
        key = f"{status}_indexes"
        if key in by_status:
            by_status[key].append(idx)
        if status == "submitted" or (
            status == "prompt_ready"
            and (
                int(item.get("attempts") or 0) > 0
                or item.get("flow_error")
                or item.get("stale_submitted_at")
            )
        ):
            by_status["search_indexes"].append(idx)
    return by_status


def extension_unresolved(project_path: str):
    prompts = load_existing_prompts(project_path)
    items = []
    by_kind = {"error": [], "not_visible": [], "submitted": [], "prompt_ready": [], "failed": []}
    for item in prompts:
        if "index" not in item:
            continue
        status = item.get("status")
        if status == "downloaded":
            continue
        if status not in {"submitted", "prompt_ready", "failed"}:
            continue
        idx = int(item["index"])
        regen_count = int(item.get("regen_count") or 0)
        flow_error = item.get("flow_error") or ""
        if status == "failed":
            kind = "failed"
        elif flow_error:
            kind = "error"
        elif status == "submitted":
            kind = "submitted"
        else:
            kind = "prompt_ready"
        payload = {
            "index": idx,
            "status": status,
            "kind": kind,
            "flow_error": flow_error,
            "regen_count": regen_count,
            "regenerable": regen_count < EXTENSION_REGEN_MAX,
        }
        items.append(payload)
        by_kind.setdefault(kind, []).append(idx)
        if kind in {"submitted", "prompt_ready"}:
            by_kind["not_visible"].append(idx)

    regenerable = [item["index"] for item in items if item["regenerable"]]
    exhausted = [item["index"] for item in items if not item["regenerable"]]
    return {
        "items": sorted(items, key=lambda x: x["index"]),
        "indexes": sorted(item["index"] for item in items),
        "error_indexes": sorted(by_kind["error"]),
        "not_visible_indexes": sorted(set(by_kind["not_visible"])),
        "submitted_indexes": sorted(by_kind["submitted"]),
        "prompt_ready_indexes": sorted(by_kind["prompt_ready"]),
        "failed_indexes": sorted(by_kind["failed"]),
        "regenerable_indexes": sorted(regenerable),
        "regenerable_count": len(regenerable),
        "exhausted_indexes": sorted(exhausted),
        "total": len(items),
        "regen_max": EXTENSION_REGEN_MAX,
    }


def active_submitted_count(project_path: str, max_age_seconds: int):
    now = datetime.now(timezone.utc)
    active = 0
    stale = 0
    for item in load_existing_prompts(project_path):
        if item.get("status") != "submitted":
            continue
        submitted_at = parse_utc_datetime(item.get("submitted_at"))
        if submitted_at is None or (now - submitted_at).total_seconds() <= max_age_seconds:
            active += 1
        else:
            stale += 1
    return active, stale


def extension_add_log_unlocked(message: str) -> None:
    if not message:
        return
    log = EXTENSION_RUN.setdefault("log", [])
    log.append({"at": utc_now(), "message": message})
    del log[:-40]


def extension_snapshot(project_path: str | None = None):
    with EXTENSION_RUN_LOCK:
        snapshot = dict(EXTENSION_RUN)
        snapshot["log"] = list(EXTENSION_RUN.get("log", []))

    effective_project_path = project_path or snapshot.get("project_path")
    if effective_project_path:
        try:
            queue = flow_queue_status(effective_project_path)
            snapshot["counts"] = queue.get("counts")
            snapshot["next_ready_index"] = queue.get("next_ready_index")
            snapshot["prompts_path"] = queue.get("prompts_path")
            snapshot["clips_dir"] = queue.get("clips_dir")
            snapshot.update(flow_queue_indexes(effective_project_path))
            snapshot["unresolved"] = extension_unresolved(effective_project_path)
        except Exception as exc:
            snapshot["queue_error"] = str(exc)

    return snapshot


def set_extension_run(**updates):
    with EXTENSION_RUN_LOCK:
        EXTENSION_RUN.update(updates)
        EXTENSION_RUN["updated_at"] = utc_now()
        message = updates.get("message")
        if message:
            extension_add_log_unlocked(message)
        return extension_snapshot()


def revive_auto_failed_prompts(project_path: str):
    project = resolve_frames_project(project_path)
    prompts_path = project["prompts_path"]
    if not prompts_path.exists():
        return []
    prompts = load_existing_prompts(project_path)
    revived = []
    for item in prompts:
        if item.get("status") != "failed" or "index" not in item:
            continue
        flow_error = str(item.get("flow_error") or "")
        if not (
            flow_error.startswith("not_downloaded_after_cycle_")
            or flow_error == "final_not_generated"
            or flow_error == "final_retry_exhausted"
        ):
            continue
        item["status"] = "prompt_ready"
        item["flow_error_previous_status"] = "failed"
        item["flow_error"] = "revived_auto_failed_for_extension"
        item["flow_error_at"] = utc_now()
        item.pop("failed_at", None)
        item.pop("submitted_at", None)
        item.pop("retry_after", None)
        revived.append({"index": int(item["index"])})
    if revived:
        write_json(prompts_path, prompts)
    return revived


def start_extension_run(project_path: str, batch_count: int, flow_project_url: str | None = None):
    if flow_project_url:
        save_flow_project_url(project_path, flow_project_url)
    revived = revive_auto_failed_prompts(project_path)
    queue = flow_queue_status(project_path)
    with EXTENSION_RUN_LOCK:
        EXTENSION_RUN.update(
            {
                "status": "running",
                "phase": "waiting_for_flow_tab",
                "message": "Đã khởi động chế độ visual bằng tiện ích. Hãy mở Flow trong tab trình duyệt thường.",
                "project_path": project_path,
                "flow_project_url": flow_project_url or saved_flow_project_url(project_path) or "",
                "batch_count": max(1, int(batch_count)),
                "started_at": utc_now(),
                "updated_at": utc_now(),
                "finished_at": None,
                "stop_requested": False,
                "last_index": None,
                "submitted_in_batch": 0,
                "awaiting_user_action": False,
                "pending_action": None,
                "audio_cue": None,
                "resume_phase": None,
                "counts": queue.get("counts"),
                "log": [],
            }
        )
        extension_add_log_unlocked(EXTENSION_RUN["message"])
        if revived:
            extension_add_log_unlocked(f"Đã đưa {len(revived)} prompt từng bị auto-failed về lại lượt chạy tiện ích mới.")
        return extension_snapshot()


def stop_extension_run():
    return set_extension_run(
        status="stopped",
        phase="stopped",
        stop_requested=True,
        awaiting_user_action=False,
        pending_action=None,
        resume_phase=None,
        finished_at=utc_now(),
        message="Đã dừng chế độ visual bằng tiện ích.",
    )


def connect_extension_tab(tab_url: str, user_agent: str = ""):
    status = EXTENSION_RUN.get("status")
    previous_phase = EXTENSION_RUN.get("phase")
    previous_tab = EXTENSION_RUN.get("tab_url") or ""
    updates = {
        "connected_at": utc_now(),
        "tab_url": tab_url or "",
        "user_agent": user_agent or "",
    }
    if status == "paused" and previous_phase == "flow_error":
        updates["status"] = "running"
        updates["phase"] = "submitting"
        updates["message"] = "Tiện ích đã kết nối lại sau cảnh báo Flow; tiếp tục mà không khởi động worker trình duyệt cũ."
    if status == "running" and previous_phase == "flow_error_wait":
        updates["phase"] = EXTENSION_RUN.get("resume_phase") or "submitting"
        updates["resume_phase"] = None
        updates["message"] = "Tiện ích đã kết nối lại sau cảnh báo Flow; tiếp tục pha hiện tại."
    elif status == "running" and previous_phase == "waiting_for_flow_tab":
        updates["phase"] = "submitting"
        updates["awaiting_user_action"] = False
        updates["pending_action"] = None
        updates["message"] = "Tiện ích đã kết nối với tab Flow."
    return set_extension_run(**updates)


def _extension_project_path() -> str:
    project_path = EXTENSION_RUN.get("project_path")
    if not project_path:
        raise RuntimeError("Chế độ visual bằng tiện ích chưa được chuẩn bị. Hãy khởi động từ UI local trước.")
    return project_path


def extension_next_prompt():
    with EXTENSION_RUN_LOCK:
        if EXTENSION_RUN.get("stop_requested"):
            EXTENSION_RUN["status"] = "stopped"
            EXTENSION_RUN["phase"] = "stopped"
            EXTENSION_RUN["finished_at"] = utc_now()
            EXTENSION_RUN["updated_at"] = utc_now()
            extension_add_log_unlocked("Đã dừng chế độ visual bằng tiện ích.")
            return {"stop_requested": True, **extension_snapshot()}
        if EXTENSION_RUN.get("status") != "running":
            return {"prompt": None, "reason": "not_running", **extension_snapshot()}
        project_path = _extension_project_path()
        phase = EXTENSION_RUN.get("phase")
        if phase != "submitting":
            return {"prompt": None, "reason": "wait_phase", "phase": phase, **extension_snapshot(project_path)}

    counts = flow_queue_status(project_path).get("counts", {})
    prompts = load_existing_prompts(project_path)
    submitted_total = int(counts.get("submitted") or 0)

    now = datetime.now(timezone.utc)
    ready = next(
        (
            item
            for item in prompts
            if item.get("status") == "prompt_ready"
            and item.get("veo_prompt")
            and prompt_retry_is_due(item, now)
        ),
        None,
    )
    if not ready:
        submitted = submitted_total
        if submitted:
            set_extension_run(
                phase="awaiting_download",
                counts=counts,
                awaiting_user_action=True,
                pending_action="start_download",
                audio_cue="submit_done",
                message=f"Không còn prompt sẵn sàng; đang chờ bạn bắt đầu tải xuống thủ công cho {submitted} clip đã gửi.",
            )
            return {"prompt": None, "reason": "waiting_downloads", **extension_snapshot(project_path)}
        set_extension_run(
            status="completed",
            phase="completed",
            finished_at=utc_now(),
            counts=counts,
            awaiting_user_action=False,
            pending_action=None,
            audio_cue="all_done",
            message=(
                "Chế độ visual bằng tiện ích đã hoàn tất: không còn mục prompt_ready hoặc submitted."
                if int(counts.get("failed") or 0) == 0
                else f"Chế độ visual bằng tiện ích đã hoàn tất với {int(counts.get('failed') or 0)} prompt lỗi."
            ),
        )
        return {"prompt": None, "reason": "completed", **extension_snapshot(project_path)}

    set_extension_run(phase="submitting", counts=counts, last_index=int(ready["index"]))
    return {
        "prompt": {
            "index": int(ready["index"]),
            "flow_title": ready.get("flow_title"),
            "veo_prompt": ready.get("veo_prompt"),
        },
        **extension_snapshot(project_path),
    }


def mark_extension_submitted(project_path: str, index: int):
    prompts_path = resolve_frames_project(project_path)["prompts_path"]
    prompts = load_existing_prompts(project_path)
    now = utc_now()
    updated = None
    for item in prompts:
        if int(item.get("index", -1)) != int(index):
            continue
        if item.get("status") == "downloaded":
            updated = item
            break
        item["status"] = "submitted"
        item["submitted_at"] = now
        item["attempts"] = int(item.get("attempts", 0)) + 1
        item["submitted_by"] = "browser_extension"
        item.pop("flow_error", None)
        item.pop("flow_error_at", None)
        item.pop("flow_error_previous_status", None)
        updated = item
        break
    if updated is None:
        raise ValueError(f"Không tìm thấy chỉ mục prompt: {index}")
    write_json(prompts_path, prompts)
    with EXTENSION_RUN_LOCK:
        EXTENSION_RUN["submitted_in_batch"] = int(EXTENSION_RUN.get("submitted_in_batch") or 0) + 1
    set_extension_run(
        phase="submitting",
        last_index=int(index),
        counts=flow_queue_status(project_path).get("counts"),
        message=f"Tiện ích đã gửi prompt #{int(index):03d}.",
    )
    return {"submitted": {"index": int(index), "flow_title": updated.get("flow_title")}, **extension_snapshot(project_path)}


def mark_extension_card_retry(project_path: str, index: int, reason: str = "card_unrenderable"):
    """Mark a visible Flow error card as unresolved for the manual regen phase."""
    project = resolve_frames_project(project_path)
    prompts = load_existing_prompts(project_path)
    now = utc_now()
    result_status = None
    for item in prompts:
        if int(item.get("index", -1)) != int(index):
            continue
        if item.get("status") == "downloaded":
            result_status = "downloaded"
            break
        item["flow_error"] = reason
        item["flow_error_at"] = now
        item["flow_error_previous_status"] = item.get("status")
        item["status"] = "prompt_ready"
        item.pop("submitted_at", None)
        item.pop("retry_after", None)
        result_status = "prompt_ready"
        break
    if result_status is None:
        raise ValueError(f"Không tìm thấy chỉ mục prompt: {index}")
    write_json(project["prompts_path"], prompts)
    counts = flow_queue_status(project_path).get("counts", {})
    set_extension_run(
        phase="downloading",
        counts=counts,
        message=f"Card #{int(index):03d} bị lỗi - đã đánh dấu {result_status} cho pha tạo lại thủ công.",
    )
    return {"index": int(index), "status": result_status, **extension_snapshot(project_path)}


def mark_extension_flow_error(project_path: str, index: int | None, message: str):
    message = message or "Lỗi Flow"
    errors = [{"index": index, "type": "extension_flow_error", "message": message or "Lỗi Flow"}]
    blocked = mark_flow_error_prompts_ready(project_path, errors)
    resume_phase = EXTENSION_RUN.get("phase")
    if resume_phase not in {"submitting", "downloading", "awaiting_download", "awaiting_regen"}:
        resume_phase = "submitting"
    if message.startswith("Sai tab dự án Flow:") or message.startswith("Wrong Flow project tab:"):
        return set_extension_run(
            status="paused",
            phase="wrong_project",
            counts=flow_queue_status(project_path).get("counts"),
            message=message,
            blocked_prompts=blocked,
        )
    return set_extension_run(
        status="running",
        phase="flow_error_wait",
        resume_phase=resume_phase,
        counts=flow_queue_status(project_path).get("counts"),
        message=f"Phát hiện cảnh báo Flow; tiện ích đang chờ và sẽ tự tiếp tục: {message}",
        blocked_prompts=blocked,
    )


def complete_extension_run(project_path: str, message: str = ""):
    counts = flow_queue_status(project_path).get("counts")
    failed = flow_queue_indexes(project_path).get("failed_indexes", [])
    if not message:
        message = (
            "Chế độ visual bằng tiện ích đã hoàn tất."
            if not failed
            else "Chế độ visual bằng tiện ích đã hoàn tất. Chưa tạo được: "
            + ", ".join(f"#{int(idx):03d}" for idx in failed)
        )
    return set_extension_run(
        status="completed",
        phase="completed",
        finished_at=utc_now(),
        counts=counts,
        awaiting_user_action=False,
        pending_action=None,
        audio_cue="all_done",
        resume_phase=None,
        message=message[:500],
    )


def acknowledge_extension_audio_cue():
    return set_extension_run(audio_cue=None)


def report_extension_phase_done(project_path: str, phase: str):
    phase = (phase or "").strip().lower()
    counts = flow_queue_status(project_path).get("counts", {})
    unresolved = extension_unresolved(project_path)
    auto_mode = bool(EXTENSION_RUN.get("auto_mode", False))

    if phase == "submit":
        submitted = int(counts.get("submitted") or 0)
        ready = int(counts.get("prompt_ready") or 0)
        if submitted:
            if auto_mode:
                return set_extension_run(
                    phase="downloading",
                    counts=counts,
                    awaiting_user_action=False,
                    pending_action=None,
                    audio_cue=None,
                    message="Tất cả prompt đã gửi. Tự động chuyển sang pha tải xuống.",
                )
            else:
                return set_extension_run(
                    phase="awaiting_download",
                    counts=counts,
                    awaiting_user_action=True,
                    pending_action="start_download",
                    audio_cue="submit_done",
                    message=f"Pha gửi prompt đã hoàn tất. Đang chờ bạn bắt đầu tải xuống thủ công cho {submitted} clip đã gửi.",
                )
        if ready:
            return set_extension_run(
                phase="submitting",
                counts=counts,
                awaiting_user_action=False,
                pending_action=None,
                message=f"Pha gửi prompt tạm dừng khi vẫn còn {ready} mục prompt_ready.",
            )
        return complete_extension_run(project_path, "Chế độ visual bằng tiện ích đã hoàn tất: không còn gì để tải xuống.")

    if phase == "download":
        if unresolved["total"] <= 0:
            return complete_extension_run(project_path, "Chế độ visual bằng tiện ích đã hoàn tất: tất cả clip đã được tải xuống.")
        if auto_mode:
            if unresolved["regenerable_count"] > 0:
                regenerable = set(unresolved["regenerable_indexes"])
                exhausted = set(unresolved["exhausted_indexes"])
                project = resolve_frames_project(project_path)
                prompts = load_existing_prompts(project_path)
                now = utc_now()
                regenerated = []
                for item in prompts:
                    if item.get("status") == "downloaded" or "index" not in item:
                        continue
                    idx = int(item["index"])
                    if idx in regenerable:
                        previous_status = item.get("status")
                        item["status"] = "prompt_ready"
                        item["regen_count"] = int(item.get("regen_count") or 0) + 1
                        item["flow_error_previous_status"] = previous_status
                        item["flow_error"] = "auto_regen_requested"
                        item["flow_error_at"] = now
                        item.pop("submitted_at", None)
                        item.pop("retry_after", None)
                        regenerated.append(idx)
                    elif idx in exhausted:
                        previous_status = item.get("status")
                        item["status"] = "failed"
                        item["failed_at"] = now
                        item["flow_error"] = "regen_limit_exhausted"
                        item["flow_error_at"] = now
                        item["flow_error_previous_status"] = previous_status
                write_json(project["prompts_path"], prompts)
                new_counts = flow_queue_status(project_path).get("counts", {})
                return set_extension_run(
                    phase="submitting",
                    counts=new_counts,
                    awaiting_user_action=False,
                    pending_action=None,
                    audio_cue=None,
                    message=f"Đã tự động đưa {len(regenerated)} prompt lỗi/thiếu vào hàng đợi tạo lại.",
                )
            else:
                failed = _mark_unresolved_failed(project_path, unresolved["indexes"], "extension_completed_without_regen")
                return complete_extension_run(
                    project_path,
                    (
                        "Chế độ tiện ích hoàn tất tự động."
                        if not failed
                        else "Chế độ tiện ích hoàn tất tự động. Không thể tạo được: "
                        + ", ".join(f"#{int(idx):03d}" for idx in failed)
                    ),
                )
        else:
            pending_action = "start_regen" if unresolved["regenerable_count"] > 0 else "complete"
            message = (
                f"Pha tải xuống đã hoàn tất. Còn {unresolved['total']} prompt chưa xử lý; "
                f"{unresolved['regenerable_count']} prompt có thể tạo lại."
            )
            return set_extension_run(
                phase="awaiting_regen",
                counts=counts,
                awaiting_user_action=True,
                pending_action=pending_action,
                audio_cue="download_done",
                message=message,
            )

    raise ValueError(f"Báo cáo pha tiện ích không được hỗ trợ: {phase}")


def _mark_unresolved_failed(project_path: str, indexes, reason: str):
    if not indexes:
        return []
    project = resolve_frames_project(project_path)
    prompts = load_existing_prompts(project_path)
    index_set = {int(idx) for idx in indexes}
    now = utc_now()
    updated = []
    for item in prompts:
        if int(item.get("index", -1)) not in index_set or item.get("status") == "downloaded":
            continue
        previous_status = item.get("status")
        item["status"] = "failed"
        item["failed_at"] = now
        item["flow_error"] = reason
        item["flow_error_at"] = now
        item["flow_error_previous_status"] = previous_status
        updated.append(int(item["index"]))
    if updated:
        write_json(project["prompts_path"], prompts)
    return sorted(updated)


def run_extension_phase_action(project_path: str, action: str):
    action = (action or "").strip()
    phase = EXTENSION_RUN.get("phase")
    counts = flow_queue_status(project_path).get("counts", {})
    unresolved = extension_unresolved(project_path)

    if action == "start_download":
        if phase != "awaiting_download":
            raise RuntimeError(f"Không thể bắt đầu tải xuống từ pha {phase}.")
        return set_extension_run(
            phase="downloading",
            counts=counts,
            awaiting_user_action=False,
            pending_action=None,
            audio_cue=None,
            message="Đã bắt đầu pha tải xuống thủ công.",
        )

    if action == "start_regen":
        if phase != "awaiting_regen":
            raise RuntimeError(f"Không thể bắt đầu tạo lại từ pha {phase}.")
        regenerable = set(unresolved["regenerable_indexes"])
        exhausted = set(unresolved["exhausted_indexes"])
        project = resolve_frames_project(project_path)
        prompts = load_existing_prompts(project_path)
        now = utc_now()
        regenerated = []
        for item in prompts:
            if item.get("status") == "downloaded" or "index" not in item:
                continue
            idx = int(item["index"])
            if idx in regenerable:
                previous_status = item.get("status")
                item["status"] = "prompt_ready"
                item["regen_count"] = int(item.get("regen_count") or 0) + 1
                item["flow_error_previous_status"] = previous_status
                item["flow_error"] = "manual_regen_requested"
                item["flow_error_at"] = now
                item.pop("submitted_at", None)
                item.pop("retry_after", None)
                regenerated.append(idx)
            elif idx in exhausted:
                previous_status = item.get("status")
                item["status"] = "failed"
                item["failed_at"] = now
                item["flow_error"] = "regen_limit_exhausted"
                item["flow_error_at"] = now
                item["flow_error_previous_status"] = previous_status
        write_json(project["prompts_path"], prompts)
        counts = flow_queue_status(project_path).get("counts", {})
        return set_extension_run(
            phase="submitting",
            counts=counts,
            awaiting_user_action=False,
            pending_action=None,
            audio_cue=None,
            message=f"Đã đưa {len(regenerated)} prompt vào hàng đợi tạo lại.",
        )

    if action == "complete":
        failed = _mark_unresolved_failed(project_path, unresolved["indexes"], "extension_completed_without_regen")
        return complete_extension_run(
            project_path,
            (
                "Chế độ visual bằng tiện ích đã hoàn tất."
                if not failed
                else "Chế độ visual bằng tiện ích đã hoàn tất. Chưa tạo được: "
                + ", ".join(f"#{int(idx):03d}" for idx in failed)
            ),
        )

    raise ValueError(f"Thao tác pha tiện ích không được hỗ trợ: {action}")


def mark_flow_error_prompts_ready(project_path: str, flow_errors):
    indexed_errors = [
        item for item in flow_errors
        if item.get("index") is not None
    ]
    if not indexed_errors:
        return []

    project = resolve_frames_project(project_path)
    prompts_path = project["prompts_path"]
    prompts = load_existing_prompts(project_path)
    by_index = {int(item["index"]): item for item in prompts if "index" in item}
    updated = []
    now = utc_now()

    for error_item in indexed_errors:
        index = int(error_item["index"])
        item = by_index.get(index)
        if not item or item.get("status") == "downloaded":
            continue
        previous_status = item.get("status")
        item["status"] = "prompt_ready"
        item["flow_error"] = error_item.get("message") or "Lỗi Flow"
        item["flow_error_at"] = now
        item["flow_error_previous_status"] = previous_status
        updated.append(
            {
                "index": index,
                "flow_title": item.get("flow_title"),
                "previous_status": previous_status,
                "status": item["status"],
                "error": item["flow_error"],
            }
        )

    if updated:
        write_json(prompts_path, prompts)
    return updated


def update_downloaded_prompts(project_path: str, downloaded):
    project = resolve_frames_project(project_path)
    prompts_path = project["prompts_path"]
    prompts = load_existing_prompts(project_path)
    by_index = {int(item["index"]): item for item in prompts}
    for result in downloaded:
        if result.get("index") is None:
            continue
        item = by_index.get(int(result["index"]))
        if not item:
            continue
        if result.get("status") in {"downloaded", "skipped_existing"}:
            item["status"] = "downloaded"
            item["downloaded_at"] = utc_now()
            item["downloaded_path"] = result["path"]
        elif result.get("status") == "retried":
            item["status"] = "submitted"
            item["attempts"] = int(item.get("attempts", 0)) + 1
            item["retried_at"] = utc_now()
            item["flow_retry_clicked"] = True
        elif result.get("status") == "flow_error":
            if item.get("status") != "downloaded":
                item["status"] = "prompt_ready"
                item["flow_error"] = result.get("error") or "Lỗi Flow"
                item["flow_error_at"] = utc_now()
                item["flow_error_previous_status"] = result.get("previous_status") or "submitted"
        elif result.get("status") == "duplicate_media":
            previous_status = item.get("status")
            item["status"] = "submitted" if previous_status == "submitted" else "prompt_ready"
            item["flow_error"] = result.get("error") or "duplicate_media"
            item["flow_error_at"] = utc_now()
            item["flow_error_previous_status"] = previous_status
            item["duplicate_media_path"] = result.get("duplicate_path")
            item["duplicate_of"] = result.get("duplicate_of")
            item["duplicate_sha256"] = result.get("sha256")
            item.pop("downloaded_path", None)
            item.pop("downloaded_at", None)
    if downloaded:
        write_json(prompts_path, prompts)
    return {
        "message": f"Đã xử lý {len(downloaded)} nút tải xuống Flow đang hiển thị.",
        "downloaded": downloaded,
        **flow_queue_status(project_path),
    }


def _is_video_file(path: Path):
    if not path.exists() or path.stat().st_size < 16:
        return False
    with path.open("rb") as file:
        header = file.read(16)
    return b"ftyp" in header[:12]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_duplicate_clip_hash(clips_dir: Path, target: Path):
    if not target.exists() or not _is_video_file(target):
        return None
    try:
        target_size = target.stat().st_size
    except OSError:
        return None
    target_hash = _file_sha256(target)
    for other in sorted(clips_dir.glob("clip_*.mp4")):
        if other.resolve() == target.resolve() or not other.is_file() or not _is_video_file(other):
            continue
        try:
            if other.stat().st_size != target_size:
                continue
            if _file_sha256(other) == target_hash:
                return {"path": str(other), "sha256": target_hash}
        except Exception:
            continue
    return None


def prompt_retry_is_due(item: dict, now: datetime | None = None):
    retry_after = parse_utc_datetime(item.get("retry_after"))
    if retry_after is None:
        return True
    now = now or datetime.now(timezone.utc)
    return retry_after <= now


def sync_prompts_with_existing_clips(project_path: str):
    project = resolve_frames_project(project_path)
    prompts_path = project["prompts_path"]
    if not prompts_path.exists():
        return []
    prompts = load_existing_prompts(project_path)
    clips_dir = project["clips_dir"]
    updated = []
    now = utc_now()
    for item in prompts:
        if "index" not in item:
            continue
        idx = int(item["index"])
        target = clips_dir / f"clip_{idx:04d}.mp4"
        if target.exists() and _is_video_file(target):
            if item.get("status") != "downloaded" or item.get("downloaded_path") != str(target):
                previous_status = item.get("status")
                item["status"] = "downloaded"
                item["downloaded_at"] = item.get("downloaded_at") or now
                item["downloaded_path"] = str(target)
                item["synced_from_existing_clip"] = True
                item["synced_previous_status"] = previous_status
                item.pop("retry_after", None)
                item.pop("flow_error", None)
                item.pop("flow_error_previous_status", None)
                updated.append({"index": idx, "status": "downloaded", "previous_status": previous_status})
        elif item.get("status") == "downloaded":
            item["status"] = "prompt_ready"
            item["flow_error"] = "downloaded_file_missing"
            item["flow_error_at"] = now
            item["flow_error_previous_status"] = "downloaded"
            item.pop("downloaded_path", None)
            item.pop("downloaded_at", None)
            updated.append({"index": idx, "status": "prompt_ready", "previous_status": "downloaded"})
    if updated:
        write_json(prompts_path, prompts)
    return updated


def hold_stale_retries_for_flow_search(project_path: str):
    """Keep old submitted prompts in the download/search queue instead of resubmitting them."""
    project = resolve_frames_project(project_path)
    prompts_path = project["prompts_path"]
    if not prompts_path.exists():
        return []
    prompts = load_existing_prompts(project_path)
    updated = []
    now = utc_now()
    for item in prompts:
        if item.get("status") != "prompt_ready" or "index" not in item:
            continue
        if not item.get("stale_submitted_at") and item.get("flow_error") != "extension_submitted_timeout":
            continue
        previous_status = item.get("status")
        item["status"] = "submitted"
        item["flow_error"] = "waiting_flow_download_after_timeout"
        item["flow_error_at"] = now
        item["flow_error_previous_status"] = previous_status
        item.pop("retry_after", None)
        updated.append(
            {
                "index": int(item["index"]),
                "status": "submitted",
                "previous_status": previous_status,
            }
        )
    if updated:
        write_json(prompts_path, prompts)
    return updated


def prompt_wait_seconds(item: dict, now: datetime | None = None):
    submitted_at = parse_utc_datetime(item.get("submitted_at"))
    if submitted_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - submitted_at).total_seconds()


def _move_duplicate_clip(project: dict, target: Path, duplicate: dict, index: int):
    duplicate_dir = project["work_dir"] / "duplicate_downloads"
    duplicate_dir.mkdir(parents=True, exist_ok=True)
    duplicate_name = f"duplicate_clip_{int(index):04d}_same_media_{int(time.time())}.mp4"
    duplicate_path = duplicate_dir / duplicate_name
    target.replace(duplicate_path)
    return {
        "index": int(index),
        "status": "duplicate_media",
        "error": f"Media đã tải xuống giống hệt một clip khác: {duplicate['path']}",
        "path": str(target),
        "duplicate_path": str(duplicate_path),
        "duplicate_of": duplicate["path"],
        "sha256": duplicate["sha256"],
        "flow_title": target.stem,
    }


def _save_extension_video_payload(payload: bytes, target: Path, raw_path: Path):
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(payload)
    signature = payload[:8]
    if signature.startswith(b"\x00\x00") and b"ftyp" in payload[:16]:
        target.write_bytes(payload)
        return {"raw_path": str(raw_path), "container": "mp4_extension"}

    if signature.startswith(b"PK"):
        with zipfile.ZipFile(raw_path) as archive:
            video_names = [
                name for name in archive.namelist()
                if name.lower().endswith((".mp4", ".mov", ".webm"))
            ]
            if not video_names:
                raise RuntimeError(f"Tệp ZIP đã tải xuống không chứa tệp video: {raw_path}")
            with archive.open(video_names[0]) as source, target.open("wb") as dest:
                dest.write(source.read())
        return {"raw_path": str(raw_path), "container": "zip_extension", "inner_name": video_names[0]}

    raise RuntimeError("Payload media từ tiện ích không phải MP4 hoặc gói ZIP video.")


def download_extension_media(project_path: str, index: int, media_url: str = "", data_base64: str = ""):
    project = resolve_frames_project(project_path)
    filename = f"clip_{int(index):04d}.mp4"
    target = project["clips_dir"] / filename
    work_dir = project["downloads_dir"]
    work_dir.mkdir(parents=True, exist_ok=True)

    if target.exists() and _is_video_file(target):
        duplicate = _find_duplicate_clip_hash(project["clips_dir"], target)
        if duplicate:
            result = _move_duplicate_clip(project, target, duplicate, index)
            updated = update_downloaded_prompts(project_path, [result])
            set_extension_run(
                phase="downloading",
                counts=updated.get("counts"),
                message=f"Tiện ích đã từ chối media trùng lặp cho clip #{int(index):03d}.",
            )
            return {"downloaded": [result], **extension_snapshot(project_path)}
        result = {
            "index": int(index),
            "status": "skipped_existing",
            "path": str(target),
            "flow_title": filename[:-4],
            "media_url": media_url,
        }
        update_downloaded_prompts(project_path, [result])
        return {"downloaded": [result], **extension_snapshot(project_path)}

    if target.exists():
        bad_target = work_dir / f"bad_{target.name}_{int(time.time())}"
        target.replace(bad_target)

    raw_path = work_dir / f"extension_media_{int(index):03d}_{int(time.time())}"
    try:
        if data_base64:
            payload = base64.b64decode(data_base64)
        elif media_url:
            req = request.Request(media_url, headers={"User-Agent": "Mozilla/5.0 FlowVeoStudioExtension"})
            with request.urlopen(req, timeout=120) as response:
                payload = response.read()
        else:
            raise ValueError("Cần có media_url hoặc data_base64")
        saved = _save_extension_video_payload(payload, target, raw_path)
        duplicate = _find_duplicate_clip_hash(project["clips_dir"], target)
        if duplicate:
            result = _move_duplicate_clip(project, target, duplicate, index)
            result["media_url"] = media_url
            updated = update_downloaded_prompts(project_path, [result])
            set_extension_run(
                phase="downloading",
                counts=updated.get("counts"),
                message=f"Tiện ích đã từ chối media trùng lặp cho clip #{int(index):03d}.",
            )
            return {"downloaded": [result], **extension_snapshot(project_path)}
        result = {
            "index": int(index),
            "status": "downloaded",
            "path": str(target),
            "flow_title": filename[:-4],
            "media_url": media_url,
            **saved,
        }
    except Exception as exc:
        result = {
            "index": int(index),
            "status": "error",
            "error": str(exc),
            "path": str(target),
            "flow_title": filename[:-4],
            "media_url": media_url,
        }

    updated = update_downloaded_prompts(project_path, [result])
    set_extension_run(
        phase="downloading",
        counts=updated.get("counts"),
        message=(
            f"Tiện ích đã tải clip #{int(index):03d}."
            if result["status"] in {"downloaded", "skipped_existing"}
            else f"Tiện ích không thể tải clip #{int(index):03d}: {result.get('error')}"
        ),
    )
    return {"downloaded": [result], **extension_snapshot(project_path)}


def reset_lost_submitted(
    project_path: str,
    visible_indexes,
    reset_visible_submitted: bool = False,
    reason: str = "lost_in_flow",
):
    """Reset submitted prompts that Flow no longer shows back to prompt_ready.

    Also resets items marked downloaded whose mp4 file is missing from disk.
    """
    visible_set = {int(idx) for idx in (visible_indexes or [])}
    project = resolve_frames_project(project_path)
    prompts_path = project["prompts_path"]
    clips_dir = project["clips_dir"]
    prompts = load_existing_prompts(project_path)
    reset = []
    now = utc_now()
    for item in prompts:
        if "index" not in item:
            continue
        idx = int(item["index"])
        status = item.get("status")
        if status == "submitted" and (reset_visible_submitted or idx not in visible_set):
            item["status"] = "prompt_ready"
            item["flow_error"] = reason
            item["flow_error_at"] = now
            item["flow_error_previous_status"] = "submitted"
            reset.append({"index": idx, "previous_status": "submitted", "flow_title": item.get("flow_title")})
        elif status == "downloaded":
            target = clips_dir / f"clip_{idx:04d}.mp4"
            if not target.exists() or target.stat().st_size < 16:
                item["status"] = "prompt_ready"
                item["flow_error"] = "downloaded_file_missing"
                item["flow_error_at"] = now
                item["flow_error_previous_status"] = "downloaded"
                reset.append({"index": idx, "previous_status": "downloaded", "flow_title": item.get("flow_title")})
    if reset:
        write_json(prompts_path, prompts)
    return reset


class Handler(BaseHTTPRequestHandler):
    server_version = "FlowVeoStudio/0.1"

    def log_message(self, fmt, *args):
        safe_error_write("%s - %s\n" % (self.address_string(), fmt % args))

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        try:
            if self.path == "/api/health":
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "ai": public_prompt_settings(),
                        "project": public_project_settings(),
                        "root": str(ROOT),
                    },
                )
                return

            if self.path == "/api/settings/ai":
                json_response(self, 200, public_prompt_settings())
                return

            if self.path == "/api/settings/project":
                json_response(self, 200, public_project_settings())
                return

            if self.path == "/api/extension/status":
                json_response(self, 200, extension_snapshot())
                return

            if self.path == "/api/extension/unresolved":
                project_path = EXTENSION_RUN.get("project_path")
                if not project_path:
                    raise RuntimeError("Chế độ visual bằng tiện ích chưa được chuẩn bị. Hãy khởi động từ UI local trước.")
                json_response(self, 200, extension_unresolved(project_path))
                return

            rel = self.path.split("?", 1)[0].lstrip("/") or "index.html"
            static_path = (WEB_DIR / rel).resolve()
            if WEB_DIR.resolve() not in static_path.parents and static_path != WEB_DIR.resolve():
                text_response(self, 403, "Forbidden", "text/plain; charset=utf-8")
                return
            if not static_path.exists() or not static_path.is_file():
                text_response(self, 404, "Not found", "text/plain; charset=utf-8")
                return
            content_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
            data = static_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            traceback.print_exc()
            json_response(self, 500, {"error": str(exc)})

    def do_POST(self):
        try:
            body = self.read_body()
            if self.path == "/api/settings/ai":
                updates = {}
                if "api_key" in body:
                    api_key = str(body.get("api_key") or "").strip()
                    updates["google_ai_api_key"] = api_key if api_key else None
                if "model" in body:
                    model = str(body.get("model") or "").strip()
                    updates["google_ai_model"] = model or GOOGLE_AI_MODEL
                if "base_url" in body:
                    base_url = str(body.get("base_url") or "").strip().rstrip("/")
                    updates["google_ai_base"] = base_url or GOOGLE_AI_API_BASE
                if updates:
                    save_prompt_settings(updates)
                json_response(self, 200, {"ok": True, **public_prompt_settings()})
                return

            if self.path == "/api/settings/project":
                settings = save_project_settings_from_body(body)
                json_response(self, 200, {"ok": True, **settings})
                return

            if self.path == "/api/sentences/preview":
                project = resolve_frames_project(body["path"])
                sentences = load_sentences(body["path"])
                start = int(body.get("start_index", 0))
                count = int(body.get("count", 20))
                selected = pick_range(sentences, start, count)
                prompts = []
                try:
                    prompts = load_existing_prompts(body["path"])
                except Exception:
                    pass
                by_index = {int(p["index"]): p for p in prompts if "index" in p}
                merged_selected = []
                for item in selected:
                    idx = int(item["index"])
                    prompt_item = by_index.get(idx, {})
                    merged_selected.append({
                        "index": idx,
                        "text": item["text"],
                        "veo_prompt": prompt_item.get("veo_prompt") or "",
                        "status": prompt_item.get("status") or "no_prompt",
                        "flow_title": prompt_item.get("flow_title") or "",
                        "flow_error": prompt_item.get("flow_error") or "",
                    })
                json_response(
                    self,
                    200,
                    {
                        "total": len(sentences),
                        "items": merged_selected,
                        "frames_dir": str(project["frames_dir"]),
                        "sentences_path": str(project["sentences_path"]),
                        "prompts_path": str(project["prompts_path"]),
                        "clips_dir": str(project["clips_dir"]),
                    },
                )
                return

            if self.path == "/api/sentences/load":
                project_path = body.get("project_path") or body.get("path")
                if not project_path:
                    raise ValueError("Thiếu project_path")
                json_response(self, 200, load_script_for_editor(project_path))
                return

            if self.path == "/api/sentences/save":
                project_path = body.get("project_path") or body.get("path")
                if not project_path:
                    raise ValueError("Thiếu project_path")
                json_response(self, 200, save_script_from_editor(project_path, body.get("script_text") or ""))
                return

            if self.path == "/api/project/status":
                json_response(self, 200, project_status(body["path"]))
                return

            if self.path == "/api/project/flow-url":
                project_path = body.get("project_path") or body.get("path")
                if not project_path:
                    raise ValueError("Thiếu project_path")
                url = save_flow_project_url(project_path, body.get("flow_project_url") or body.get("url") or "")
                configured_path = configured_frames_path()
                if not configured_path or same_frames_path(configured_path, project_path):
                    save_project_settings(
                        {
                            "frames_path": str(resolve_frames_project(project_path)["frames_dir"]),
                            "flow_project_url": url,
                        }
                    )
                json_response(self, 200, {"ok": True, "flow_project_url": url, **project_status(project_path)})
                return

            if self.path == "/api/composer/generate":
                json_response(self, 200, generate_composer_prompts(body))
                return

            if self.path == "/api/vision/generate":
                body["mode"] = "text_image_to_video"
                json_response(self, 200, generate_composer_prompts(body))
                return


            if self.path == "/api/prompts/generate":
                project_path = body.get("project_path") or body.get("sentences_path") or body.get("path")
                project = resolve_frames_project(project_path)
                sentences = load_sentences(project_path)
                start = int(body.get("start_index", 0))
                count = int(body.get("count", 20))
                if body.get("missing_only"):
                    selected = pick_missing_range(sentences, project_path, start, count)
                else:
                    selected = pick_range(sentences, start, count)
                if not selected:
                    raise ValueError("Chưa chọn đoạn kịch bản nào")

                selected_context = with_neighbors(sentences, selected)
                user_prompt = build_user_prompt(selected_context, body.get("style_prompt", ""))
                system_prompt = (
                    "You create structured JSON for a production prompt pipeline. "
                    "Follow the schema exactly. Keep prompts practical for Google Veo."
                )
                model = body.get("model") or configured_google_ai_model()
                raw = call_google_ai_text(system_prompt, user_prompt, model)
                generated = normalize_generated(
                    raw.get("prompts", []),
                    {item["index"]: item["text"] for item in selected},
                )
                project_name = body.get("project_name") or public_project_settings().get("project_name") or "composer_project"
                prompts_path, all_prompts = merge_project_prompts(project_path, project_name, generated)
                status = project_status(project_path)
                json_response(
                    self,
                    200,
                    {
                        "saved_to": str(prompts_path),
                        "frames_dir": str(project["frames_dir"]),
                        "clips_dir": str(project["clips_dir"]),
                        "generated": generated,
                        "prompts": all_prompts,
                        "project_count": len(all_prompts),
                        "next_start_index": status["next_start_index"],
                        "missing_count": status["missing_count"],
                    },
                )
                return

            if self.path == "/api/flow/queue":
                project_path = body.get("project_path") or body.get("path")
                if not project_path:
                    raise ValueError("Thiếu project_path")
                json_response(self, 200, flow_queue_status(project_path))
                return

            if self.path == "/api/extension/start":
                project_path = body.get("project_path") or body.get("path")
                if not project_path:
                    raise ValueError("Thiếu project_path")
                count = max(1, int(body.get("count", EXTENSION_ROUND_BATCH)))
                raw_flow_project_url = (body.get("flow_project_url") or "").strip()
                flow_project_url = (
                    require_flow_project_url(raw_flow_project_url)
                    if raw_flow_project_url
                    else saved_flow_project_url(project_path)
                ) or ""
                json_response(self, 200, start_extension_run(project_path, count, flow_project_url))
                return

            if self.path == "/api/extension/stop":
                json_response(self, 200, stop_extension_run())
                return

            if self.path == "/api/extension/auto-mode":
                enabled = bool(body.get("auto_mode", False))
                with EXTENSION_RUN_LOCK:
                    EXTENSION_RUN["auto_mode"] = enabled
                json_response(self, 200, extension_snapshot())
                return

            if self.path == "/api/extension/connect":
                json_response(
                    self,
                    200,
                    connect_extension_tab(body.get("tab_url") or body.get("url") or "", body.get("user_agent") or ""),
                )
                return

            if self.path == "/api/extension/next-prompt":
                json_response(self, 200, extension_next_prompt())
                return

            if self.path == "/api/extension/phase-action":
                project_path = body.get("project_path") or body.get("path") or _extension_project_path()
                json_response(self, 200, run_extension_phase_action(project_path, body.get("action") or ""))
                return

            if self.path == "/api/extension/audio-cue/ack":
                json_response(self, 200, acknowledge_extension_audio_cue())
                return

            if self.path == "/api/extension/report-phase-done":
                project_path = body.get("project_path") or body.get("path") or _extension_project_path()
                json_response(self, 200, report_extension_phase_done(project_path, body.get("phase") or ""))
                return

            if self.path == "/api/extension/mark-submitted":
                project_path = body.get("project_path") or body.get("path") or _extension_project_path()
                json_response(self, 200, mark_extension_submitted(project_path, int(body["index"])))
                return

            if self.path == "/api/extension/download-media":
                project_path = body.get("project_path") or body.get("path") or _extension_project_path()
                json_response(
                    self,
                    200,
                    download_extension_media(
                        project_path,
                        int(body["index"]),
                        body.get("media_url") or "",
                        body.get("data_base64") or "",
                    ),
                )
                return

            if self.path == "/api/extension/flow-error":
                project_path = body.get("project_path") or body.get("path") or _extension_project_path()
                raw_index = body.get("index")
                index = None if raw_index is None else int(raw_index)
                json_response(self, 200, mark_extension_flow_error(project_path, index, body.get("message") or "Lỗi Flow"))
                return

            if self.path == "/api/extension/complete":
                project_path = body.get("project_path") or body.get("path") or _extension_project_path()
                json_response(self, 200, complete_extension_run(project_path, body.get("message") or ""))
                return

            if self.path == "/api/extension/mark-retry-failed":
                project_path = body.get("project_path") or body.get("path") or _extension_project_path()
                json_response(self, 200, mark_extension_card_retry(
                    project_path,
                    int(body["index"]),
                    body.get("reason") or "card_unrenderable",
                ))
                return

            if self.path == "/api/extension/log":
                msg = (body.get("message") or "").strip()
                if msg:
                    set_extension_run(message=msg[:200])
                json_response(self, 200, {"ok": True})
                return

            text_response(self, 404, "Not found", "text/plain; charset=utf-8")
        except Exception as exc:
            traceback.print_exc()
            json_response(self, 500, {"error": str(exc)})


def ensure_runtime_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)


def create_server(host: str = HOST, port: int = PORT) -> HTTPServer:
    ensure_runtime_dirs()
    return HTTPServer((host, port), Handler)


def serve_server(server: HTTPServer) -> None:
    host, port = server.server_address
    safe_console_write(f"Flow Veo Studio đang chạy tại http://{host}:{port}")
    safe_console_write(f"Thư mục dự án: {ROOT}")
    safe_console_write("Nhấn Ctrl+C để dừng.")
    server.serve_forever()


def run_server(host: str = HOST, port: int = PORT) -> None:
    server = create_server(host, port)
    serve_server(server)


def main():
    run_server()


if __name__ == "__main__":
    main()
