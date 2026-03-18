"""
alert_system.py
================
Sends alerts to family when the deviation detector fires.

MERGE ADDITIONS:
  - TTS delivery channel via src/tts.py
  - send() accepts voice_alert flag
  - Privacy: strip_pii() applied before Telegram send
"""

import html
import logging
import os
import re
import requests
from datetime import datetime
from pathlib import Path

from src.privacy import strip_pii as _strip_pii

logger = logging.getLogger(__name__)

_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

RISK_EMOJI = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "🚨", "UNKNOWN": "❓"}


class AlertSystem:
    def __init__(self):
        self.token   = os.environ.get("CAREWATCH_BOT_TOKEN", "")
        self.chat_id = os.environ.get("CAREWATCH_CHAT_ID", "")
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not set. Alerts will log to console only.")

    def send(self, risk_result: dict, person_name: str = "Your family member",
             voice_alert: bool = False):
        level     = risk_result.get("risk_level", "UNKNOWN")
        score     = risk_result.get("risk_score", 0)
        anomalies = risk_result.get("anomalies", [])

        if level == "GREEN":
            logger.info("%s — all normal, no alert sent.", person_name)
            return

        safe_result      = _strip_pii(risk_result)
        person_name_safe = html.escape(str(person_name))
        summary_safe     = html.escape(str(safe_result.get("summary", "No summary available.")))

        emoji    = RISK_EMOJI.get(level, "❓")
        time_str = datetime.now().strftime("%I:%M %p")

        lines = [
            f"{emoji} <b>CareWatch Alert — {person_name_safe}</b>",
            f"📅 {datetime.now().strftime('%A, %d %b %Y')} at {time_str}",
            f"Risk Level: <b>{level}</b> (score: {score}/100)",
            "",
            f"<i>{summary_safe}</i>",
            "",
        ]

        if anomalies:
            lines.append("<b>Issues detected:</b>")
            for a in anomalies:
                if not isinstance(a, dict):
                    continue
                sev_icon = "🔴" if a.get("severity") == "HIGH" else "🟡" if a.get("severity") == "MEDIUM" else "🔵"
                msg_safe = html.escape(str(a.get("message", "")))
                lines.append(f"{sev_icon} {msg_safe}")

        ai = safe_result.get("ai_explanation")
        if ai:
            lines += ["",
                      f"AI Assessment: {html.escape(str(ai.get('summary', '')))}",
                      f"Recommended action: {html.escape(str(ai.get('action', '')))}",
                      f"Today's positive: {html.escape(str(ai.get('positive', '')))}"]
        else:
            lines += ["", "Please check in with them or review the CareWatch dashboard."]

        message = "\n".join(lines)
        logger.info("ALERT TRIGGERED: %s", re.sub(r"<[^>]+>", "", message))

        if self.token and self.chat_id:
            self._send_telegram(message)

        if voice_alert:
            self._send_tts(level, person_name, safe_result)

    def _send_telegram(self, message: str):
        url = TELEGRAM_API.format(token=self.token)
        try:
            resp = requests.post(url, json={"chat_id": self.chat_id, "text": message,
                                             "parse_mode": "HTML"}, timeout=10)
            if resp.status_code == 200:
                logger.info("Telegram alert sent successfully.")
            else:
                logger.error("Telegram error: %s — %s", resp.status_code, resp.text)
        except requests.RequestException as e:
            logger.error("Could not send Telegram alert: %s", e)

    def _send_tts(self, level: str, person_name: str, safe_result: dict):
        try:
            from src.tts import speak
            ai     = safe_result.get("ai_explanation") or {}
            action = ai.get("action", "Please check on your family member.")
            if level == "RED":
                spoken = f"Urgent CareWatch alert for {person_name}. {action} Please respond immediately."
            else:
                spoken = f"CareWatch notice for {person_name}. {action}"
            speak(spoken)
            logger.info("TTS alert fired for %s (level=%s)", person_name, level)
        except Exception as e:
            logger.warning("TTS delivery failed (non-fatal): %s", e)

    def send_daily_summary(self, risk_result: dict, person_name: str = "Your family member",
                           voice_alert: bool = False):
        level = risk_result.get("risk_level", "UNKNOWN")
        score = risk_result.get("risk_score", 0)
        safe_result = _strip_pii(risk_result)
        message = (
            f"{RISK_EMOJI.get(level, '❓')} <b>CareWatch Daily Summary — {html.escape(str(person_name))}</b>\n"
            f"📅 {datetime.now().strftime('%A, %d %b %Y')}\n\n"
            f"Overall day: <b>{level}</b> (score: {score}/100)\n"
            f"<i>{html.escape(str(safe_result.get('summary', '')))}</i>\n\n"
            f"Have a good night! 🌙"
        )
        logger.info("Daily summary: %s", re.sub(r"<[^>]+>", "", message))
        if self.token and self.chat_id:
            self._send_telegram(message)
        if voice_alert and level in ("YELLOW", "RED"):
            self._send_tts(level, person_name, safe_result)
