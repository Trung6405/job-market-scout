from __future__ import annotations

import httpx

from scout.config import Settings

_DISCORD_API_BASE = "https://discord.com/api/v10"


def ensure_discord_configured(settings: Settings) -> None:
    if not settings.discord_bot_token or not settings.discord_channel_id:
        raise ValueError(
            "DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID must both be set to send a "
            "briefing message"
        )


async def send_message(payload: dict, settings: Settings) -> None:
    ensure_discord_configured(settings)
    url = f"{_DISCORD_API_BASE}/channels/{settings.discord_channel_id}/messages"
    headers = {"Authorization": f"Bot {settings.discord_bot_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
