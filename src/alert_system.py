"""
alert_system.py
================
Sends a Telegram message to the family when the deviation detector fires.

SETUP (one time):
  1. Open Telegram, search @BotFather
  2. Send /newbot, follow instructions, copy the token
  3. Add the bot to your family group chat
  4. Get the chat_id by visiting:
     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
  5. Set environment variables:
     export CAREWATCH_BOT_TOKEN="your_token_here"
     export CAREWATCH_CHAT_ID="your_chat_id_here"

USAGE:
    from src.alert_system import AlertSystem
    alerts = AlertSystem()
    alerts.send(risk_result)   # pass output from DeviationDetector.check()
"""

import logging
import os
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

# Load .env from repo root if present (so CAREWATCH_BOT_TOKEN etc. work)
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass  # python-dotenv not installed; use export or system env
from datetime import datetime

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Risk level → emoji
RISK_EMOJI = {
    "GREEN":   "✅",
    "YELLOW":  "⚠️",
    "RED":     "🚨",
    "UNKNOWN": "❓",
}


class AlertSystem:
    def __init__(self):
        self.token   = os.environ.get("CAREWATCH_BOT_TOKEN", "")
        self.chat_id = os.environ.get("CAREWATCH_CHAT_ID", "")

        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not set. Alerts will log to console only.")

    def send(self, risk_result: dict, person_name: str = "Your family member"):
        """
        Send an alert based on deviation detector output.
        Only sends if risk_level is YELLOW or RED.
        """
        level = risk_result.get("risk_level", "UNKNOWN")
        score = risk_result.get("risk_score", 0)
        anomalies = risk_result.get("anomalies", [])

        # Don't spam the family for GREEN days
        if level == "GREEN":
            logger.info("%s — all normal, no alert sent.", person_name)
            return

        emoji = RISK_EMOJI.get(level, "❓")
        time_str = datetime.now().strftime("%I:%M %p")

        # Build message
        lines = [
            f"{emoji} *CareWatch Alert — {person_name}*",
            f"📅 {datetime.now().strftime('%A, %d %b %Y')} at {time_str}",
            f"Risk Level: *{level}* (score: {score}/100)",
            "",
            f"_{risk_result.get('summary', 'No summary available.')}_",
            "",
        ]

        if anomalies:
            lines.append("*Issues detected:*")
            for a in anomalies:
                if not isinstance(a, dict):
                    continue
                sev_icon = "🔴" if a["severity"] == "HIGH" else "🟡" if a["severity"] == "MEDIUM" else "🔵"
                lines.append(f"{sev_icon} {a['message']}")

        ai = risk_result.get("ai_explanation")
        if ai:
            lines += [
                "",
                f"AI Assessment: {ai.get('summary', '')}",
                f"Recommended action: {ai.get('action', '')}",
                f"Today's positive: {ai.get('positive', '')}",
            ]
        else:
            lines += [
                "",
                "Please check in with them or review the CareWatch dashboard.",
            ]

        message = "\n".join(lines)

        logger.info("ALERT TRIGGERED: %s", message.replace("*", "").replace("_", ""))

        # Send to Telegram if configured
        if self.token and self.chat_id:
            self._send_telegram(message)

    def _send_telegram(self, message: str):
        url = TELEGRAM_API.format(token=self.token)
        payload = {
            "chat_id":    self.chat_id,
            "text":       message,
            "parse_mode": "Markdown",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Telegram alert sent successfully.")
            else:
                logger.error("Telegram error: %s — %s", resp.status_code, resp.text)
        except requests.RequestException as e:
            logger.error("Could not send Telegram alert: %s", e)

    def send_daily_summary(self, risk_result: dict, person_name: str = "Your family member"):
        """Send an end-of-day summary regardless of risk level."""
        level  = risk_result.get("risk_level", "UNKNOWN")
        score  = risk_result.get("risk_score", 0)
        emoji  = RISK_EMOJI.get(level, "❓")

        message = (
            f"{emoji} *CareWatch Daily Summary — {person_name}*\n"
            f"📅 {datetime.now().strftime('%A, %d %b %Y')}\n\n"
            f"Overall day: *{level}* (score: {score}/100)\n"
            f"_{risk_result.get('summary', '')}_\n\n"
            f"Have a good night! 🌙"
        )

        logger.info("Daily summary: %s", message.replace("*", "").replace("_", ""))
        if self.token and self.chat_id:
            self._send_telegram(message)