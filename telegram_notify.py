"""Send messages to a Telegram user through a bot.

Usage:
    python telegram_notify.py "Hello!"      # send a message
    python telegram_notify.py --get-chat-id  # find your chat id
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.telegram.org/bot{token}/{method}"
MAX_LENGTH = 4096  # Telegram's limit per message


def _token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Missing TELEGRAM_BOT_TOKEN in .env")
    return token


def _split(text: str) -> list[str]:
    """Split long text into chunks under Telegram's limit, breaking on lines."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > MAX_LENGTH:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


def send_message(text: str, chat_id: str | None = None) -> None:
    """Send `text` to `chat_id` (defaults to TELEGRAM_CHAT_ID from .env).

    Text longer than Telegram's limit is sent as several messages.
    """
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise ValueError("Missing TELEGRAM_CHAT_ID in .env")

    for chunk in _split(text):
        response = requests.post(
            API_URL.format(token=_token(), method="sendMessage"),
            json={"chat_id": chat_id, "text": chunk},
            timeout=10,
        )
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram error: {data.get('description')}")


def print_chat_ids() -> None:
    """List chat ids of users who recently messaged the bot."""
    response = requests.get(
        API_URL.format(token=_token(), method="getUpdates"), timeout=10
    )
    updates = response.json().get("result", [])
    if not updates:
        print("No messages found. Send any message to your bot first, then retry.")
        return

    seen = set()
    for update in updates:
        chat = (update.get("message") or {}).get("chat")
        if chat and chat["id"] not in seen:
            seen.add(chat["id"])
            name = chat.get("username") or chat.get("first_name", "")
            print(f"chat_id={chat['id']}  ({name})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--get-chat-id":
        print_chat_ids()
    else:
        send_message(" ".join(sys.argv[1:]))
        print("Message sent.")
