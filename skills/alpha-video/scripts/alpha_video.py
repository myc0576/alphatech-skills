#!/usr/bin/env python3
"""Dependency-free OpenAI-compatible video client for AlphaTech API."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE = "https://alphatech.net.cn"
KEYS_URL = "https://alphatech.net.cn/keys"
SUCCESS = {"completed", "complete", "succeeded", "success"}
FAILURE = {"failed", "failure", "error", "cancelled", "canceled"}


class ClientError(RuntimeError):
    def __init__(self, message: str, code: str = "client_error", ambiguous: bool = False):
        super().__init__(message)
        self.code = code
        self.ambiguous = ambiguous


def config_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for path in (Path.home() / ".config/alphatech/config.json", Path.home() / ".config/alphatech/video.json", Path(__file__).resolve().parents[1] / "config.json"):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                values.update(loaded)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            pass
    return values


def credentials() -> tuple[str, str]:
    """Resolve the AlphaTech key from wherever this machine already keeps it.

    Order: this Skill's own config.json files, then the ALPHATECH_* environment,
    then an AlphaTech relay already wired into Claude Code (CC Switch and the
    /keys page both write ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN), so an
    existing user needs no second secret. Never print the result.
    """
    values = config_values()
    key = os.environ.get("ALPHATECH_API_KEY") or str(values.get("api_key") or "")
    base = os.environ.get("ALPHATECH_BASE_URL") or str(values.get("base_url") or DEFAULT_BASE)
    if not key and "alphatech.net.cn" in os.environ.get("ANTHROPIC_BASE_URL", ""):
        key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    return base.rstrip("/"), key


def settings() -> tuple[str, str]:
    base, key = credentials()
    if not key:
        raise ClientError(
            "No AlphaTech API key found. Set ALPHATECH_API_KEY, or create one at " + KEYS_URL,
            "missing_api_key",
        )
    return base, key


def api(base: str, key: str, method: str, path: str, data: bytes | None = None, content_type: str | None = None, timeout: float = 120.0, expect_json: bool = True) -> Any:
    headers = {"Accept": "application/json" if expect_json else "video/*", "Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read(1600).decode("utf-8", "replace")
        raise ClientError(f"HTTP {exc.code} from {path}: {detail}", "api_http_error") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ClientError(f"request to {path} failed: {exc}", "request_failed", ambiguous=method == "POST") from exc
    if not expect_json:
        return raw
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError(f"invalid JSON from {path}", "invalid_response", ambiguous=method == "POST") from exc


def task_id(response: Any) -> str:
    if isinstance(response, dict):
        value = response.get("id") or response.get("task_id")
        if isinstance(value, str) and value:
            return value
    raise ClientError("create response did not contain a task ID", "invalid_submit_response")


def status(response: Any) -> str:
    if isinstance(response, dict):
        return str(response.get("status") or response.get("state") or "").strip().lower()
    return ""


def create_body(args: argparse.Namespace) -> tuple[bytes, str]:
    # AlphaTech's OpenAI-compatible video route is backed by the Sora task
    # protocol.  Its usage schema accepts only a small enum for `size`; an
    # arbitrary pixel string such as 1920x1080 or 720P is rejected before the
    # request reaches the AIStarsLab adapter.  Keep size optional because the
    # model alias already carries the requested quality and the adapter has a
    # safe 16:9 default for aspect ratio.
    seconds = float(args.seconds)
    if not seconds.is_integer():
        raise ClientError("seconds must be an integer number of seconds", "invalid_seconds")
    if seconds <= 0 or seconds > 3600:
        raise ClientError("seconds must be between 1 and 3600", "invalid_seconds")
    fields = {"model": args.model, "prompt": args.prompt, "seconds": str(int(seconds))}
    if args.size:
        allowed_sizes = {"720x1280", "1280x720", "1792x1024", "1024x1792"}
        if args.size not in allowed_sizes:
            raise ClientError(
                "size must be one of 720x1280, 1280x720, 1792x1024, or 1024x1792; omit it to use the model default",
                "invalid_size",
            )
        fields["size"] = args.size
    media = {"inputImages": [media_value(item) for item in args.image], "inputVideos": [media_value(item) for item in args.video], "inputAudios": [media_value(item) for item in args.audio]}
    media = {key: values for key, values in media.items() if values}
    if not args.reference:
        return json.dumps({**fields, **media}, ensure_ascii=False).encode(), "application/json"
    path = Path(args.reference).expanduser().resolve()
    if not path.is_file():
        raise ClientError(f"reference file not found: {path}", "invalid_reference")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ClientError("reference must be PNG, JPEG, or WebP", "invalid_reference")
    boundary = "----AlphaTech" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"input_reference\"; filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
    chunks.extend((path.read_bytes(), b"\r\n", f"--{boundary}--\r\n".encode()))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def media_value(value: str) -> str:
    if value.startswith(("https://", "http://", "data:")):
        return value
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ClientError(f"media file not found: {path}", "invalid_reference")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not (mime.startswith("image/") or mime.startswith("video/") or mime.startswith("audio/")):
        raise ClientError(f"unsupported media type: {path}", "invalid_reference")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def fetch(base: str, key: str, identifier: str) -> Any:
    return api(base, key, "GET", f"/v1/videos/{identifier}")


def wait_for(base: str, key: str, identifier: str, deadline: float, interval: float) -> Any:
    started = time.monotonic()
    pause = max(1.0, interval)
    latest: Any = {"id": identifier, "status": "submitted"}
    while True:
        latest = fetch(base, key, identifier)
        state = status(latest)
        if state in SUCCESS or state in FAILURE:
            return latest
        if time.monotonic() - started >= deadline:
            if isinstance(latest, dict):
                latest["poll_timeout"] = True
            return latest
        time.sleep(min(pause, max(0.0, deadline - (time.monotonic() - started))))
        pause = min(pause * 1.5, 20.0)


def download(base: str, key: str, identifier: str, output: str) -> str:
    payload = api(base, key, "GET", f"/v1/videos/{identifier}/content", timeout=300.0, expect_json=False)
    if not payload:
        raise ClientError("video content was empty", "empty_content")
    target = Path(output).expanduser().resolve()
    if target.suffix.lower() != ".mp4":
        target = target.with_suffix(".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return str(target)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Create and monitor AlphaTech video tasks.")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("models")
    create = sub.add_parser("create")
    create.add_argument("--model", default="64:seedance-2.0@1080p")
    create.add_argument("--prompt", required=True)
    create.add_argument(
        "--seconds",
        type=float,
        required=True,
        help="required video duration in whole seconds; choose it from the user's request",
    )
    create.add_argument(
        "--size",
        default=None,
        help="optional aspect-ratio enum: 720x1280, 1280x720, 1792x1024, or 1024x1792",
    )
    create.add_argument("--reference")
    create.add_argument("--image", action="append", default=[], help="image URL, Data URL, or local file; repeatable")
    create.add_argument("--video", action="append", default=[], help="video URL, Data URL, or local file; repeatable")
    create.add_argument("--audio", action="append", default=[], help="audio URL, Data URL, or local file; repeatable")
    create.add_argument("--wait", action=argparse.BooleanOptionalAction, default=False)
    create.add_argument("--timeout", type=float, default=1800.0)
    create.add_argument("--interval", type=float, default=4.0)
    create.add_argument("--download")
    for command in ("status", "wait"):
        item = sub.add_parser(command)
        item.add_argument("--task-id", required=True)
        item.add_argument("--timeout", type=float, default=1800.0)
        item.add_argument("--interval", type=float, default=4.0)
        item.add_argument("--download")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        base, key = settings()
        if args.command == "models":
            print(json.dumps(api(base, key, "GET", "/v1/models"), ensure_ascii=False, indent=2))
            return 0
        if args.command == "create":
            body, content_type = create_body(args)
            result = api(base, key, "POST", "/v1/videos", body, content_type)
            identifier = task_id(result)
            if args.wait:
                result = wait_for(base, key, identifier, args.timeout, args.interval)
        else:
            identifier = args.task_id
            result = fetch(base, key, identifier) if args.command == "status" else wait_for(base, key, identifier, args.timeout, args.interval)
        if args.download:
            if status(result) not in SUCCESS:
                raise ClientError("task is not complete; content was not downloaded", "task_not_complete")
            result = dict(result) if isinstance(result, dict) else {"result": result}
            result["saved_path"] = download(base, key, identifier, args.download)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if status(result) in FAILURE else 0
    except ClientError as exc:
        payload = {"ok": False, "error_code": exc.code, "message": str(exc)}
        if exc.ambiguous:
            payload["request_completion"] = "unknown"
            payload["message"] = "Submission completion is unknown; do not retry automatically. " + str(exc)
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 3 if exc.ambiguous else 1


if __name__ == "__main__":
    raise SystemExit(main())
