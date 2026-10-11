#!/usr/bin/env python3
"""Dependency-free GPT Image 2 client for AlphaTech API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE = "https://alphatech.net.cn/v1"
KEYS_URL = "https://alphatech.net.cn/keys"
MAX_IMAGES = 6
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class ClientError(RuntimeError):
    def __init__(self, message: str, code: str = "client_error", ambiguous: bool = False):
        super().__init__(message)
        self.code = code
        self.ambiguous = ambiguous


def config_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for path in (Path.home() / ".config/alphatech/config.json", Path.home() / ".config/alphatech/image2.json", Path(__file__).resolve().parents[1] / "config.json"):
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


def request_json(base: str, key: str, method: str, path: str, data: bytes | None = None, content_type: str | None = None, timeout: float = 300.0) -> Any:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(base + "/" + path.lstrip("/"), data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read(1600).decode("utf-8", "replace")
        raise ClientError(f"HTTP {exc.code}: {detail}", "api_http_error") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ClientError(f"request failed: {exc}", "request_failed", ambiguous=method == "POST") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError("AlphaTech returned invalid JSON.", "invalid_response", ambiguous=method == "POST") from exc


def multipart(fields: dict[str, str], images: list[str]) -> tuple[bytes, str]:
    boundary = "----AlphaTech" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    for item in images:
        if item.startswith("https://"):
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"\r\n\r\n{item}\r\n".encode())
            continue
        path = Path(item).expanduser().resolve()
        mime = MIME_TYPES.get(path.suffix.lower())
        if not mime or not path.is_file():
            raise ClientError(f"unsupported or missing image: {path}", "invalid_image")
        data = path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            raise ClientError(f"image exceeds 10 MiB: {path}", "image_too_large")
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
        chunks.extend((data, b"\r\n"))
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def output_paths(output: str, count: int, fmt: str) -> list[Path]:
    target = Path(output).expanduser().resolve()
    suffix = ".jpg" if fmt in {"jpg", "jpeg"} else "." + fmt
    if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        target = target.with_suffix(suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    return [target if index == 0 else target.with_name(f"{target.stem}-{index + 1}{target.suffix}") for index in range(count)]


def save_results(response: Any, output: str, fmt: str) -> list[str]:
    items = response.get("data") if isinstance(response, dict) else None
    if not isinstance(items, list) or not items:
        raise ClientError("response contains no image results", "empty_result")
    paths = output_paths(output, len(items), fmt)
    saved: list[str] = []
    for item, path in zip(items, paths):
        if not isinstance(item, dict):
            raise ClientError("invalid image result", "invalid_result")
        encoded, url = item.get("b64_json"), item.get("url")
        try:
            if isinstance(encoded, str):
                if encoded.startswith("data:"):
                    encoded = encoded.split(",", 1)[1]
                payload = base64.b64decode(encoded, validate=True)
            elif isinstance(url, str) and url.startswith("https://"):
                with urlopen(Request(url, headers={"Accept": "image/*"}), timeout=120.0) as result:
                    payload = result.read(50 * 1024 * 1024 + 1)
            else:
                raise ClientError("result has no supported image payload", "unsupported_result")
        except (ValueError, HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ClientError(f"image request completed but saving failed: {exc}", "save_failed") from exc
        if not payload or len(payload) > 50 * 1024 * 1024:
            raise ClientError("result image is empty or too large", "save_failed")
        path.write_bytes(payload)
        saved.append(str(path))
    return saved


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Generate or edit images through AlphaTech API.")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("models", help="non-billable GET /v1/models check")
    for name in ("generate", "edit"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--prompt", required=True)
        cmd.add_argument("--output", required=True)
        cmd.add_argument("--model", default="gpt-image-2")
        cmd.add_argument("--size", default="1024x1024")
        cmd.add_argument("--quality", default="auto")
        cmd.add_argument("--background")
        cmd.add_argument("--format", choices=["png", "jpeg", "jpg", "webp"], default="png")
        cmd.add_argument("--n", type=int, default=1, choices=range(1, 11), metavar="1..10")
        if name == "edit":
            cmd.add_argument("--image", action="append", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        base, key = settings()
        if args.command == "models":
            print(json.dumps(request_json(base, key, "GET", "/models"), ensure_ascii=False, indent=2))
            return 0
        fields = {"model": args.model, "prompt": args.prompt, "size": args.size, "quality": args.quality, "n": str(args.n), "output_format": "jpeg" if args.format == "jpg" else args.format}
        if args.background:
            fields["background"] = args.background
        if args.command == "generate":
            body = json.dumps({**fields, "n": args.n}, ensure_ascii=False).encode()
            response = request_json(base, key, "POST", "/images/generations", body, "application/json")
        else:
            if len(args.image) > MAX_IMAGES:
                raise ClientError("at most six reference images are supported", "too_many_images")
            body, content_type = multipart(fields, args.image)
            response = request_json(base, key, "POST", "/images/edits", body, content_type)
        saved = save_results(response, args.output, args.format)
        print(json.dumps({"ok": True, "paths": saved, "request_completed": True}, ensure_ascii=False, indent=2))
        return 0
    except ClientError as exc:
        result = {"ok": False, "error_code": exc.code, "message": str(exc), "request_completion": "unknown" if exc.ambiguous else "known"}
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 3 if exc.ambiguous else 1


if __name__ == "__main__":
    raise SystemExit(main())
