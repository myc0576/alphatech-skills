#!/usr/bin/env python3
"""Small, dependency-free client for the AlphaTech API Suno relay.

The submit endpoint is billable. This program never retries a submit request;
polling is the only repeated operation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_BASE = "https://alphatech.net.cn"
KEYS_URL = "https://alphatech.net.cn/keys"
SENSITIVE_QUERY = {"key", "token", "signature", "sig", "x-amz-signature", "authorization"}
URL_KEYS = {"audio_url", "video_url", "image_url", "image_large_url", "url", "download_url"}
TERMINAL_SUCCESS = {"success", "succeeded", "completed", "complete"}
TERMINAL_FAILURE = {"failure", "failed", "error", "canceled", "cancelled"}
IN_PROGRESS = {"submitted", "queueing", "queued", "processing", "in_progress", "in-progress", "pending"}


class ClientError(RuntimeError):
    def __init__(self, message: str, code: str = "client_error", ambiguous: bool = False):
        super().__init__(message)
        self.code = code
        self.ambiguous = ambiguous


def config_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    candidates = [
        Path.home() / ".config/alphatech/config.json",
        Path.home() / ".config/alphatech/suno.json",
        Path(__file__).resolve().parents[1] / "config.json",
    ]
    for path in candidates:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                values.update(loaded)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            continue
    return values


def get_config(name: str, values: dict[str, Any], default: Any = None) -> Any:
    env_name = {
        "base_url": "ALPHATECH_BASE_URL",
        "api_key": "ALPHATECH_API_KEY",
    }.get(name)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    resolved = values.get(name)
    # An AlphaTech relay already wired into [CC] (CC Switch and the /keys page
    # both write these) is a valid source, so an existing user needs no second
    # secret. Never print the result.
    if not resolved and name == "api_key" and "alphatech.net.cn" in os.environ.get("ANTHROPIC_BASE_URL", ""):
        resolved = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    return resolved if resolved else default


def redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        query = []
        for key, val in parse_qsl(parts.query, keep_blank_values=True):
            query.append((key, "[REDACTED]" if key.lower() in SENSITIVE_QUERY else val))
        netloc = parts.hostname or ""
        if parts.port:
            netloc += f":{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), ""))
    except ValueError:
        return "[REDACTED_URL]"


def sanitize(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: sanitize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, key) for v in value]
    if isinstance(value, str) and (key.lower() in URL_KEYS or value.startswith(("http://", "https://"))):
        return redact_url(value)
    return value


def request_json(base: str, api_key: str, method: str, path: str, body: Any = None, timeout: float = 45.0) -> Any:
    url = base.rstrip("/") + "/" + path.lstrip("/")
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read(1200).decode("utf-8", "replace")
        raise ClientError(f"HTTP {exc.code} from {path}: {detail}", "upstream_http_error") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ClientError(f"request to {path} failed: {exc}", "request_failed", ambiguous=method == "POST" and path.startswith("/suno/submit")) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError(f"invalid JSON response from {path}", "invalid_upstream_response") from exc


def ensure_success(response: Any, path: str) -> Any:
    if not isinstance(response, dict):
        raise ClientError(f"unexpected response from {path}", "invalid_upstream_response")
    code = str(response.get("code", "")).lower()
    # NewAPI's Suno plugin returns code="success" for both submit and fetch.
    # Some compatible deployments use numeric 200/0, while an omitted code is
    # accepted by the upstream's JSON envelope for backwards compatibility.
    if code not in {"success", "200", "0", ""}:
        raise ClientError(str(response.get("message") or response.get("error_message") or f"{path} returned code {code}"), code or "upstream_error")
    if "data" not in response:
        raise ClientError(f"{path} response is missing data", "invalid_upstream_response")
    return response["data"]


def task_from_fetch(data: Any, task_id: str) -> dict[str, Any]:
    # Native /suno/fetch returns a list of SunoDataResponse objects. Keep the
    # selected task envelope intact so status, fail_reason, timestamps and the
    # nested song/lyrics data remain available to callers.
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and str(item.get("task_id") or item.get("taskId") or "") == task_id:
                return item
        return data[0] if data and isinstance(data[0], dict) else {"task_id": task_id, "data": data}
    if isinstance(data, dict):
        return data
    return {"task_id": task_id, "data": data}


def status_of(task: dict[str, Any]) -> str:
    return str(task.get("status") or task.get("state") or "").strip().lower()


def fetch_task(base: str, api_key: str, task_id: str) -> dict[str, Any]:
    data = ensure_success(request_json(base, api_key, "POST", "/suno/fetch", {"ids": [task_id]}), "/suno/fetch")
    return task_from_fetch(data, task_id)


def collect_urls(value: Any, found: list[tuple[str, str]], key: str = "") -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, str) and v.startswith(("http://", "https://")) and k.lower() in URL_KEYS:
                found.append((k, v))
            else:
                collect_urls(v, found, k)
    elif isinstance(value, list):
        for item in value:
            collect_urls(item, found, key)


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "_", name, flags=re.UNICODE).strip("._")
    return cleaned[:120] or "suno_result"


def download_results(task: dict[str, Any], directory: str, timeout: float = 120.0) -> list[str]:
    found: list[tuple[str, str]] = []
    collect_urls(task, found)
    if not found:
        return []
    target = Path(directory).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    task_id = safe_filename(str(task.get("task_id") or "task"))
    saved: list[str] = []
    seen: set[str] = set()
    for label, url in found:
        if url in seen:
            continue
        seen.add(url)
        suffix = Path(urlsplit(url).path).suffix.lower()
        if suffix not in {".mp3", ".wav", ".m4a", ".mp4", ".jpg", ".jpeg", ".png", ".webp"}:
            suffix = {"audio_url": ".mp3", "video_url": ".mp4", "image_url": ".jpg", "image_large_url": ".jpg"}.get(label, ".bin")
        out = target / f"{task_id}_{label}{suffix}"
        try:
            with urlopen(Request(url, headers={"Accept": "*/*"}), timeout=timeout) as response:
                out.write_bytes(response.read())
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(json.dumps({"warning": f"download failed for {label}: {exc}", "url": redact_url(url)}, ensure_ascii=False), file=sys.stderr)
            continue
        saved.append(str(out))
    return saved


def poll(base: str, key: str, task_id: str, deadline: float, interval: float) -> dict[str, Any]:
    started = time.monotonic()
    current_interval = max(1.0, interval)
    last: dict[str, Any] = {"task_id": task_id, "status": "submitted"}
    while True:
        last = fetch_task(base, key, task_id)
        state = status_of(last)
        if state in TERMINAL_SUCCESS or state in TERMINAL_FAILURE:
            return last
        if time.monotonic() - started >= deadline:
            last["poll_timeout"] = True
            return last
        time.sleep(min(current_interval, max(0.0, deadline - (time.monotonic() - started))))
        current_interval = min(current_interval * 1.5, 20.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call AlphaTech API Suno without exposing credentials.")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="submit a music task")
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--title")
    generate.add_argument("--tags")
    generate.add_argument("--mv")
    generate.add_argument("--gpt-description-prompt")
    generate.add_argument("--continue-at", type=float)
    generate.add_argument("--continue-clip-id")
    generate.add_argument("--make-instrumental", action="store_true")
    generate.add_argument("--poll", action=argparse.BooleanOptionalAction, default=True)
    generate.add_argument("--timeout", type=float, default=1200.0)
    generate.add_argument("--interval", type=float, default=4.0)
    generate.add_argument("--download-dir")
    lyrics = sub.add_parser("lyrics", help="submit a lyrics task")
    lyrics.add_argument("--prompt", required=True)
    lyrics.add_argument("--poll", action=argparse.BooleanOptionalAction, default=True)
    lyrics.add_argument("--timeout", type=float, default=600.0)
    lyrics.add_argument("--interval", type=float, default=4.0)
    lyrics.add_argument("--download-dir")
    status = sub.add_parser("status", help="fetch one task without submitting")
    status.add_argument("--task-id", required=True)
    status.add_argument("--download-dir")
    sub.add_parser("models", help="non-billable GET /v1/models check")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    values = config_values()
    base = str(get_config("base_url", values, DEFAULT_BASE)).rstrip("/")
    key = get_config("api_key", values)
    if not key:
        print(json.dumps({"ok": False, "error_code": "missing_api_key", "message": "No AlphaTech API key found. Set ALPHATECH_API_KEY, or create one at " + KEYS_URL}, ensure_ascii=False))
        return 2
    try:
        if args.command == "models":
            data = request_json(base, key, "GET", "/v1/models")
            print(json.dumps(sanitize(data), ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            task = fetch_task(base, key, args.task_id)
            if args.download_dir:
                task["saved_paths"] = download_results(task, args.download_dir)
            print(json.dumps(sanitize(task), ensure_ascii=False, indent=2))
            return 0

        action = "LYRICS" if args.command == "lyrics" else "MUSIC"
        body: dict[str, Any] = {"prompt": args.prompt}
        if action == "MUSIC":
            for attr, field in (("title", "title"), ("tags", "tags"), ("mv", "mv"), ("gpt_description_prompt", "gpt_description_prompt"), ("continue_at", "continue_at"), ("continue_clip_id", "continue_clip_id")):
                value = getattr(args, attr, None)
                if value is not None:
                    body[field] = value
            body["make_instrumental"] = bool(args.make_instrumental)
        response = request_json(base, key, "POST", f"/suno/submit/{action}", body, timeout=60.0)
        task_id = ensure_success(response, f"/suno/submit/{action}")
        if not isinstance(task_id, str) or not task_id:
            raise ClientError("submit response did not contain a task ID", "invalid_submit_response")
        result: dict[str, Any] = {"task_id": task_id, "action": action, "status": "submitted"}
        if args.poll:
            result = poll(base, key, task_id, args.timeout, args.interval)
        if args.download_dir:
            result["saved_paths"] = download_results(result, args.download_dir)
        print(json.dumps(sanitize(result), ensure_ascii=False, indent=2))
        return 0 if status_of(result) not in TERMINAL_FAILURE else 1
    except ClientError as exc:
        payload = {"ok": False, "error_code": exc.code, "message": str(exc)}
        if exc.ambiguous:
            payload["request_completion"] = "unknown"
            payload["message"] = "Submit request completion is unknown; do not retry automatically. " + str(exc)
        print(json.dumps(payload, ensure_ascii=False))
        return 3 if exc.ambiguous else 1


if __name__ == "__main__":
    raise SystemExit(main())
