from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import base64
import hashlib
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import urlsplit, urlunsplit

from src.flow_automation import FLOW_URL, FlowAutomation


ROOT = Path(__file__).resolve().parent
CHANNELS_DIR = ROOT / "channels"
PROJECTS_DIR = ROOT / "projects"
WEB_DIR = ROOT / "web"
LIBRARY_ROOT = Path(os.environ.get("FLOW_VEO_LIBRARY_ROOT", r"D:\MyChannelsIRL"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("FLOW_VEO_PORT", "8765"))
FLOW = FlowAutomation(ROOT)
VISUAL_JOB_LOCK = threading.RLock()
PHASE_LABELS_RU = {
    "idle": "Простой",
    "starting": "Запуск",
    "open_flow": "Открываем Flow",
    "queue": "Проверка очереди",
    "download": "Скачиваем уже отправленные клипы",
    "submit": "Отправляем новую пачку промптов",
    "wait_after_submit": "Ждем готовности новой пачки",
    "flow_recovery": "Перезагрузка Flow после блокировки",
    "flow_error": "Flow заблокирован (unusual activity)",
    "download_timeout": "Скачивание не успевает",
    "submit_empty": "Flow не принял новую пачку",
    "browser_closed": "Окно Flow закрыто",
    "wrong_project": "Открыт не тот проект Flow",
    "completed": "Готово",
    "stopped": "Остановлено пользователем",
    "stopping": "Останавливаем",
    "error": "Ошибка",
}
PHASE_NEXT_ACTIONS_RU = {
    "flow_error": "Откройте окно Flow вручную, дождитесь, пока пропадёт «unusual activity», и снова нажмите «Сгенерировать визуал».",
    "browser_closed": "Нажмите «Открыть Flow», войдите в Google если попросит, затем снова нажмите «Сгенерировать визуал».",
    "download_timeout": "Подождите 1-2 минуты, чтобы Flow доделал клипы, и снова нажмите «Сгенерировать визуал».",
    "submit_empty": "Откройте Flow и проверьте, что промпт-бокс активен, потом нажмите «Сгенерировать визуал» снова.",
    "wrong_project": "Откройте нужный проект внутри Flow, нажмите «Зафиксировать текущий URL», затем снова «Сгенерировать визуал».",
    "completed": "Все промпты обработаны. Можно проверить папку clips_dir.",
    "stopped": "Можно снова запустить «Сгенерировать визуал», когда будете готовы.",
    "error": "Проверьте visual_worker.err.log в _flow_veo_studio и снова нажмите «Сгенерировать визуал».",
}


def normalize_flow_url(url: str) -> str:
    if not url:
        return ""
    base = str(url).strip().split("?", 1)[0].split("#", 1)[0]
    base = base.rstrip("/")
    # Flow вставляет локаль /ru/, /en/, /uk/ и т.п. между /fx/ и /tools — убираем её для сравнения.
    base = re.sub(r"(/fx)/[a-z]{2}(?=/tools)", r"\1", base)
    return base


def clean_flow_project_url(url: str | None) -> str:
    raw_url = (url or "").strip()
    if not raw_url:
        return ""
    parts = urlsplit(raw_url)
    if parts.scheme not in ("http", "https") or parts.netloc.lower() != "labs.google":
        return ""
    match = re.match(
        r"^(/fx(?:/[a-z]{2})?/tools/flow/project/[^/?#/\s]+)",
        parts.path.rstrip("/"),
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, match.group(1), "", ""))


def require_flow_project_url(url: str | None) -> str:
    raw_url = (url or "").strip()
    clean_url = clean_flow_project_url(raw_url)
    if raw_url and not clean_url:
        raise ValueError(
            "URL проекта Flow должен быть ссылкой на конкретный проект: "
            "https://labs.google/fx/ru/tools/flow/project/{id}"
        )
    return clean_url


def is_on_flow_project(flow: FlowAutomation, expected_url: str) -> bool:
    if not expected_url:
        return True
    current = flow.current_url() if hasattr(flow, "current_url") else None
    if not current:
        return False
    return normalize_flow_url(current).startswith(normalize_flow_url(expected_url))


def ensure_on_flow_project(flow: FlowAutomation, expected_url: str) -> bool:
    if not expected_url:
        return True
    if is_on_flow_project(flow, expected_url):
        return True
    try:
        flow.goto(expected_url, wait_ms=2000)
    except Exception:
        traceback.print_exc()
        return False
    return is_on_flow_project(flow, expected_url)
