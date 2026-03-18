"""
telegram_listener.py
====================
Polls Telegram for /clear <person_id> commands. When a caregiver sends the command,
clears the persistent alert in AlertStore and confirms back. Uses same token/chat_id
as AlertSystem — credentials loaded from .env at repo root.

USAGE:
    from src.telegram_listener import TelegramListener
    TelegramListener().poll()  # blocking — run in background thread or separate terminal
"""

import logging
import os
import time
import requests
from pathlib import Path

from src.alert_store import AlertStore

logger = logging.getLogger(__name__)

# Load .env from repo root — identical pattern to alert_system.py
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

TELEGRAM_API = "https://api.telegram.org/bot{token}"


class TelegramListener:
    """Polls for /clear commands. Blocking loop — run in background thread or terminal."""

    def __init__(self):
        self.token   = os.environ.get("CAREWATCH_BOT_TOKEN", "")
        self.chat_id = os.environ.get("CAREWATCH_CHAT_ID", "")
        self.store   = AlertStore()
        self.offset  = 0

        if not self.token or not self.chat_id:
            raise EnvironmentError(
                "CAREWATCH_BOT_TOKEN and CAREWATCH_CHAT_ID must be set. "
                "Check your .env file or export them manually."
            )

    def _get_updates(self) -> list:
        url = f"{TELEGRAM_API.format(token=self.token)}/getUpdates"
        try:
            r = requests.get(url, params={"offset": self.offset, "timeout": 10})
            return r.json().get("result", [])
        except Exception as e:
            logger.warning("Telegram poll error: %s", e)
            return []

    def _send(self, text: str):
        url = f"{TELEGRAM_API.format(token=self.token)}/sendMessage"
        requests.post(url, json={"chat_id": self.chat_id, "text": text})

    def _handle(self, message: dict):
        text = message.get("text", "").strip()
        if not text.startswith("/clear"):
            return
        parts = text.split()
        if len(parts) != 2:
            self._send("Usage: /clear <person_id>   e.g. /clear resident_0042")
            return
        person_id = parts[1]
        cleared   = self.store.clear_alert(person_id)
        if cleared:
            self._send(f"Alert cleared for {person_id}. Resuming normal monitoring.")
        else:
            self._send(f"No active alert found for {person_id}.")

    def poll(self, interval_seconds: int = 5):
        """Blocking loop. Run in a background thread or separate terminal."""
        # User-facing startup message — matches plan verification expectation
        logger.info("Listener started. Waiting for /clear commands...")
        while True:
            updates = self._get_updates()
            for update in updates:
                self.offset = update["update_id"] + 1
                msg = update.get("message", {})
                if msg:
                    self._handle(msg)
            time.sleep(interval_seconds)


if __name__ == "__main__":
    TelegramListener().poll()
