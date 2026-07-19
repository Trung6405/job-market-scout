from __future__ import annotations

import smtplib
from email.message import EmailMessage

from scout.config import Settings

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 465


def send_email(message: EmailMessage, settings: Settings) -> None:
    if not settings.gmail_address or not settings.gmail_app_password:
        raise ValueError(
            "GMAIL_ADDRESS and GMAIL_APP_PASSWORD must both be set to send a "
            "briefing email"
        )
    with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT) as smtp:
        smtp.login(settings.gmail_address, settings.gmail_app_password)
        smtp.send_message(message)