VISUAL_JOB = {
    "status": "idle",
    "phase": "idle",
    "phase_label": PHASE_LABELS_RU["idle"],
    "next_action": "",
    "message": "Visual automation is idle.",
    "project_path": None,
    "flow_project_url": None,
    "batch_count": 30,
    "started_at": None,
    "updated_at": None,
    "finished_at": None,
    "stop_requested": False,
    "counts": None,
    "log": [],
    "process": None,
    "status_path": None,
    "stop_path": None,
    "browser": None,
}
EXTENSION_RUN_LOCK = threading.RLock()
EXTENSION_RUN = {
    "status": "idle",
    "phase": "idle",
    "message": "Extension visual mode is idle.",
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


def load_channels():
    channels = []
    for path in sorted(CHANNELS_DIR.glob("*.json")):
        item = read_json(path)
        item["_file"] = path.name
        channels.append(item)
    return channels


def fallback_channel(channel_id: str):
    return {
        "id": channel_id,
        "name": channel_id,
        "default_model": "gpt-5.4-mini",
        "default_project_name": channel_id or "default_project",
        "prompt_batch_size": 20,
        "style_prompt": (
            "You are a professional prompt writer for Google Veo. Create English video prompts "
            "for the selected channel and adapt every scene to the meaning of the Russian script fragment. "
            "Keep visuals realistic, cinematic, varied in camera scale, and practical for Google Flow. "
            "Every prompt must start with the exact index in this format: \"#000,\". "
            "Avoid subtitles, on-screen text, music, dialogue, speech, voiceover, and talking."
        ),
        "shot_cycle": [
            "extreme close-up",
            "close-up",
            "medium shot",
            "medium-wide shot",
            "wide shot",
            "overhead shot",
        ],
    }


def load_channel(channel_id: str):
    for channel in load_channels():
        if channel.get("id") == channel_id:
            return channel
    return fallback_channel(channel_id)


def natural_sort_key(value: str):
    parts = re.split(r"(\d+)", value.lower())
    key = []
    for part in parts:
        key.append(int(part) if part.isdigit() else part)
    return key


def infer_library_channel_id(channel):
    for key in ("library_channel_id", "channel_folder", "folder"):
        if channel.get(key):
            return str(channel[key])
    channel_id = str(channel.get("id", ""))
    first = channel_id.split("_", 1)[0]
    return first or channel_id


def series_from_frames_path(path_value: str):
    if not path_value:
        return ""
    path = Path(path_value)
    frames_dir = path.parent if path.suffix.lower() == ".json" else path
    if frames_dir.name.lower() == "frames":
        return frames_dir.parent.name
    return ""


def list_library():
    configured = load_channels()
    styles_by_folder = {}
    for channel in configured:
        folder_id = infer_library_channel_id(channel)
        styles_by_folder.setdefault(folder_id.lower(), []).append(channel)

    folders = []
    if LIBRARY_ROOT.exists():
        try:
            folders = [item for item in LIBRARY_ROOT.iterdir() if item.is_dir()]
        except OSError:
            folders = []

    channels = []
    for folder in sorted(folders, key=lambda item: natural_sort_key(item.name)):
        styles = styles_by_folder.get(folder.name.lower(), [])
        series = []
        try:
            series_dirs = [item for item in folder.iterdir() if item.is_dir()]
        except OSError:
            series_dirs = []
        for series_dir in sorted(series_dirs, key=lambda item: natural_sort_key(item.name)):
            frames_dir = series_dir / "frames"
            series.append(
                {
                    "id": series_dir.name,
                    "name": series_dir.name,
                    "path": str(series_dir),
                    "frames_path": str(frames_dir),
                    "has_frames": frames_dir.is_dir(),
                    "has_sentences": (frames_dir / "sentences.json").exists(),
                }
            )

        preferred_style = styles[0] if styles else fallback_channel(folder.name)
        preferred_series = series_from_frames_path(preferred_style.get("default_project_path", ""))
        if not preferred_series:
            usable = [item for item in series if item["has_frames"]]
            preferred_series = usable[-1]["id"] if usable else (series[-1]["id"] if series else "")

        channels.append(
            {
                "id": folder.name,
                "name": folder.name,
                "path": str(folder),
                "configured": bool(styles),
                "styles": styles or [fallback_channel(folder.name)],
                "default_style_id": preferred_style.get("id", folder.name),
                "series": series,
                "default_series_id": preferred_series,
            }
        )

    folder_ids = {item["id"].lower() for item in channels}
    configured_without_folder = [
        channel
        for channel in configured
        if infer_library_channel_id(channel).lower() not in folder_ids
    ]
    return {
        "root": str(LIBRARY_ROOT),
        "channels": channels,
        "configured_without_folder": configured_without_folder,
    }


def load_sentences(path_value: str):
    project = resolve_frames_project(path_value)
    path = project["sentences_path"]
    if not path.exists():
        raise FileNotFoundError(f"Sentences file not found: {path}")
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError("sentences.json must be an array")

    normalized = []
    for item in data:
        if not isinstance(item, dict) or "index" not in item or "text" not in item:
            raise ValueError("Each sentence item must contain index and text")
        normalized.append({"index": int(item["index"]), "text": str(item["text"])})
    return normalized


def load_existing_prompts(path_value: str):
    project = resolve_frames_project(path_value)
    prompts_path = project["prompts_path"]
    if not prompts_path.exists():
        return []
    data = read_json(prompts_path)
    if not isinstance(data, list):
        raise ValueError(f"Prompts file must be an array: {prompts_path}")
    return data


def project_status(path_value: str):
    project = resolve_frames_project(path_value)
    project_state = load_project_state(path_value)
    sentences = load_sentences(path_value)
    existing = load_existing_prompts(path_value)
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


def build_user_prompt(items, channel, style_override: str):
    style = style_override.strip() if style_override.strip() else channel.get("style_prompt", "")
    shot_cycle = channel.get("shot_cycle", [])
    return (
        "Generate Google Veo prompts for these Russian script fragments.\n\n"
        "Use this channel style as the highest priority:\n"
        f"{style}\n\n"
        "Use previous/current/next text to understand the meaning. The current text is the main target.\n"
        "Do not make a literal translation. Invent a visual scene that fits the sentence and the channel.\n"
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
        f"Preferred shot cycle: {json.dumps(shot_cycle, ensure_ascii=False)}\n\n"
        "Script fragments:\n"
        f"{json.dumps(items, ensure_ascii=False, indent=2)}"
    )


def openai_extract_text(response_data):
    if response_data.get("output_text"):
        return response_data["output_text"]

    chunks = []
    for output in response_data.get("output", []):
        for content in output.get("content", []):
            if "text" in content:
                chunks.append(content["text"])
    return "".join(chunks)


def call_openai(model: str, system_prompt: str, user_prompt: str):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in Windows environment variables")

    schema = {
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

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "veo_prompt_batch",
                "strict": True,
                "schema": schema,
            }
        },
        "max_output_tokens": 8000,
    }

    req = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc

    output_text = openai_extract_text(data)
    if not output_text:
        raise RuntimeError(f"OpenAI response did not contain output text: {data}")
    return json.loads(output_text)


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
        "browser": FLOW.status(),
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


