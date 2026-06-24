"""Print Codex app-server rate-limit utilization without printing credentials.

Default mode is read-only: the script asks the local Codex app-server for
`account/rateLimits/read` and exits cleanly if Codex is not authenticated.

From inside the Codex agent sandbox, direct egress to the ChatGPT usage endpoint is
blocked by default, so reading usage there requires the user to run the host-side bridge
(`codex_usage_bridge.cmd`, or this script with `--run-bridge`); a normal run then
auto-detects `AI/work/codex-usage-bridge.json` over loopback.

Optional authentication is explicit:

- `--login` runs `codex login --device-auth` in the current terminal before reading usage.
- `--login-new-window` opens a Windows Command Prompt for login, waits for the user to
  press Enter in the original terminal, then reads usage.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import queue
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CLIENT_INFO = {
    "name": "lre_codex_usage_check",
    "title": "LRE Codex Usage Check",
    "version": "0.1.0",
}
RATE_LIMIT_FIELDS = {
    "usedPercent",
    "windowDurationMins",
    "resetsAt",
    "credits",
    "rateLimitReachedType",
}
WINDOW_NAMES = ("primary", "secondary")
WORK_GITIGNORE_REQUIRED = ("*", "*/", "!.gitignore")
WORK_GITIGNORE_CONTENT = "*\n*/\n!.gitignore\n"
DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 17342
BRIDGE_STATUS_NAME = "codex-usage-bridge.json"
BRIDGE_STDERR_NAME = "codex-usage-bridge.stderr.log"


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _find_repo_root(start: Path) -> Path:
    """The VS Code project root that owns `start`: the immediate child of $DEVROOT containing it
    (%DEVROOT%\\<project>), else the nearest enclosing repo/workspace that is NOT a per-skill package.
    Every skills/<name>/ is its own git repo (its root has SKILL.md), so resolving to the nearest .git
    would wrongly land inside a skill; this resolver climbs past skills to the owning project."""
    current = Path(start).resolve()
    devroot = os.environ.get("DEVROOT")
    if devroot:
        dr = Path(devroot).resolve()
        for path in (current, *current.parents):
            if path.parent == dr:
                if not (path / "SKILL.md").is_file():
                    return path
                break  # a skill sits directly under DEVROOT; fall through to the climb
    for path in (current, *current.parents):
        if (path / "SKILL.md").is_file():
            continue  # never resolve to a per-skill package
        if (path / ".git").exists() or (path / "AGENTS.md").is_file():
            return path
    return current


def _repo_work_dir() -> Path:
    root = _find_repo_root(Path.cwd())
    if (root / "SKILL.md").is_file():  # guard: never write AI/work inside a skill package
        raise RuntimeError(f"refusing to use AI/work inside a skill package: {root}")
    return root / "AI" / "work"


def _repo_local_codex_home() -> Path:
    return _repo_work_dir() / "codex-home-agent"


def _default_bridge_url(port: int = DEFAULT_BRIDGE_PORT) -> str:
    return f"ws://{DEFAULT_BRIDGE_HOST}:{port}"


def _ensure_work_gitignore(work_dir: Path) -> None:
    """Ensure repo-local Codex state under AI/work stays untracked by default."""
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        gitignore = work_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(WORK_GITIGNORE_CONTENT, encoding="utf-8")
            return
        text = gitignore.read_text(encoding="utf-8")
        active_lines = {
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        missing = [pattern for pattern in WORK_GITIGNORE_REQUIRED if pattern not in active_lines]
        if missing:
            prefix = "" if not text or text.endswith(("\n", "\r")) else "\n"
            with gitignore.open("a", encoding="utf-8") as handle:
                handle.write(prefix)
                handle.write("\n# Protect local agent work products and credential caches.\n")
                for pattern in missing:
                    handle.write(pattern + "\n")
    except OSError as exc:
        raise RuntimeError(f"could not verify AI/work/.gitignore safety ({type(exc).__name__})") from exc


def _bridge_status_path() -> Path:
    return _repo_work_dir() / BRIDGE_STATUS_NAME


def _bridge_ready_url(app_server_url: str) -> str:
    parsed = urlparse(app_server_url)
    if parsed.scheme != "ws" or not parsed.hostname or not parsed.port:
        raise ValueError("bridge URL must be ws://host:port")
    return f"http://{parsed.hostname}:{parsed.port}/readyz"


def _is_bridge_ready(app_server_url: str, timeout_seconds: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(_bridge_ready_url(app_server_url), timeout=timeout_seconds) as response:
            return response.status == 200
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        return False


def _write_bridge_status(data: dict[str, Any]) -> None:
    work_dir = _repo_work_dir()
    _ensure_work_gitignore(work_dir)
    status = {"updated": _stamp(), **data}
    _bridge_status_path().write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _running_bridge_url() -> str | None:
    path = _bridge_status_path()
    if not path.is_file():
        return None
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if status.get("state") != "running":
        return None
    app_server_url = status.get("appServerUrl")
    if isinstance(app_server_url, str) and _is_bridge_ready(app_server_url):
        return app_server_url
    return None


def _resolve_codex() -> str | None:
    for name in ("codex", "codex.cmd", "codex.exe", "codex.ps1"):
        path = shutil.which(name)
        if path:
            return path
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "(Get-Command codex -ErrorAction SilentlyContinue).Source",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        source = result.stdout.strip().splitlines()
        return source[0] if source else None
    return None


def _codex_command(*args: str) -> list[str] | None:
    codex = _resolve_codex()
    if not codex:
        return None
    suffix = Path(codex).suffix.lower()
    if suffix == ".ps1":
        node = Path(codex).parent / "node.exe"
        script = Path(codex).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if node.is_file() and script.is_file():
            return [str(node), str(script), *args]
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            codex,
            *args,
        ]
    return [codex, *args]


def _codex_env(codex_home: Path | None) -> dict[str, str] | None:
    if codex_home is None:
        return None
    codex_home = codex_home.resolve()
    work_dir = _repo_work_dir()
    _ensure_work_gitignore(work_dir)
    temp_dir = work_dir / "codex-temp-agent"
    env = os.environ.copy()
    paths = {
        "CODEX_HOME": codex_home,
        "HOME": work_dir / "home-agent",
        "USERPROFILE": work_dir / "userprofile-agent",
        "APPDATA": work_dir / "appdata-agent",
        "LOCALAPPDATA": work_dir / "localappdata-agent",
        "TEMP": temp_dir,
        "TMP": temp_dir,
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    env.update({key: str(path) for key, path in paths.items()})
    env.pop("CODEX_SANDBOX_NETWORK_DISABLED", None)
    return env


def _reader(stream, out: "queue.Queue[str]") -> None:
    try:
        for line in stream:
            out.put(line)
    finally:
        out.put("")


def _send(proc: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if proc.stdin is None:
        raise RuntimeError("app-server stdin is unavailable")
    proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def _wait_for_response(
    lines: "queue.Queue[str]", response_id: int, timeout_seconds: float
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            return None
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == response_id:
            return message
    return None


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def _is_auth_required(response: dict[str, Any]) -> bool:
    error = response.get("error")
    text = json.dumps(error, sort_keys=True).lower() if error is not None else ""
    return "auth" in text and any(term in text for term in ("required", "login", "credential"))


def _safe_error_message(response: dict[str, Any]) -> str:
    error = response.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        details = []
        if code is not None:
            details.append(f"code={code}")
        if isinstance(message, str):
            details.append(f"message={message}")
        return " ".join(details) if details else "unknown structured error"
    if isinstance(error, str):
        return error
    return type(error).__name__


def _format_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _field_parts(value: dict[str, Any], fields: tuple[str, ...], include_null: bool = False) -> list[str]:
    parts: list[str] = []
    for key in fields:
        if key in value and (include_null or value[key] is not None):
            parts.append(f"{key}={_format_value(value[key])}")
    return parts


def _bucket_label(default_name: str, bucket: dict[str, Any]) -> str:
    label = bucket.get("limitName") or bucket.get("limitId") or default_name
    return str(label) if label else "rateLimit"


def _format_bucket(default_name: str, bucket: Any) -> list[str]:
    if not isinstance(bucket, dict):
        return []
    label = _bucket_label(default_name, bucket)
    lines: list[str] = []
    meta = _field_parts(bucket, ("planType", "rateLimitReachedType", "credits"))
    if meta:
        lines.append(f"{label}: {' '.join(meta)}")
    for window_name in WINDOW_NAMES:
        window = bucket.get(window_name)
        if isinstance(window, dict):
            parts = _field_parts(window, ("usedPercent", "windowDurationMins", "resetsAt"), include_null=True)
            if parts:
                lines.append(f"{label}.{window_name}: {' '.join(parts)}")
        elif window is not None:
            lines.append(f"{label}.{window_name}: {_format_value(window)}")
    direct = _field_parts(bucket, ("usedPercent", "windowDurationMins", "resetsAt"), include_null=True)
    if direct:
        lines.append(f"{label}: {' '.join(direct)}")
    if not lines and any(key in bucket for key in ("limitId", "limitName", *WINDOW_NAMES, *RATE_LIMIT_FIELDS)):
        lines.append(f"{label}: no populated rate-limit fields")
    return lines


def _fallback_scan(name: str, value: Any) -> list[str]:
    lines: list[str] = []
    if isinstance(value, dict):
        bucket_lines = _format_bucket(name, value)
        if bucket_lines:
            return bucket_lines
        for key, child in value.items():
            child_name = f"{name}.{key}" if name else str(key)
            lines.extend(_fallback_scan(child_name, child))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_name = f"{name}.{index}" if name else str(index)
            lines.extend(_fallback_scan(child_name, child))
    return lines


def _extract_rate_limit_lines(result: Any) -> list[str]:
    root = result.get("result") if isinstance(result, dict) and "result" in result else result
    lines: list[str] = []
    if isinstance(root, dict):
        by_id = root.get("rateLimitsByLimitId")
        if isinstance(by_id, dict) and by_id:
            for name, bucket in by_id.items():
                lines.extend(_format_bucket(str(name), bucket))
            return lines
        single = root.get("rateLimits")
        if isinstance(single, dict):
            lines.extend(_format_bucket(str(single.get("limitId") or "codex"), single))
            return lines
    lines.extend(_fallback_scan("", root))
    return lines


def _shape_lines(name: str, value: Any, depth: int = 0) -> list[str]:
    if depth > 8:
        return [f"{name}: <max-depth>"]
    if isinstance(value, dict):
        if not value:
            return [f"{name}: {{}}"]
        lines: list[str] = []
        for key, child in value.items():
            child_name = f"{name}.{key}" if name else str(key)
            lines.extend(_shape_lines(child_name, child, depth + 1))
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{name}: []"]
        lines = [f"{name}: list[{len(value)}]"]
        for index, child in enumerate(value[:5]):
            lines.extend(_shape_lines(f"{name}[{index}]", child, depth + 1))
        if len(value) > 5:
            lines.append(f"{name}: ... {len(value) - 5} more")
        return lines
    if isinstance(value, str) and not name.endswith(("limitId", "limitName", "planType", "rateLimitReachedType")):
        display = f"<str len={len(value)}>"
    else:
        display = _format_value(value)
    return [f"{name}: {display}"]


def print_response_shape(response: dict[str, Any]) -> None:
    root = response.get("result") if isinstance(response, dict) else response
    print("usage response shape:")
    for line in _shape_lines("", root):
        print(f"  {line}")


def read_rate_limits(timeout_seconds: float, codex_home: Path | None = None) -> tuple[str, dict[str, Any] | str | None]:
    command = _codex_command("app-server", "--listen", "stdio://")
    if command is None:
        return "skip", "codex executable not found on PATH"
    try:
        codex_env = _codex_env(codex_home)
    except RuntimeError as exc:
        return "skip", str(exc)
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=codex_env,
        )
    except OSError as exc:
        return "skip", f"could not start codex app-server ({type(exc).__name__})"
    assert proc.stdout is not None
    lines: "queue.Queue[str]" = queue.Queue()
    thread = threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True)
    thread.start()
    try:
        _send(
            proc,
            {
                "method": "initialize",
                "id": 1,
                "params": {"clientInfo": CLIENT_INFO},
            },
        )
        init_response = _wait_for_response(lines, 1, timeout_seconds)
        if init_response is None:
            return "skip", "codex app-server did not answer initialize before timeout"
        if init_response.get("error") is not None:
            return "skip", "codex app-server initialize returned an error"
        _send(proc, {"method": "initialized", "params": {}})
        _send(proc, {"method": "account/rateLimits/read", "id": 2})
        usage_response = _wait_for_response(lines, 2, timeout_seconds)
        if usage_response is None:
            return "skip", "codex app-server did not answer account/rateLimits/read before timeout"
        if usage_response.get("error") is not None:
            if _is_auth_required(usage_response):
                return "auth_required", usage_response
            return "skip", "codex app-server returned an error for account/rateLimits/read: " + _safe_error_message(usage_response)
        return "ok", usage_response
    except (BrokenPipeError, OSError, RuntimeError) as exc:
        return "skip", f"codex app-server request failed ({type(exc).__name__})"
    finally:
        _stop_process(proc)


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise OSError("websocket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _ws_connect(url: str, timeout_seconds: float) -> socket.socket:
    parsed = urlparse(url)
    if parsed.scheme != "ws":
        raise ValueError("only ws:// app-server URLs are supported")
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        raise ValueError("app-server URL must include host and port")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=timeout_seconds)
    sock.settimeout(timeout_seconds)
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)
        if len(response) > 65536:
            raise OSError("websocket handshake response too large")
    header_text = response.decode("iso-8859-1", errors="replace")
    if not header_text.startswith("HTTP/1.1 101") and not header_text.startswith("HTTP/1.0 101"):
        first = header_text.splitlines()[0] if header_text else "<empty>"
        raise OSError(f"websocket handshake failed: {first}")
    expected = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")
    if expected.lower() not in header_text.lower():
        raise OSError("websocket handshake missing expected accept key")
    return sock


def _ws_send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    first = 0x80 | opcode
    length = len(payload)
    header = bytearray([first])
    if length < 126:
        header.append(0x80 | length)
    elif length <= 65535:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    mask = secrets.token_bytes(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _ws_send_json(sock: socket.socket, message: dict[str, Any]) -> None:
    _ws_send_frame(sock, 0x1, json.dumps(message, separators=(",", ":")).encode("utf-8"))


def _ws_read_text(sock: socket.socket) -> str | None:
    while True:
        first, second = _read_exact(sock, 2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _read_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _read_exact(sock, 8))[0]
        mask = _read_exact(sock, 4) if masked else b""
        payload = _read_exact(sock, length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            return None
        if opcode == 0x9:
            _ws_send_frame(sock, 0xA, payload)
            continue
        if opcode == 0x1:
            return payload.decode("utf-8", errors="replace")


def _ws_wait_for_response(sock: socket.socket, response_id: int, timeout_seconds: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        text = _ws_read_text(sock)
        if text is None:
            return None
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            continue
        if message.get("id") == response_id:
            return message
    return None


def read_rate_limits_ws(url: str, timeout_seconds: float) -> tuple[str, dict[str, Any] | str | None]:
    try:
        with _ws_connect(url, timeout_seconds) as sock:
            _ws_send_json(sock, {"method": "initialize", "id": 1, "params": {"clientInfo": CLIENT_INFO}})
            init_response = _ws_wait_for_response(sock, 1, timeout_seconds)
            if init_response is None:
                return "skip", "websocket app-server did not answer initialize before timeout"
            if init_response.get("error") is not None:
                return "skip", "websocket app-server initialize returned an error: " + _safe_error_message(init_response)
            _ws_send_json(sock, {"method": "initialized", "params": {}})
            _ws_send_json(sock, {"method": "account/rateLimits/read", "id": 2})
            usage_response = _ws_wait_for_response(sock, 2, timeout_seconds)
            if usage_response is None:
                return "skip", "websocket app-server did not answer account/rateLimits/read before timeout"
            if usage_response.get("error") is not None:
                if _is_auth_required(usage_response):
                    return "auth_required", usage_response
                return "skip", "websocket app-server returned an error for account/rateLimits/read: " + _safe_error_message(usage_response)
            return "ok", usage_response
    except (OSError, ValueError, TimeoutError) as exc:
        return "skip", f"websocket app-server request failed ({type(exc).__name__}: {exc})"


def _wait_for_any_key() -> None:
    if os.name == "nt":
        try:
            import msvcrt

            msvcrt.getwch()
            return
        except OSError:
            pass
    input()


def _stop_child(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def ensure_login_if_needed(codex_home: Path, timeout_seconds: float) -> bool:
    """Confirm repo-local Codex auth, running device-code login only when needed."""
    print("usage bridge: checking repo-local Codex authentication...")
    status, payload = read_rate_limits(min(timeout_seconds, 30.0), codex_home)
    if status == "ok":
        print("usage bridge: repo-local Codex authentication is ready.")
        return True
    if status != "auth_required":
        print(f"usage bridge: could not verify Codex authentication before starting bridge: {payload}")
        return False
    print("usage bridge: repo-local Codex authentication is required before starting bridge.")
    if not run_login(False, codex_home):
        print("usage bridge: login did not complete; bridge was not started.")
        return False
    status, payload = read_rate_limits(min(timeout_seconds, 30.0), codex_home)
    if status == "ok":
        print("usage bridge: repo-local Codex login verified.")
        return True
    if status == "auth_required":
        print("usage bridge: Codex authentication is still unavailable after login; bridge was not started.")
    else:
        print(f"usage bridge: could not verify Codex usage after login: {payload}")
    return False


def run_bridge(
    port: int,
    codex_home: Path | None = None,
    startup_timeout_seconds: float = 30.0,
    login_if_needed: bool = False,
) -> int:
    codex_home = codex_home or _repo_local_codex_home()
    app_server_url = _default_bridge_url(port)
    ready_url = _bridge_ready_url(app_server_url)
    command = _codex_command("app-server", "--listen", app_server_url)
    if command is None:
        print("usage bridge: codex executable not found on PATH")
        return 0
    if login_if_needed and not ensure_login_if_needed(codex_home, startup_timeout_seconds):
        _write_bridge_status(
            {
                "state": "error",
                "appServerUrl": app_server_url,
                "readyUrl": ready_url,
                "codexHome": str(codex_home.resolve()),
                "error": "login preflight failed",
            }
        )
        return 0
    try:
        codex_env = _codex_env(codex_home)
    except RuntimeError as exc:
        print(f"usage bridge: {exc}")
        return 0
    log_path = _repo_work_dir() / BRIDGE_STDERR_NAME
    _write_bridge_status(
        {
            "state": "starting",
            "appServerUrl": app_server_url,
            "readyUrl": ready_url,
            "codexHome": str(codex_home.resolve()),
            "message": "Starting Codex usage bridge.",
        }
    )
    with log_path.open("a", encoding="utf-8") as stderr:
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=codex_env,
            )
        except OSError as exc:
            _write_bridge_status(
                {
                    "state": "error",
                    "appServerUrl": app_server_url,
                    "readyUrl": ready_url,
                    "codexHome": str(codex_home.resolve()),
                    "error": f"could not start codex app-server ({type(exc).__name__})",
                }
            )
            print(f"usage bridge: could not start codex app-server ({type(exc).__name__})")
            return 0
        deadline = time.monotonic() + startup_timeout_seconds
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                _write_bridge_status(
                    {
                        "state": "error",
                        "appServerUrl": app_server_url,
                        "readyUrl": ready_url,
                        "codexHome": str(codex_home.resolve()),
                        "pid": proc.pid,
                        "error": f"codex app-server exited during startup with code {proc.returncode}",
                    }
                )
                print(f"usage bridge: codex app-server exited during startup with code {proc.returncode}")
                print(f"usage bridge: see {log_path}")
                return 0
            if _is_bridge_ready(app_server_url):
                break
            time.sleep(0.25)
        else:
            _write_bridge_status(
                {
                    "state": "error",
                    "appServerUrl": app_server_url,
                    "readyUrl": ready_url,
                    "codexHome": str(codex_home.resolve()),
                    "pid": proc.pid,
                    "error": "timed out waiting for app-server readyz",
                }
            )
            print(f"usage bridge: timed out waiting for {ready_url}")
            _stop_child(proc)
            return 0

        _write_bridge_status(
            {
                "state": "running",
                "appServerUrl": app_server_url,
                "readyUrl": ready_url,
                "codexHome": str(codex_home.resolve()),
                "pid": proc.pid,
                "started": _stamp(),
                "message": "Bridge running. Minimize this window. Press any key in this window to stop.",
            }
        )
        print("Codex usage bridge is running.")
        print(f"  app-server: {app_server_url}")
        print(f"  readyz:     {ready_url}")
        print(f"  status:     {_bridge_status_path()}")
        print(f"  log:        {log_path}")
        print()
        print("Minimize this window while agents need usage checks.")
        print("Press any key in this window to stop the bridge.")
        try:
            _wait_for_any_key()
        except KeyboardInterrupt:
            pass
        finally:
            _stop_child(proc)
            _write_bridge_status(
                {
                    "state": "stopped",
                    "appServerUrl": app_server_url,
                    "readyUrl": ready_url,
                    "codexHome": str(codex_home.resolve()),
                    "pid": proc.pid,
                    "stopped": _stamp(),
                    "message": "Bridge stopped by user.",
                }
            )
        print("Codex usage bridge stopped.")
    return 0


def _write_login_cmd(command: list[str], codex_home: Path) -> Path:
    work_dir = _repo_work_dir()
    env = _codex_env(codex_home) or {}
    script = work_dir / "codex-login-repo-local.cmd"
    lines = ["@echo off"]
    for key in ("CODEX_HOME", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        lines.append(f"set {key}={env[key]}")
    lines.append(subprocess.list2cmdline(command))
    lines.append("echo.")
    lines.append("echo Login command finished. You may close this window.")
    lines.append("pause")
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return script


def run_login(new_window: bool, codex_home: Path | None = None) -> bool:
    command = _codex_command("login", "--device-auth")
    if command is None:
        print("usage: codex executable not found on PATH - skip")
        return False
    print(
        "usage: Codex device-code login requires ChatGPT Settings -> Codex -> "
        "`Enable device code authorization for Codex` to be enabled."
    )
    if new_window:
        if os.name != "nt":
            print("usage: --login-new-window is only available on Windows; falling back to --login")
        else:
            if codex_home is not None:
                try:
                    inner = str(_write_login_cmd(command, codex_home))
                except RuntimeError as exc:
                    print(f"usage: {exc} - skip")
                    return False
            else:
                inner = subprocess.list2cmdline(command)
            try:
                subprocess.Popen(["cmd.exe", "/c", "start", "Codex Login", "cmd.exe", "/k", inner])
            except OSError as exc:
                print(f"usage: could not open login command prompt ({type(exc).__name__}) - skip")
                return False
            input("Complete Codex login in the new Command Prompt, then press Enter here to retry.")
            return True
    print("usage: launching `codex login --device-auth`; return here when it completes.")
    try:
        codex_env = _codex_env(codex_home)
    except RuntimeError as exc:
        print(f"usage: {exc} - skip")
        return False
    try:
        completed = subprocess.run(command, check=False, env=codex_env)
    except OSError as exc:
        print(f"usage: could not run codex login ({type(exc).__name__}) - skip")
        return False
    return completed.returncode == 0


def print_rate_limits(response: dict[str, Any]) -> None:
    lines = _extract_rate_limit_lines(response)
    if lines:
        for line in lines:
            print(line)
        return
    result = response.get("result") if isinstance(response, dict) else None
    keys = list(result.keys()) if isinstance(result, dict) else type(result).__name__
    print(f"usage: response received but no known rate-limit fields were found; result keys: {keys}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print Codex account rate-limit utilization.")
    parser.add_argument("--login", action="store_true", help="authenticate with `codex login --device-auth` before retrying")
    parser.add_argument(
        "--login-new-window",
        action="store_true",
        help="open a Windows Command Prompt for `codex login --device-auth`, then retry",
    )
    parser.add_argument(
        "--show-response-shape",
        action="store_true",
        help="print a sanitized response-shape tree for validation",
    )
    parser.add_argument(
        "--repo-local-home",
        action="store_true",
        help="use AI/work/codex-home-agent as CODEX_HOME so sandbox agents and the user terminal share one local login",
    )
    parser.add_argument(
        "--codex-home",
        help="explicit CODEX_HOME path to use for login and rate-limit reads",
    )
    parser.add_argument(
        "--app-server-url",
        help="query an already-running Codex app-server websocket URL, e.g. ws://127.0.0.1:17340",
    )
    parser.add_argument(
        "--run-bridge",
        action="store_true",
        help="start a visible localhost usage bridge; press any key in that window to stop it",
    )
    parser.add_argument(
        "--login-if-needed",
        action="store_true",
        help="with --run-bridge, verify repo-local Codex auth and run device-code login first if needed",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=DEFAULT_BRIDGE_PORT,
        help=f"localhost port for --run-bridge (default: {DEFAULT_BRIDGE_PORT})",
    )
    parser.add_argument(
        "--no-bridge-autodetect",
        action="store_true",
        help="do not auto-use AI/work/codex-usage-bridge.json when present",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for each app-server response")
    args = parser.parse_args(argv)

    if args.repo_local_home and args.codex_home:
        parser.error("use only one of --repo-local-home or --codex-home")
    use_repo_local_home = args.repo_local_home or args.run_bridge
    codex_home = _repo_local_codex_home() if use_repo_local_home else Path(args.codex_home) if args.codex_home else None
    if codex_home is not None:
        print(f"usage: using repo-local CODEX_HOME={codex_home.resolve()}")

    if args.run_bridge:
        return run_bridge(args.bridge_port, codex_home, args.timeout, args.login_if_needed)

    if (args.login or args.login_new_window) and not run_login(args.login_new_window, codex_home):
        return 0

    if args.app_server_url:
        status, payload = read_rate_limits_ws(args.app_server_url, args.timeout)
    elif not args.no_bridge_autodetect and (bridge_url := _running_bridge_url()):
        print(f"usage: using running Codex usage bridge {bridge_url}")
        status, payload = read_rate_limits_ws(bridge_url, args.timeout)
    else:
        status, payload = read_rate_limits(args.timeout, codex_home)
    if status == "ok" and isinstance(payload, dict):
        print_rate_limits(payload)
        if args.show_response_shape:
            print_response_shape(payload)
        return 0
    if status == "auth_required":
        if args.login or args.login_new_window:
            print("usage: codex account authentication is still unavailable after login - skip")
            return 0
        print(
            "usage: codex account authentication required; rerun with --login to authenticate. "
            "Device-code login requires ChatGPT Settings -> Codex -> "
            "`Enable device code authorization for Codex` to be enabled. For sandbox sharing, run "
            "`--repo-local-home --login` in your terminal, then run `--repo-local-home` from the agent - skip"
        )
        return 0
    if (
        isinstance(payload, str)
        and "chatgpt.com/backend-api/wham/usage" in payload
        and not args.app_server_url
    ):
        payload += (
            "; direct sandbox egress is blocked. Start the visible bridge with "
            "codex_usage_bridge.cmd or `python codex_usage_check.py --run-bridge --login-if-needed`, then retry"
        )
    print(f"usage: {payload} - skip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
