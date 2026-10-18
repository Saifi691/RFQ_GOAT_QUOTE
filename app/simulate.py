"""Simulation: send a real RFQ email from a test sender account to the bot's inbox.

The recipient is always BOT_EMAIL, so the dashboard cannot be used to email anyone else.
Attachments are limited to the kit's own sample item list; nothing is uploaded.
"""
import os
import smtplib
import threading
import time
from collections import deque
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid

from app.config import ROOT

SAMPLE_ATTACHMENT = ROOT / "emails" / "rfq_items.xlsx"
XLSX = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
PRESET_FILES = [
    ("email-1", "Email 1 · IDs in the body", "email-1-ids-in-body.eml"),
    ("email-2", "Email 2 · IDs in an Excel attachment", "email-2-ids-in-attachment.eml"),
    ("email-3", "Email 3 · Ferguson and competitor items", "email-3-mixed-ferguson-and-competitor.eml"),
    ("email-4", "Email 4 · Messy forwarded thread", "email-4-messy-forward.eml"),
]
MAX_SUBJECT = 200
MAX_BODY = 20_000
MIN_INTERVAL_S = 10
MAX_PER_HOUR = 30

_sent_times = deque()
_lock = threading.Lock()


class SimulationError(ValueError):
    """A problem the user can fix (shown in the panel)."""


def accounts():
    sender = os.getenv("SIM_SENDER_EMAIL", "").strip()
    password = os.getenv("SIM_SENDER_PASSWORD", "").replace(" ", "")
    bot = os.getenv("BOT_EMAIL", "").strip()
    return sender, password, bot


def config():
    sender, password, bot = accounts()
    problems = []
    if not bot:
        problems.append("Set BOT_EMAIL in .env (the bot's inbox).")
    if not sender or not password:
        problems.append("Set SIM_SENDER_EMAIL and SIM_SENDER_PASSWORD in .env (a second Gmail account and its App Password).")
    elif bot and sender.lower() == bot.lower():
        problems.append("SIM_SENDER_EMAIL must differ from BOT_EMAIL: the bot ignores emails from its own address.")
    allowed = {x.strip().lower() for x in os.getenv("RFQ_ALLOWED_SENDERS", "").split(",") if x.strip()}
    if allowed and sender and sender.lower() not in allowed:
        problems.append("SIM_SENDER_EMAIL is not in RFQ_ALLOWED_SENDERS, so the bot would skip it.")
    return {"enabled": not problems, "problems": problems, "sender": sender or None, "recipient": bot or None,
            "presets": presets(), "attachment": SAMPLE_ATTACHMENT.name}


def presets():
    result = []
    for preset_id, label, filename in PRESET_FILES:
        message = BytesParser(policy=policy.default).parsebytes((ROOT / "emails" / filename).read_bytes())
        body = message.get_body(preferencelist=("plain",))
        result.append({"id": preset_id, "label": label, "subject": str(message["Subject"]),
                       "body": body.get_content().strip() if body else "",
                       "attach": any(True for _ in message.iter_attachments())})
    return result


def _check_rate():
    now = time.monotonic()
    while _sent_times and now - _sent_times[0] > 3600:
        _sent_times.popleft()
    if _sent_times and now - _sent_times[-1] < MIN_INTERVAL_S:
        raise SimulationError(f"Wait {MIN_INTERVAL_S - int(now - _sent_times[-1])} s before sending another simulation.")
    if len(_sent_times) >= MAX_PER_HOUR:
        raise SimulationError(f"Limit of {MAX_PER_HOUR} simulated emails per hour reached.")


def send(subject, body, attach=False):
    subject = " ".join(str(subject or "").split())
    body = str(body or "").strip()
    if not subject or len(subject) > MAX_SUBJECT:
        raise SimulationError(f"Subject is required (up to {MAX_SUBJECT} characters).")
    if len(body) > MAX_BODY:
        raise SimulationError(f"Body is too long (up to {MAX_BODY} characters).")
    if not body and not attach:
        raise SimulationError("Add product IDs to the body or attach the sample item list.")
    current = config()
    if not current["enabled"]:
        raise SimulationError(" ".join(current["problems"]))
    sender, password, bot = accounts()

    message = EmailMessage()
    message["From"] = sender
    message["To"] = bot  # fixed: only the bot's own inbox
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(idstring="rfq-sim", domain=sender.split("@")[-1])
    message.set_content(body or "Please prepare the RFQ for the items in the attached sheet.")
    if attach:
        message.add_attachment(SAMPLE_ATTACHMENT.read_bytes(), maintype=XLSX[0], subtype=XLSX[1],
                               filename=SAMPLE_ATTACHMENT.name)

    with _lock:
        _check_rate()
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
                smtp.login(sender, password)
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise SimulationError("Gmail rejected SIM_SENDER_EMAIL / SIM_SENDER_PASSWORD; use a 16-letter App Password.") from exc
        _sent_times.append(time.monotonic())
    return {"message_id": message["Message-ID"], "from": sender, "to": bot, "subject": subject,
            "attached": attach, "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
