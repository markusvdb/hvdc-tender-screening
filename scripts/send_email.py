"""Send the weekly digest via SMTP."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger(__name__)


def send_email(subject: str, html_body: str, text_body: str = "") -> None:
    """Send an HTML email using SMTP credentials from the environment.

    Required env vars:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
      EMAIL_FROM, EMAIL_TO
    """
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    sender = os.environ.get("EMAIL_FROM", user)
    recipient = os.environ["EMAIL_TO"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(text_body or "This email requires an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()

    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)

    log.info("Sent email to %s via %s:%d", recipient, host, port)
