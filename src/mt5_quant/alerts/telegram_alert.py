"""Telegram 警报推送模块。

支持发送纯文本消息，对接 LossStreakGuardrail 的 alert callback。
"""

from __future__ import annotations

import logging
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)


class TelegramAlert:
    """Telegram Bot 消息推送。

    使用 Bot API: https://core.telegram.org/bots/api#sendmessage
    """

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        if not bot_token or not chat_id:
            LOGGER.warning("Telegram bot_token 或 chat_id 为空，警报将不会发送。")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._url = self.BASE_URL.format(token=bot_token)

    def send_message(self, text: str) -> bool:
        """发送文本消息到 Telegram。"""
        if not self.bot_token or not self.chat_id:
            LOGGER.warning("Telegram 未配置，忽略消息: %s", text[:50])
            return False

        try:
            payload = (
                f"chat_id={quote(self.chat_id)}"
                f"&text={quote(text)}"
                f"&parse_mode=HTML"
            )
            full_url = f"{self._url}?{payload}"
            request = Request(full_url, headers={"User-Agent": "mt5-quant-system/0.1"})
            with urlopen(request, timeout=15) as response:
                response.read()
            LOGGER.info("Telegram 消息发送成功: %s...", text[:50])
            return True
        except (HTTPError, URLError, OSError) as exc:
            LOGGER.error("Telegram 发送失败: %s", exc)
            return False

    def send_loss_streak_alert(
        self,
        loss_streak: int,
        symbol: str,
        timeframe: str,
        csv_path: str = "",
        suggestion: str = "",
    ) -> bool:
        """发送连亏警报（含建议）。"""
        text = (
            f"🚨 <b>连亏警报</b>\n"
            f"品种：{symbol}\n"
            f"周期：{timeframe}\n"
            f"连续亏损：{loss_streak} 次\n"
        )
        if csv_path:
            text += f"行情片段：{csv_path}\n"
        if suggestion:
            text += f"建议：{suggestion}\n"
        else:
            text += "建议：切换至更高周期（如 M5）或暂停交易。\n"

        return self.send_message(text)

    def send_status_update(
        self,
        symbol: str,
        timeframe: str,
        status: dict,
    ) -> bool:
        """发送策略状态更新。"""
        text = (
            f"📊 <b>策略状态</b>\n"
            f"品种：{symbol}\n"
            f"周期：{timeframe}\n"
            f"模式：{status.get('mode', 'unknown')}\n"
            f"连亏次数：{status.get('loss_streak', 0)}\n"
            f"冷却剩余：{status.get('cooldown_remaining_seconds', 0)} 秒\n"
        )
        return self.send_message(text)
