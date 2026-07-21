from __future__ import annotations

from email.message import EmailMessage

import pytest

from scout.config import Settings
from scout.sub_agents.briefing.notification import send_email


class _FakeSmtp:
    instances: list["_FakeSmtp"] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.login_calls = []
        self.sent_messages = []
        _FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def login(self, address, password):
        self.login_calls.append((address, password))

    def send_message(self, message):
        self.sent_messages.append(message)


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSmtp.instances = []
    yield
    _FakeSmtp.instances = []


def test_send_email_raises_when_gmail_address_missing(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSmtp)
    settings = Settings(gmail_address="", gmail_app_password="secret")

    with pytest.raises(ValueError):
        send_email(EmailMessage(), settings)

    assert _FakeSmtp.instances == []


def test_send_email_raises_when_app_password_missing(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSmtp)
    settings = Settings(gmail_address="scout@example.com", gmail_app_password="")

    with pytest.raises(ValueError):
        send_email(EmailMessage(), settings)

    assert _FakeSmtp.instances == []


def test_send_email_logs_in_and_sends(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSmtp)
    settings = Settings(gmail_address="scout@example.com", gmail_app_password="secret")
    message = EmailMessage()

    send_email(message, settings)

    smtp = _FakeSmtp.instances[0]
    assert smtp.login_calls == [("scout@example.com", "secret")]
    assert smtp.sent_messages == [message]


def test_send_email_propagates_smtp_failures(monkeypatch):
    class _FailingSmtp(_FakeSmtp):
        def login(self, address, password):
            raise RuntimeError("auth failed")

    monkeypatch.setattr("smtplib.SMTP_SSL", _FailingSmtp)
    settings = Settings(gmail_address="scout@example.com", gmail_app_password="secret")

    with pytest.raises(RuntimeError):
        send_email(EmailMessage(), settings)
