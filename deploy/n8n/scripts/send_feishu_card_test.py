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
    markdown = (
        "**飞书群机器人消息卡片 UTF-8 测试**\n\n"
        "**来源**：Signal to Obsidian\n\n"
        "**摘要**\n"
        "这是一条通过仓库脚本发送的测试卡片，用来避免 Windows "
        "PowerShell 管道把中文转成问号。\n\n"
        "**状态**：如果这条显示正常，说明飞书 webhook 和消息卡片编码链路正常。"
    )
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "wide_screen_mode": True,
                "summary": {"content": "飞书消息卡片 UTF-8 测试"},
            },
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "AI 信息摘要"},
                "padding": "12px 12px 12px 12px",
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": markdown,
                        "text_align": "left",
                    }
                ],
            },
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
