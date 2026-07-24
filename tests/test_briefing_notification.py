from __future__ import annotations

import httpx
import pytest

from scout.config import Settings
from scout.sub_agents.briefing.notification import (
    ensure_discord_configured,
    send_message,
)


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=None  # type: ignore[arg-type]
            )


class _FakeAsyncClient:
    instances: list["_FakeAsyncClient"] = []

    def __init__(self, *args, **kwargs):
        self.post_calls: list[dict] = []
        self.status_code = 200
        _FakeAsyncClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, *, headers=None, json=None):
        self.post_calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(self.status_code)


@pytest.fixture(autouse=True)
def _reset_fake_client(monkeypatch):
    _FakeAsyncClient.instances = []
    monkeypatch.setattr(
        "scout.sub_agents.briefing.notification.httpx.AsyncClient", _FakeAsyncClient
    )
    yield
    _FakeAsyncClient.instances = []


def _settings():
    return Settings(discord_bot_token="bot-token", discord_channel_id="123456789")


def test_ensure_discord_configured_raises_when_token_missing():
    with pytest.raises(ValueError):
        ensure_discord_configured(Settings(discord_bot_token="", discord_channel_id="123"))


def test_ensure_discord_configured_raises_when_channel_missing():
    with pytest.raises(ValueError):
        ensure_discord_configured(
            Settings(discord_bot_token="tok", discord_channel_id="")
        )


@pytest.mark.asyncio
async def test_send_message_posts_to_channel_with_bot_auth():
    payload = {"embeds": [{"title": "hi"}]}

    await send_message(payload, _settings())

    client = _FakeAsyncClient.instances[0]
    assert len(client.post_calls) == 1
    call = client.post_calls[0]
    assert call["url"] == (
        "https://discord.com/api/v10/channels/123456789/messages"
    )
    assert call["headers"]["Authorization"] == "Bot bot-token"
    assert call["json"] == payload


@pytest.mark.asyncio
async def test_send_message_raises_on_non_success_response(monkeypatch):
    payload = {"embeds": [{"title": "hi"}]}

    class _FailingClient(_FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.status_code = 403

    monkeypatch.setattr(
        "scout.sub_agents.briefing.notification.httpx.AsyncClient", _FailingClient
    )

    with pytest.raises(httpx.HTTPStatusError):
        await send_message(payload, _settings())
