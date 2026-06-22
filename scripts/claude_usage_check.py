"""Print Claude usage utilization from the local OAuth token. The token is never printed.

SECURITY: the OAuth token / credentials are SECRET. This script reads them ONLY to call the
usage endpoint and NEVER prints, logs, or writes the token or raw credentials. The credentials
file is treated as read-only. If the file/token is absent (for example, credentials live in an
OS keychain) it says so and exits cleanly without leaking anything.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

CRED = Path.home() / ".claude" / ".credentials.json"
URL = "https://api.anthropic.com/api/oauth/usage"
HEADERS_EXTRA = {"anthropic-beta": "oauth-2025-04-20", "Accept": "application/json"}
WINDOWS = ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "seven_day_cowork")


def _find_token(obj):
    """Recursively find an access-token value without surfacing it."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and "access" in k.lower() and "token" in k.lower():
                return v
            found = _find_token(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_token(v)
            if found:
                return found
    return None


def main() -> int:
    if not CRED.is_file():
        print(f"usage: credentials file not found at {CRED} (token may be in an OS keychain) - skip")
        return 0
    try:
        token = _find_token(json.loads(CRED.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"usage: could not read/parse credentials ({type(exc).__name__}) - skip")
        return 0
    if not token:
        print("usage: no access token in credentials file - skip")
        return 0
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {token}", **HEADERS_EXTRA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"usage: endpoint returned HTTP {exc.code} - skip")
        return 0
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
        print(f"usage: request failed ({type(exc).__name__}) - skip")
        return 0
    printed = False
    if isinstance(data, dict):
        for w in WINDOWS:
            win = data.get(w)
            if isinstance(win, dict) and win.get("utilization") is not None:
                resets = win.get("resets_at") or win.get("resetsAt")
                print(f"{w}: utilization={win['utilization']}" + (f" resets_at={resets}" if resets else ""))
                printed = True
    if not printed:
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        print(f"usage: response received but no known utilization window present; top-level keys: {keys}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