def visual_snapshot_is_active(snapshot: dict | None = None) -> bool:
    snapshot = snapshot or visual_job_snapshot()
    return bool(snapshot.get("process_running")) or snapshot.get("status") in {"running", "recovering", "stopping"}


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

    visual_snapshot = visual_job_snapshot()
    snapshot["visual_job_active"] = visual_snapshot_is_active(visual_snapshot)
    snapshot["visual_job"] = {
        "status": visual_snapshot.get("status"),
        "phase": visual_snapshot.get("phase"),
        "message": visual_snapshot.get("message"),
        "project_path": visual_snapshot.get("project_path"),
        "process_running": visual_snapshot.get("process_running", False),
    }
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
    visual_snapshot = visual_job_snapshot()
    if visual_snapshot_is_active(visual_snapshot):
        raise RuntimeError(
            "The Chrome/CDP visual worker is active. Stop it before starting the extension visual mode."
        )
    if flow_project_url:
        save_flow_project_url(project_path, flow_project_url)
    revived = revive_auto_failed_prompts(project_path)
    queue = flow_queue_status(project_path)
    with EXTENSION_RUN_LOCK:
        EXTENSION_RUN.update(
            {
                "status": "running",
                "phase": "waiting_for_flow_tab",
                "message": "Extension visual mode started. Open Flow in your normal browser tab.",
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
            extension_add_log_unlocked(f"Revived {len(revived)} auto-failed prompt(s) for another extension pass.")
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
        message="Extension visual mode stopped.",
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
        updates["message"] = "Extension reconnected after a Flow warning; continuing without starting the old browser worker."
    if status == "running" and previous_phase == "flow_error_wait":
        updates["phase"] = EXTENSION_RUN.get("resume_phase") or "submitting"
        updates["resume_phase"] = None
        updates["message"] = "Extension reconnected after a Flow warning; resuming the current phase."
    elif status == "running" and previous_phase == "waiting_for_flow_tab":
        updates["phase"] = "submitting"
        updates["awaiting_user_action"] = False
        updates["pending_action"] = None
        updates["message"] = "Extension connected to the Flow tab."
    return set_extension_run(**updates)


def _extension_project_path() -> str:
    project_path = EXTENSION_RUN.get("project_path")
    if not project_path:
        raise RuntimeError("Extension visual mode is not prepared. Start it from the local UI first.")
    return project_path


def extension_next_prompt():
    with EXTENSION_RUN_LOCK:
        if EXTENSION_RUN.get("stop_requested"):
            EXTENSION_RUN["status"] = "stopped"
            EXTENSION_RUN["phase"] = "stopped"
            EXTENSION_RUN["finished_at"] = utc_now()
            EXTENSION_RUN["updated_at"] = utc_now()
            extension_add_log_unlocked("Extension visual mode stopped.")
            return {"stop_requested": True, **extension_snapshot()}
        if EXTENSION_RUN.get("status") != "running":
            return {"prompt": None, "reason": "not_running", **extension_snapshot()}
        project_path = _extension_project_path()
        phase = EXTENSION_RUN.get("phase")
        if phase != "submitting":
            return {"prompt": None, "reason": "wait_phase", "phase": phase, **extension_snapshot(project_path)}

    visual_snapshot = visual_job_snapshot()
    if visual_snapshot_is_active(visual_snapshot):
        raise RuntimeError(
            "The Chrome/CDP visual worker is active. Extension mode is paused to avoid two visual workers."
        )

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
                message=f"No ready prompts; waiting for manual download start for {submitted} submitted clips.",
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
                "Extension visual mode completed: no prompt_ready or submitted items remain."
                if int(counts.get("failed") or 0) == 0
                else f"Extension visual mode completed with {int(counts.get('failed') or 0)} failed prompts."
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
        raise ValueError(f"Prompt index not found: {index}")
    write_json(prompts_path, prompts)
    with EXTENSION_RUN_LOCK:
        EXTENSION_RUN["submitted_in_batch"] = int(EXTENSION_RUN.get("submitted_in_batch") or 0) + 1
    set_extension_run(
        phase="submitting",
        last_index=int(index),
        counts=flow_queue_status(project_path).get("counts"),
        message=f"Extension submitted prompt #{int(index):03d}.",
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
        raise ValueError(f"Prompt index not found: {index}")
    write_json(project["prompts_path"], prompts)
    counts = flow_queue_status(project_path).get("counts", {})
    set_extension_run(
        phase="downloading",
        counts=counts,
        message=f"Card #{int(index):03d} error - marked {result_status} for the manual regen phase.",
    )
    return {"index": int(index), "status": result_status, **extension_snapshot(project_path)}


def mark_extension_flow_error(project_path: str, index: int | None, message: str):
    message = message or "Flow error"
    errors = [{"index": index, "type": "extension_flow_error", "message": message or "Flow error"}]
    blocked = mark_flow_error_prompts_ready(project_path, errors)
    resume_phase = EXTENSION_RUN.get("phase")
    if resume_phase not in {"submitting", "downloading", "awaiting_download", "awaiting_regen"}:
        resume_phase = "submitting"
    if message.startswith("Wrong Flow project tab:"):
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
        message=f"Flow warning detected; extension is waiting and will continue automatically: {message}",
        blocked_prompts=blocked,
    )


def complete_extension_run(project_path: str, message: str = ""):
    counts = flow_queue_status(project_path).get("counts")
    failed = flow_queue_indexes(project_path).get("failed_indexes", [])
    if not message:
        message = (
            "Extension visual mode completed."
            if not failed
            else "Extension visual mode completed. Not generated: "
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
    if phase == "submit":
        submitted = int(counts.get("submitted") or 0)
        ready = int(counts.get("prompt_ready") or 0)
        if submitted:
            return set_extension_run(
                phase="awaiting_download",
                counts=counts,
                awaiting_user_action=True,
                pending_action="start_download",
                audio_cue="submit_done",
                message=f"Submit phase finished. Waiting for manual download start for {submitted} submitted clips.",
            )
        if ready:
            return set_extension_run(
                phase="submitting",
                counts=counts,
                awaiting_user_action=False,
                pending_action=None,
                message=f"Submit phase paused with {ready} prompt_ready item(s) still available.",
            )
        return complete_extension_run(project_path, "Extension visual mode completed: nothing remains to download.")

    if phase == "download":
        if unresolved["total"] <= 0:
            return complete_extension_run(project_path, "Extension visual mode completed: all clips are downloaded.")
        pending_action = "start_regen" if unresolved["regenerable_count"] > 0 else "complete"
        message = (
            f"Download phase finished. {unresolved['total']} prompt(s) remain unresolved; "
            f"{unresolved['regenerable_count']} can be regenerated."
        )
        return set_extension_run(
            phase="awaiting_regen",
            counts=counts,
            awaiting_user_action=True,
            pending_action=pending_action,
            audio_cue="download_done",
            message=message,
        )

    raise ValueError(f"Unsupported extension phase report: {phase}")


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
            raise RuntimeError(f"Cannot start download from phase {phase}.")
        return set_extension_run(
            phase="downloading",
            counts=counts,
            awaiting_user_action=False,
            pending_action=None,
            audio_cue=None,
            message="Manual download phase started.",
        )

    if action == "start_regen":
        if phase != "awaiting_regen":
            raise RuntimeError(f"Cannot start regeneration from phase {phase}.")
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
            message=f"Regeneration queued for {len(regenerated)} prompt(s).",
        )

    if action == "complete":
        failed = _mark_unresolved_failed(project_path, unresolved["indexes"], "extension_completed_without_regen")
        return complete_extension_run(
            project_path,
            (
                "Extension visual mode completed."
                if not failed
                else "Extension visual mode completed. Not generated: "
                + ", ".join(f"#{int(idx):03d}" for idx in failed)
            ),
        )

    raise ValueError(f"Unsupported extension phase action: {action}")


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
        item["flow_error"] = error_item.get("message") or "Flow error"
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


def submit_ready_flow_batch(project_path: str, count: int, delay_seconds: float, flow: FlowAutomation | None = None):
    flow = flow or FLOW
    if not flow.is_open:
        raise RuntimeError("Flow browser is not open. Click Open Flow browser first.")
    project = resolve_frames_project(project_path)
    prompts_path = project["prompts_path"]
    existing_errors = flow.visible_flow_errors()
    blocked_prompts = mark_flow_error_prompts_ready(project_path, existing_errors)
    if existing_errors:
        return {
            "submitted": [],
            "blocked_prompts": blocked_prompts,
            "flow_errors": existing_errors,
            "message": (
                "Flow is showing unusual activity errors. "
                "Stopped before sending more prompts; affected submitted items were returned to prompt_ready."
            ),
            **flow_queue_status(project_path),
        }

    prompts = load_existing_prompts(project_path)
    ready = [item for item in prompts if item.get("status") == "prompt_ready" and item.get("veo_prompt")]
    selected = ready[:count]
    if not selected:
        return {
            "submitted": [],
            "blocked_prompts": [],
            "message": "No prompt_ready items found.",
            **flow_queue_status(project_path),
        }

    submitted = []
    blocked_prompts = []
    flow_errors = []
    for item in selected:
        flow.submit_prompt(item["veo_prompt"], delay_seconds=delay_seconds)
        item["attempts"] = int(item.get("attempts", 0)) + 1
        current_errors = flow.visible_flow_errors()
        matching_errors = [
            error_item for error_item in current_errors
            if error_item.get("index") is None or int(error_item["index"]) == int(item["index"])
        ]
        if matching_errors:
            item["status"] = "prompt_ready"
            item["flow_error"] = matching_errors[0].get("message") or "Flow error"
            item["flow_error_at"] = utc_now()
            item["flow_error_previous_status"] = "submitted"
            blocked_prompts.append(
                {
                    "index": item["index"],
                    "flow_title": item.get("flow_title"),
                    "previous_status": "submitted",
                    "status": item["status"],
                    "error": item["flow_error"],
                }
            )
            flow_errors = current_errors
            write_json(prompts_path, prompts)
            break

        item["status"] = "submitted"
        item["submitted_at"] = utc_now()
        item.pop("flow_error", None)
        item.pop("flow_error_at", None)
        item.pop("flow_error_previous_status", None)
        submitted.append({"index": item["index"], "flow_title": item.get("flow_title")})
        write_json(prompts_path, prompts)

    if blocked_prompts:
        message = (
            f"Submitted {len(submitted)} prompts to Flow, then stopped on Flow unusual activity."
        )
    else:
        message = f"Submitted {len(submitted)} prompts to Flow."

    return {
        "submitted": submitted,
        "blocked_prompts": blocked_prompts,
        "flow_errors": flow_errors,
        "message": message,
        **flow_queue_status(project_path),
    }


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
                item["flow_error"] = result.get("error") or "Flow error"
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
        "message": f"Processed {len(downloaded)} visible Flow download buttons.",
        "downloaded": downloaded,
        **flow_queue_status(project_path),
    }


def download_all_flow_clips(project_path: str, count: int, flow: FlowAutomation | None = None):
    flow = flow or FLOW
    project = resolve_frames_project(project_path)
    prompts = load_existing_prompts(project_path)
    flow_errors = flow.visible_flow_errors()
    blocked_prompts = mark_flow_error_prompts_ready(project_path, flow_errors)
    prompts = load_existing_prompts(project_path)
    names_by_index = {
        int(item["index"]): f"clip_{int(item['index']):04d}"
        for item in prompts
        if "index" in item and item.get("status") != "downloaded"
    }
    downloaded = flow.download_all_visible_with_scroll(
        project["clips_dir"],
        project["downloads_dir"],
        names_by_index,
        max_count=count,
    )
    result = update_downloaded_prompts(project_path, downloaded)
    result["message"] = f"Processed {len(downloaded)} Flow download candidates with auto-scroll."
    result["blocked_prompts"] = blocked_prompts + result.get("blocked_prompts", [])
    result["flow_errors"] = flow_errors
    return result


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
        "error": f"Downloaded media is identical to another clip: {duplicate['path']}",
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
                raise RuntimeError(f"Downloaded ZIP did not contain a video file: {raw_path}")
            with archive.open(video_names[0]) as source, target.open("wb") as dest:
                dest.write(source.read())
        return {"raw_path": str(raw_path), "container": "zip_extension", "inner_name": video_names[0]}

    raise RuntimeError("Extension media payload is not an MP4 or ZIP video package.")


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
                message=f"Extension rejected duplicate media for clip #{int(index):03d}.",
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
            raise ValueError("media_url or data_base64 is required")
        saved = _save_extension_video_payload(payload, target, raw_path)
        duplicate = _find_duplicate_clip_hash(project["clips_dir"], target)
        if duplicate:
            result = _move_duplicate_clip(project, target, duplicate, index)
            result["media_url"] = media_url
            updated = update_downloaded_prompts(project_path, [result])
            set_extension_run(
                phase="downloading",
                counts=updated.get("counts"),
                message=f"Extension rejected duplicate media for clip #{int(index):03d}.",
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
            f"Extension downloaded clip #{int(index):03d}."
            if result["status"] in {"downloaded", "skipped_existing"}
            else f"Extension could not download clip #{int(index):03d}: {result.get('error')}"
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


def visual_job_paths(project_path: str):
    project = resolve_frames_project(project_path)
    return {
        "status_path": project["work_dir"] / "visual_job_status.json",
        "stop_path": project["work_dir"] / "visual_job_stop.flag",
        "stdout_path": project["work_dir"] / "visual_worker.out.log",
        "stderr_path": project["work_dir"] / "visual_worker.err.log",
    }


def visual_job_payload_unlocked():
    snapshot = dict(VISUAL_JOB)
    snapshot.pop("thread", None)
    process = snapshot.pop("process", None)
    if process is not None:
        snapshot["pid"] = process.pid
        snapshot["process_running"] = process.poll() is None
    snapshot["log"] = list(VISUAL_JOB.get("log", []))
    for key in ("status_path", "stop_path"):
        if snapshot.get(key) is not None:
            snapshot[key] = str(snapshot[key])
    return snapshot


def write_visual_job_status_unlocked():
    status_path = VISUAL_JOB.get("status_path")
    if not status_path:
        return
    try:
        status_path = Path(status_path)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps(visual_job_payload_unlocked(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        traceback.print_exc()


def read_visual_job_status_file(path):
    if not path:
        return None
    try:
        path = Path(path)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        traceback.print_exc()
    return None


def visual_job_snapshot():
    with VISUAL_JOB_LOCK:
        snapshot = visual_job_payload_unlocked()
        file_snapshot = read_visual_job_status_file(VISUAL_JOB.get("status_path"))
        if file_snapshot:
            snapshot.update(file_snapshot)
            snapshot["log"] = file_snapshot.get("log", snapshot.get("log", []))
        snapshot["browser"] = snapshot.get("browser") or FLOW.status()
        return snapshot


def set_visual_job(**updates):
    with VISUAL_JOB_LOCK:
        VISUAL_JOB.update(updates)
        VISUAL_JOB["updated_at"] = utc_now()
        phase = VISUAL_JOB.get("phase") or "idle"
        VISUAL_JOB["phase_label"] = PHASE_LABELS_RU.get(phase, phase)
        status = VISUAL_JOB.get("status")
        if status in {"paused", "error", "completed", "stopped"}:
            VISUAL_JOB["next_action"] = PHASE_NEXT_ACTIONS_RU.get(phase, "")
        else:
            VISUAL_JOB["next_action"] = ""
        message = updates.get("message")
        if message:
            log = VISUAL_JOB.setdefault("log", [])
            log.append({"at": VISUAL_JOB["updated_at"], "message": message})
            del log[:-40]
        write_visual_job_status_unlocked()


def visual_job_stop_requested():
    with VISUAL_JOB_LOCK:
        stop_path = VISUAL_JOB.get("stop_path")
        if stop_path and Path(stop_path).exists():
            return True
        return bool(VISUAL_JOB.get("stop_requested"))


def sleep_visual_job(seconds: float) -> bool:
    deadline = time.time() + max(0.0, seconds)
    while time.time() < deadline:
        if visual_job_stop_requested():
            return False
        time.sleep(min(1.0, deadline - time.time()))
    return not visual_job_stop_requested()


def visual_job_has_active_thread():
    process = VISUAL_JOB.get("process")
    if process is not None:
        return process.poll() is None
    thread = VISUAL_JOB.get("thread")
    return thread is not None and thread.is_alive()


def visual_job_flow_errors(project_path: str, flow: FlowAutomation):
    if not flow.is_open and not flow.try_recover_page():
        return None, []
    try:
        errors = flow.visible_flow_errors()
    except Exception:
        traceback.print_exc()
        if not flow.try_recover_page():
            return None, []
        try:
            errors = flow.visible_flow_errors()
        except Exception:
            traceback.print_exc()
            return None, []
    blocked = mark_flow_error_prompts_ready(project_path, errors)
    return errors, blocked


def reopen_flow_for_visual_job(flow: FlowAutomation, project_path: str, flow_project_url: str | None = None) -> bool:
    if flow.is_open or flow.try_recover_page():
        if flow_project_url and not is_on_flow_project(flow, flow_project_url):
            ensure_on_flow_project(flow, flow_project_url)
        return flow.is_open
    try:
        project = resolve_frames_project(project_path)
        flow.open(project["downloads_dir"], flow_project_url or None)
    except Exception:
        traceback.print_exc()
        return False
    return flow.is_open


def recover_flow_for_visual_job(project_path: str, flow: FlowAutomation, max_seconds: int = 300, flow_project_url: str | None = None):
    deadline = time.time() + max_seconds
    attempt = 1
    last_errors = []
    while time.time() < deadline and not visual_job_stop_requested():
        if not flow.is_open and not reopen_flow_for_visual_job(flow, project_path, flow_project_url):
            return {
                "ok": False,
                "browser_closed": True,
                "flow_errors": [],
                "blocked_prompts": [],
            }

        errors, blocked = visual_job_flow_errors(project_path, flow)
        if errors is None:
            if not reopen_flow_for_visual_job(flow, project_path, flow_project_url):
                return {
                    "ok": False,
                    "browser_closed": True,
                    "flow_errors": [],
                    "blocked_prompts": [],
                }
            if not sleep_visual_job(5):
                break
            continue

        last_errors = errors
        if not errors:
            return {"ok": True, "flow_errors": [], "blocked_prompts": blocked}

        remaining = int(max(0, deadline - time.time()))
        set_visual_job(
            status="recovering",
            phase="flow_recovery",
            message=(
                f"Flow заблокирован (unusual activity). Перезагрузка №{attempt}, "
                f"осталось {remaining} c."
            ),
            counts=flow_queue_status(project_path).get("counts"),
        )
        try:
            flow.reload(wait_ms=30000)
        except Exception as exc:
            set_visual_job(
                status="recovering",
                phase="flow_recovery",
                message=f"Reload Flow упал: {exc}. Пытаемся восстановить вкладку.",
            )
            if not reopen_flow_for_visual_job(flow, project_path, flow_project_url):
                return {
                    "ok": False,
                    "browser_closed": True,
                    "flow_errors": last_errors,
                    "blocked_prompts": [],
                }
            if not sleep_visual_job(15):
                break
        attempt += 1

    errors, blocked = visual_job_flow_errors(project_path, flow)
    if errors:
        last_errors = errors
    return {"ok": False, "flow_errors": last_errors, "blocked_prompts": blocked}


def download_submitted_for_visual_job(
    project_path: str,
    batch_count: int,
    flow: FlowAutomation,
    max_seconds: int = 300,
    flow_project_url: str | None = None,
):
    deadline = time.time() + max_seconds
    attempt = 1
    last_result = None
    while time.time() < deadline and not visual_job_stop_requested():
        queue = flow_queue_status(project_path)
        submitted_left = int(queue["counts"].get("submitted", 0))
        if submitted_left <= 0:
            return {"ok": True, "result": last_result, **queue}

        if not flow.is_open and not reopen_flow_for_visual_job(flow, project_path, flow_project_url):
            return {"ok": False, "reason": "browser_closed", "result": last_result, **queue}
        if flow_project_url and not is_on_flow_project(flow, flow_project_url):
            ensure_on_flow_project(flow, flow_project_url)

        remaining = int(max(0, deadline - time.time()))
        set_visual_job(
            status="running",
            phase="download",
            message=(
                f"Скачиваем уже отправленные клипы (попытка {attempt}). "
                f"Осталось submitted: {submitted_left}."
            ),
            counts=queue.get("counts"),
        )
        try:
            result = download_all_flow_clips(project_path, max(batch_count, submitted_left), flow=flow)
        except Exception as exc:
            traceback.print_exc()
            if not reopen_flow_for_visual_job(flow, project_path, flow_project_url):
                return {
                    "ok": False,
                    "reason": "browser_closed",
                    "error": str(exc),
                    "result": last_result,
                    **flow_queue_status(project_path),
                }
            if not sleep_visual_job(5):
                break
            continue

        last_result = result
        set_visual_job(counts=result.get("counts"))

        if result.get("flow_errors") or result.get("blocked_prompts"):
            recovery = recover_flow_for_visual_job(project_path, flow, max_seconds=max(30, remaining), flow_project_url=flow_project_url)
            if recovery.get("browser_closed"):
                return {"ok": False, "reason": "browser_closed", "result": result, "recovery": recovery}
            if not recovery["ok"]:
                return {"ok": False, "reason": "flow_error", "result": result, "recovery": recovery}
            attempt += 1
            continue

        new_submitted_left = int(result.get("counts", {}).get("submitted", submitted_left))
        if new_submitted_left <= 0:
            return {"ok": True, "result": result, **flow_queue_status(project_path)}

        if new_submitted_left < submitted_left:
            wait_seconds = min(45, max(1, deadline - time.time()))
            if not sleep_visual_job(wait_seconds):
                break
            attempt += 1
            continue

        # Ничего не скачалось и Flow не показывает ошибок — значит клипов в Flow нет.
        # Сбрасываем все submitted в prompt_ready и выходим, пусть автоматизация их пере-отправит.
        try:
            visible = flow.collect_visible_indexes()
        except Exception:
            traceback.print_exc()
            visible = []
        reset_visible_submitted = attempt >= 2
        reset = reset_lost_submitted(
            project_path,
            visible,
            reset_visible_submitted=reset_visible_submitted,
            reason="stuck_in_flow_download" if reset_visible_submitted else "lost_in_flow",
        )
        if reset:
            indexes_preview = ", ".join(f"#{r['index']:03d}" for r in reset[:8])
            if len(reset) > 8:
                indexes_preview += f" и ещё {len(reset) - 8}"
            reset_reason = (
                "Flow показывает их на странице, но скачать не получается"
                if reset_visible_submitted else
                "Flow не показывает их на странице"
            )
            set_visual_job(
                status="running",
                phase="download",
                message=(
                    f"{reset_reason}: {len(reset)} ранее отправленных клипов "
                    f"({indexes_preview}). Возвращаем их в prompt_ready и пере-отправим."
                ),
                counts=flow_queue_status(project_path).get("counts"),
            )
            return {"ok": True, "result": result, **flow_queue_status(project_path)}

        # One retry is enough here: if Flow keeps old cards without media, regenerate them.
        wait_seconds = min(20, max(1, deadline - time.time()))
        if not sleep_visual_job(wait_seconds):
            break
        attempt += 1

    return {"ok": False, "reason": "timeout", "result": last_result, **flow_queue_status(project_path)}


def pause_browser_closed(project_path: str):
    set_visual_job(
        status="paused",
        phase="browser_closed",
        finished_at=utc_now(),
        message=(
            "Окно Flow закрылось во время автоматизации. "
            "Откройте Flow заново и снова нажмите «Сгенерировать визуал»."
        ),
        counts=flow_queue_status(project_path).get("counts"),
    )


def pause_wrong_project(project_path: str, expected_url: str, current_url: str):
    set_visual_job(
        status="paused",
        phase="wrong_project",
        finished_at=utc_now(),
        message=(
            f"Flow открыт не в нужном проекте.\nОжидался URL: {expected_url}\n"
            f"Сейчас открыто: {current_url or 'неизвестно'}.\n"
            "Откройте нужный проект внутри Flow, нажмите «Зафиксировать текущий URL», "
            "затем снова «Сгенерировать визуал»."
        ),
        counts=flow_queue_status(project_path).get("counts"),
    )


def run_visual_job(project_path: str, batch_count: int, flow_project_url: str | None = None):
    visual_flow = FlowAutomation(ROOT)
    flow_project_url = require_flow_project_url(flow_project_url) or None
    try:
        project = resolve_frames_project(project_path)
        target_url = flow_project_url or FLOW_URL
        set_visual_job(
            status="running",
            phase="open_flow",
            flow_project_url=flow_project_url,
            message=(
                f"Открываем проект Flow: {flow_project_url}"
                if flow_project_url else
                "Открываем Flow (URL проекта не задан — буду работать на текущей вкладке)."
            ),
            counts=flow_queue_status(project_path).get("counts"),
        )
        try:
            visual_flow.open(project["downloads_dir"], target_url)
        except Exception as exc:
            traceback.print_exc()
            set_visual_job(
                status="paused",
                phase="browser_closed",
                finished_at=utc_now(),
                message=f"Не удалось открыть Flow: {exc}",
                counts=flow_queue_status(project_path).get("counts"),
            )
            return
        if flow_project_url and not is_on_flow_project(visual_flow, flow_project_url):
            ensure_on_flow_project(visual_flow, flow_project_url)
        set_visual_job(browser=visual_flow.status())

        while not visual_job_stop_requested():
            if not visual_flow.is_open and not reopen_flow_for_visual_job(visual_flow, project_path, flow_project_url):
                pause_browser_closed(project_path)
                return
            if flow_project_url and not is_on_flow_project(visual_flow, flow_project_url):
                ensure_on_flow_project(visual_flow, flow_project_url)

            queue = flow_queue_status(project_path)
            counts = queue["counts"]
            set_visual_job(status="running", phase="queue", counts=counts)

            if counts.get("submitted", 0) > 0:
                download_result = download_submitted_for_visual_job(
                    project_path,
                    batch_count,
                    flow=visual_flow,
                    max_seconds=300,
                    flow_project_url=flow_project_url,
                )
                if download_result.get("ok"):
                    continue
                reason = download_result.get("reason")
                if reason == "browser_closed":
                    pause_browser_closed(project_path)
                    return
                if reason == "flow_error":
                    set_visual_job(
                        status="paused",
                        phase="flow_error",
                        finished_at=utc_now(),
                        message=(
                            "Flow продолжает показывать unusual activity после попыток восстановления. "
                            "Автоматизация поставлена на паузу."
                        ),
                        counts=flow_queue_status(project_path).get("counts"),
                    )
                    return
                set_visual_job(
                    status="paused",
                    phase="download_timeout",
                    finished_at=utc_now(),
                    message=(
                        "Не все отправленные клипы успели стать готовыми за 5 минут. "
                        "Автоматизация на паузе, чтобы не отправлять новую пачку слишком рано."
                    ),
                    counts=flow_queue_status(project_path).get("counts"),
                )
                return

            if counts.get("prompt_ready", 0) <= 0:
                set_visual_job(
                    status="completed",
                    phase="completed",
                    finished_at=utc_now(),
                    message="Готово: в очереди нет ни submitted, ни prompt_ready.",
                    counts=counts,
                )
                return

            errors, blocked = visual_job_flow_errors(project_path, visual_flow)
            if errors is None:
                pause_browser_closed(project_path)
                return
            if errors:
                recovery = recover_flow_for_visual_job(project_path, visual_flow, max_seconds=300, flow_project_url=flow_project_url)
                if recovery.get("browser_closed"):
                    pause_browser_closed(project_path)
                    return
                if not recovery["ok"]:
                    set_visual_job(
                        status="paused",
                        phase="flow_error",
                        finished_at=utc_now(),
                        message=(
                            "Flow unusual activity не пропал за 5 минут. "
                            "Автоматизация на паузе перед отправкой следующей пачки."
                        ),
                        counts=flow_queue_status(project_path).get("counts"),
                    )
                    return

            set_visual_job(
                status="running",
                phase="submit",
                message=f"Отправляем следующую пачку — до {batch_count} промптов.",
                counts=flow_queue_status(project_path).get("counts"),
            )
            try:
                submit_result = submit_ready_flow_batch(
                    project_path,
                    batch_count,
                    delay_seconds=2.5,
                    flow=visual_flow,
                )
            except Exception as exc:
                traceback.print_exc()
                set_visual_job(
                    status="paused",
                    phase="submit",
                    finished_at=utc_now(),
                    message=(
                        f"Отправка пачки остановлена: {exc}. "
                        "Ничего не помечено как submitted; проверьте окно Flow и запустите снова."
                    ),
                    counts=flow_queue_status(project_path).get("counts"),
                )
                return
            set_visual_job(counts=submit_result.get("counts"))
            if submit_result.get("flow_errors") or submit_result.get("blocked_prompts"):
                recovery = recover_flow_for_visual_job(project_path, visual_flow, max_seconds=300, flow_project_url=flow_project_url)
                if recovery.get("browser_closed"):
                    pause_browser_closed(project_path)
                    return
                if not recovery["ok"]:
                    set_visual_job(
                        status="paused",
                        phase="flow_error",
                        finished_at=utc_now(),
                        message=(
                            "Во время отправки появилось unusual activity. "
                            "Автоматизация на паузе после 5-минутного окна восстановления."
                        ),
                        counts=flow_queue_status(project_path).get("counts"),
                    )
                    return

            submitted_count = len(submit_result.get("submitted", []))
            if submitted_count <= 0:
                queue = flow_queue_status(project_path)
                if queue["counts"].get("submitted", 0) <= 0 and queue["counts"].get("prompt_ready", 0) <= 0:
                    set_visual_job(
                        status="completed",
                        phase="completed",
                        finished_at=utc_now(),
                        message="Готово: ничего не осталось для отправки.",
                        counts=queue.get("counts"),
                    )
                    return
                set_visual_job(
                    status="paused",
                    phase="submit_empty",
                    finished_at=utc_now(),
                    message="Flow не принял новую пачку. Автоматизация на паузе.",
                    counts=queue.get("counts"),
                )
                return

            set_visual_job(
                status="running",
                phase="wait_after_submit",
                message=f"Отправлено {submitted_count} промптов. Ждём 60 c перед скачиванием.",
                counts=submit_result.get("counts"),
            )
            if not sleep_visual_job(60):
                break

        set_visual_job(
            status="stopped",
            phase="stopped",
            finished_at=utc_now(),
            message="Автоматизация остановлена пользователем.",
            counts=flow_queue_status(project_path).get("counts"),
        )
    except Exception as exc:
        traceback.print_exc()
        if not visual_flow.is_open:
            pause_browser_closed(project_path)
        else:
            set_visual_job(
                status="error",
                phase="error",
                finished_at=utc_now(),
                message=f"Автоматизация упала: {exc}",
                counts=flow_queue_status(project_path).get("counts") if project_path else None,
            )
    finally:
        try:
            visual_flow.close(close_browser=False)
        except Exception:
            pass


def start_visual_job(project_path: str, batch_count: int, flow_project_url: str | None = None):
    paths = visual_job_paths(project_path)
    flow_project_url = require_flow_project_url(flow_project_url) or None
    if flow_project_url:
        save_flow_project_url(project_path, flow_project_url)
    with VISUAL_JOB_LOCK:
        if visual_job_has_active_thread():
            return visual_job_snapshot()
        try:
            paths["stop_path"].unlink(missing_ok=True)
        except Exception:
            pass
        for log_path in (paths["stdout_path"], paths["stderr_path"]):
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("", encoding="utf-8")
            except Exception:
                pass
        VISUAL_JOB.update(
            {
                "status": "running",
                "phase": "starting",
                "message": "Starting visual automation.",
                "project_path": project_path,
                "flow_project_url": flow_project_url,
                "batch_count": batch_count,
                "started_at": utc_now(),
                "updated_at": utc_now(),
                "finished_at": None,
                "stop_requested": False,
                "counts": None,
                "process": None,
                "status_path": paths["status_path"],
                "stop_path": paths["stop_path"],
                "browser": None,
                "log": [],
            }
        )
        write_visual_job_status_unlocked()
        stdout_handle = paths["stdout_path"].open("a", encoding="utf-8")
        stderr_handle = paths["stderr_path"].open("a", encoding="utf-8")
        argv = [
            sys.executable,
            "-u",
            str(Path(__file__).resolve()),
            "--visual-worker",
            project_path,
            str(batch_count),
            str(paths["status_path"]),
            str(paths["stop_path"]),
            flow_project_url or "",
        ]
        process = subprocess.Popen(
            argv,
            cwd=str(ROOT),
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
        stdout_handle.close()
        stderr_handle.close()
        VISUAL_JOB["process"] = process
        write_visual_job_status_unlocked()
        return visual_job_snapshot()


def stop_visual_job():
    with VISUAL_JOB_LOCK:
        if not visual_job_has_active_thread():
            return visual_job_snapshot()
        VISUAL_JOB["stop_requested"] = True
        VISUAL_JOB["status"] = "stopping"
        VISUAL_JOB["phase"] = "stopping"
        VISUAL_JOB["message"] = "Stopping visual automation after current operation."
        VISUAL_JOB["updated_at"] = utc_now()
        stop_path = VISUAL_JOB.get("stop_path")
        if stop_path:
            try:
                Path(stop_path).parent.mkdir(parents=True, exist_ok=True)
                Path(stop_path).write_text(utc_now(), encoding="utf-8")
            except Exception:
                traceback.print_exc()
        write_visual_job_status_unlocked()
        return visual_job_snapshot()


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
                        "openai_key": bool(os.environ.get("OPENAI_API_KEY")),
                        "root": str(ROOT),
                    },
                )
                return

            if self.path == "/api/channels":
                json_response(self, 200, {"channels": load_channels()})
                return

            if self.path == "/api/library":
                json_response(self, 200, list_library())
                return

            if self.path == "/api/flow/status":
                json_response(self, 200, {"browser": FLOW.status()})
                return

            if self.path == "/api/flow/visual/status":
                json_response(self, 200, visual_job_snapshot())
                return

            if self.path == "/api/extension/status":
                json_response(self, 200, extension_snapshot())
                return

            if self.path == "/api/extension/unresolved":
                project_path = EXTENSION_RUN.get("project_path")
                if not project_path:
                    raise RuntimeError("Extension visual mode is not prepared. Start it from the local UI first.")
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
            if self.path == "/api/sentences/preview":
                project = resolve_frames_project(body["path"])
                sentences = load_sentences(body["path"])
                start = int(body.get("start_index", 0))
                count = int(body.get("count", 20))
                selected = pick_range(sentences, start, count)
                json_response(
                    self,
                    200,
                    {
                        "total": len(sentences),
                        "items": selected,
                        "frames_dir": str(project["frames_dir"]),
                        "sentences_path": str(project["sentences_path"]),
                        "prompts_path": str(project["prompts_path"]),
                        "clips_dir": str(project["clips_dir"]),
                    },
                )
                return

            if self.path == "/api/project/status":
                json_response(self, 200, project_status(body["path"]))
                return

            if self.path == "/api/project/flow-url":
                project_path = body.get("project_path") or body.get("path")
                if not project_path:
                    raise ValueError("project_path is required")
                url = save_flow_project_url(project_path, body.get("flow_project_url") or body.get("url") or "")
                json_response(self, 200, {"ok": True, "flow_project_url": url, **project_status(project_path)})
                return

            if self.path == "/api/prompts/generate":
                channel = load_channel(body["channel_id"])
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
                    raise ValueError("No script fragments selected")

                selected_context = with_neighbors(sentences, selected)
                user_prompt = build_user_prompt(selected_context, channel, body.get("style_prompt", ""))
                system_prompt = (
                    "You create structured JSON for a production prompt pipeline. "
                    "Follow the schema exactly. Keep prompts practical for Google Veo."
                )
                model = body.get("model") or channel.get("default_model") or "gpt-5.4-mini"
                raw = call_openai(model, system_prompt, user_prompt)
                generated = normalize_generated(
                    raw.get("prompts", []),
                    {item["index"]: item["text"] for item in selected},
                )
                project_name = body.get("project_name") or channel.get("default_project_name") or "default_project"
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

            if self.path == "/api/channel/save":
                channel_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", body.get("id", "").strip())
                if not channel_id:
                    raise ValueError("Channel id is required")
                body["id"] = channel_id
                write_json(CHANNELS_DIR / f"{channel_id}.json", body)
                json_response(self, 200, {"ok": True})
                return

            if self.path == "/api/flow/queue":
                project_path = body.get("project_path") or body.get("path")
                if not project_path:
                    raise ValueError("project_path is required")
                json_response(self, 200, flow_queue_status(project_path))
                return

            if self.path == "/api/flow/visual/stop":
                json_response(self, 200, stop_visual_job())
                return

            if self.path == "/api/extension/start":
                project_path = body.get("project_path") or body.get("path")
                if not project_path:
                    raise ValueError("project_path is required")
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
                json_response(self, 200, mark_extension_flow_error(project_path, index, body.get("message") or "Flow error"))
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


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--visual-worker":
        if len(sys.argv) < 6:
            raise SystemExit("Usage: app.py --visual-worker <project_path> <batch_count> <status_path> <stop_path> [<flow_project_url>]")
        project_path = sys.argv[2]
        batch_count = int(sys.argv[3])
        status_path = Path(sys.argv[4])
        stop_path = Path(sys.argv[5])
        flow_project_url = sys.argv[6] if len(sys.argv) >= 7 else ""
        flow_project_url = require_flow_project_url(flow_project_url) or None
        with VISUAL_JOB_LOCK:
            VISUAL_JOB.update(
                {
                    "status": "running",
                    "phase": "starting",
                    "message": "Visual worker process started.",
                    "project_path": project_path,
                    "flow_project_url": flow_project_url,
                    "batch_count": batch_count,
                    "started_at": utc_now(),
                    "updated_at": utc_now(),
                    "finished_at": None,
                    "stop_requested": False,
                    "counts": None,
                    "process": None,
                    "status_path": status_path,
                    "stop_path": stop_path,
                    "browser": None,
                    "log": [],
                }
            )
            write_visual_job_status_unlocked()
        run_visual_job(project_path, batch_count, flow_project_url)
        return

    CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    server = HTTPServer((HOST, PORT), Handler)
    safe_console_write(f"Flow Veo Studio running at http://{HOST}:{PORT}")
    safe_console_write(f"Project root: {ROOT}")
    safe_console_write("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
