#!/usr/bin/env python3
"""
Проверяет RSS-фид дев-логов itch.io и постит новые записи в Discord через webhook.
Хранит id последней отправленной записи в файле state.json (коммитится обратно в репо).
"""

import json
import os
import sys
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape

FEED_URL = os.environ["FEED_URL"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
STATE_FILE = "state.json"

DISCORD_MAX_LEN = 4096  # лимит на description в embed


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_id": None}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": "itch-devlog-bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def strip_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return unescape(text).strip()


def parse_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    items = []
    # RSS 2.0 format (itch.io использует именно его)
    channel = root.find("channel")
    if channel is None:
        return items
    for item in channel.findall("item"):
        guid = item.findtext("guid") or item.findtext("link")
        title = item.findtext("title") or "Новый дев-лог"
        link = item.findtext("link") or ""
        description = item.findtext("description") or ""
        pub_date = item.findtext("pubDate") or ""
        items.append({
            "id": guid,
            "title": title.strip(),
            "link": link.strip(),
            "description": strip_html(description),
            "pub_date": pub_date,
        })
    return items


def post_to_discord(entry):
    description = entry["description"]
    if len(description) > DISCORD_MAX_LEN:
        description = description[: DISCORD_MAX_LEN - 3] + "..."

    payload = {
        "embeds": [
            {
                "title": entry["title"][:256],
                "url": entry["link"],
                "description": description or "(нет описания)",
                "color": 0xFA5C5C,  # itch.io-ish red
                "footer": {"text": "Новый дев-лог на itch.io"},
            }
        ]
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "itch-devlog-bot/1.0 (+https://github.com)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"Discord webhook вернул статус {resp.status}")


def main():
    state = load_state()
    try:
        xml_bytes = fetch_feed(FEED_URL)
    except Exception as e:
        print(f"Не удалось получить фид: {e}", file=sys.stderr)
        sys.exit(1)

    items = parse_feed(xml_bytes)
    if not items:
        print("В фиде нет записей.")
        return

    # Фид отдаёт записи от новых к старым
    last_id = state.get("last_id")

    if last_id is None:
        # Первый запуск — просто запоминаем текущую последнюю запись, ничего не постим,
        # чтобы не спамить весь исторический дев-лог разом.
        state["last_id"] = items[0]["id"]
        save_state(state)
        print(f"Первый запуск. Запомнили последнюю запись: {items[0]['title']}")
        return

    # Собираем все новые записи (те, что идут до last_id), постим от старых к новым
    new_items = []
    for item in items:
        if item["id"] == last_id:
            break
        new_items.append(item)

    if not new_items:
        print("Новых записей нет.")
        return

    new_items.reverse()  # от старых к новым, чтобы порядок в Discord был правильный

    for item in new_items:
        print(f"Постим: {item['title']}")
        post_to_discord(item)

    state["last_id"] = items[0]["id"]
    save_state(state)
    print(f"Готово. Отправлено записей: {len(new_items)}")


if __name__ == "__main__":
    main()
