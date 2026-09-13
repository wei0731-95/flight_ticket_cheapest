"""Send the run report by email."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .config import MailConfig

log = logging.getLogger(__name__)

_SENDER_NAME = "trip.com 機票監控"


class NotifyError(RuntimeError):
    """Sending the email failed."""


def build_message(mail: MailConfig, subject: str, text: str, html: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((_SENDER_NAME, mail.sender or mail.user))
    message["To"] = ", ".join(mail.recipients)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain="tripcom-watcher.local")
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def send_email(mail: MailConfig, subject: str, text: str, html: str) -> None:
    """Deliver one report. Raises :class:`NotifyError` on any SMTP failure."""
    if not mail.configured:
        raise NotifyError(f"寄信設定不完整，缺少：{', '.join(mail.missing())}")

    message = build_message(mail, subject, text, html)
    context = ssl.create_default_context()
    try:
        if mail.port == 465:
            with smtplib.SMTP_SSL(mail.host, mail.port, context=context, timeout=60) as server:
                server.login(mail.user, mail.password)
                server.send_message(message)
        else:
            with smtplib.SMTP(mail.host, mail.port, timeout=60) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(mail.user, mail.password)
                server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise NotifyError(
            "SMTP 認證失敗。Gmail 必須使用「應用程式密碼」而非帳號密碼，"
            f"且帳號需已開啟兩步驟驗證。原始錯誤：{exc}"
        ) from exc
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise NotifyError(f"寄信失敗：{type(exc).__name__}: {exc}") from exc

    log.info("已寄出通知給 %s", ", ".join(mail.recipients))
