"""Sends the newsletter over SMTP (Gmail, Outlook, Zoho, etc.) with retries."""
from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import Secrets

log = logging.getLogger(__name__)


class MailError(RuntimeError):
    pass


def build_message(secrets: Secrets, subject: str, html: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Recast Intelligence <{secrets.email_from}>"
    msg["To"] = secrets.email_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=secrets.email_from.split("@")[-1] or "recast.local")
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send(secrets: Secrets, subject: str, html: str, text: str, attempts: int = 3) -> None:
    if not secrets.smtp_ready:
        raise MailError("Email is not configured. Fill in RECAST_EMAIL_* and RECAST_SMTP_* in .env")
    msg = build_message(secrets, subject, html, text)
    ctx = ssl.create_default_context()
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            if secrets.smtp_port == 465:
                with smtplib.SMTP_SSL(secrets.smtp_host, 465, context=ctx, timeout=30) as s:
                    s.login(secrets.smtp_user, secrets.smtp_password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(secrets.smtp_host, secrets.smtp_port, timeout=30) as s:
                    s.starttls(context=ctx)
                    s.login(secrets.smtp_user, secrets.smtp_password)
                    s.send_message(msg)
            log.info("email_sent to=%s subject=%r", secrets.email_to, subject)
            return
        except smtplib.SMTPAuthenticationError as e:
            raise MailError(f"SMTP login failed. For Gmail, use an App Password, not your normal password. ({e.smtp_code})") from e
        except (smtplib.SMTPException, OSError) as e:
            last = e
            log.warning("email_retry attempt=%d error=%s", attempt + 1, e)
            time.sleep(5 * (attempt + 1))
    raise MailError(f"Could not send email after {attempts} attempts: {last}")
