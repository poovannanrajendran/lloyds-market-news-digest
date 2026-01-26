from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Mapping


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    host: str
    port: int
    user: str | None
    password: str | None
    sender: str
    recipients: list[str]


def load_email_config(env: Mapping[str, str] | None = None) -> EmailConfig:
    data = env or os.environ
    enabled = data.get("SMTP_ENABLED", "false").lower() in {"1", "true", "yes"}
    host = data.get("SMTP_HOST", "")
    port = int(data.get("SMTP_PORT", "587"))
    user = data.get("SMTP_USER")
    password = data.get("SMTP_PASSWORD")
    sender = data.get("SMTP_FROM", "")
    recipients = [r.strip() for r in data.get("SMTP_TO", "").split(",") if r.strip()]
    return EmailConfig(
        enabled=enabled,
        host=host,
        port=port,
        user=user,
        password=password,
        sender=sender,
        recipients=recipients,
    )


def send_digest_email(
    subject: str,
    html_body: str,
    env: Mapping[str, str] | None = None,
) -> bool:
    config = load_email_config(env)
    if not config.enabled:
        return False
    if not (config.host and config.sender and config.recipients):
        raise ValueError("SMTP settings incomplete")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message.set_content("HTML digest attached.")
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(config.host, config.port) as server:
        server.starttls()
        if config.user and config.password:
            server.login(config.user, config.password)
        server.send_message(message)
    return True
