"""Telegram alerts + Rich console notifications."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


class Notifier:
    """Sends alerts via Telegram and/or Rich console."""

    def __init__(
        self,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        telegram_enabled: bool = False,
        console_enabled: bool = True,
    ):
        self._bot_token = telegram_bot_token
        self._chat_id = telegram_chat_id
        self._tg_enabled = telegram_enabled and bool(telegram_bot_token) and bool(telegram_chat_id)
        self._console_enabled = console_enabled

    def info(self, message: str):
        self._send(message, "INFO", "blue")

    def trade_entry(self, message: str):
        self._send(f"ENTRY: {message}", "TRADE", "green")

    def trade_exit(self, message: str):
        self._send(f"EXIT: {message}", "TRADE", "yellow")

    def warning(self, message: str):
        self._send(message, "WARN", "yellow")

    def error(self, message: str):
        self._send(message, "ERROR", "red")

    def kill_switch(self, message: str):
        self._send(f"KILL SWITCH: {message}", "CRITICAL", "bold red")

    def daily_summary(self, summary: str):
        self._send(f"DAILY SUMMARY:\n{summary}", "SUMMARY", "cyan")

    def _send(self, message: str, level: str, style: str):
        ts = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{ts}] [{level}] {message}"

        if self._console_enabled:
            console.print(f"[{style}]{formatted}[/{style}]")

        if self._tg_enabled:
            self._send_telegram(formatted)

    def _send_telegram(self, text: str):
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            httpx.post(
                url,
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception:
            logger.exception("Telegram send failed")
