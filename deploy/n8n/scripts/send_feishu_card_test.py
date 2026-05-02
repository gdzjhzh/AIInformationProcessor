#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT_DIR / "deploy" / ".env"


def load_env_value(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if value:
        return value
    if not ENV_FILE.exists():
        return ""

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        if name.strip() != key:
            continue
        parsed_value = raw_value.strip()
        if (
            len(parsed_value) >= 2
            and parsed_value[0] == parsed_value[-1]
            and parsed_value[0] in {"'", '"'}
        ):
            parsed_value = parsed_value[1:-1]
        return parsed_value.strip()
    return ""


def build_card_payload() -> dict[str, object]:
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": "AI \u4fe1\u606f\u6458\u8981",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "**\u98de\u4e66\u7fa4\u673a\u5668\u4eba\u6d88\u606f"
                            "\u5361\u7247 UTF-8 \u6d4b\u8bd5**\n\n"
                            "**\u6765\u6e90**: Signal to Obsidian\n\n"
                            "**\u6458\u8981**\n"
                            "\u8fd9\u662f\u4e00\u6761\u901a\u8fc7\u4ed3\u5e93"
                            "\u811a\u672c\u53d1\u9001\u7684\u6d4b\u8bd5\u5361"
                            "\u7247\uff0c\u7528\u6765\u907f\u514d Windows "
                            "PowerShell \u7ba1\u9053\u628a\u4e2d\u6587\u8f6c"
                            "\u6210\u95ee\u53f7\u3002\n\n"
                            "**\u72b6\u6001**: \u5982\u679c\u8fd9\u6761"
                            "\u663e\u793a\u6b63\u5e38\uff0c\u8bf4\u660e"
                            "\u98de\u4e66 webhook \u548c\u6d88\u606f\u5361"
                            "\u7247\u7f16\u7801\u94fe\u8def\u6b63\u5e38\u3002"
                        ),
                    },
                }
            ],
        },
    }


def send_card(webhook_url: str, payload: dict[str, object]) -> tuple[int, str]:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response_body = response.read().decode("utf-8", errors="replace")
        return response.status, response_body


def main() -> int:
    webhook_url = load_env_value("FEISHU_WEBHOOK_URL")
    if not webhook_url:
        print("FEISHU_WEBHOOK_URL is not configured in environment or deploy/.env", file=sys.stderr)
        return 2

    try:
        status, response_body = send_card(webhook_url, build_card_payload())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP status={exc.code}", file=sys.stderr)
        print(body[:500], file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Network error: {exc.reason}", file=sys.stderr)
        return 1

    print(f"HTTP status={status}")
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        print(response_body[:500])
        return 0 if status == 200 else 1

    status_code = parsed.get("StatusCode", parsed.get("code"))
    message = parsed.get("StatusMessage", parsed.get("msg", ""))
    print(f"Feishu StatusCode={status_code}")
    print(f"Feishu message={message}")
    if status != 200 or status_code not in (0, None):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
