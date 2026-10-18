"""Gmail polling with a durable send journal and conservative retry handling."""
import hashlib
import imaplib
import json
import logging
import os
import smtplib
import time
from datetime import datetime, timezone
from pathlib import Path
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr

from app import store
from app.config import Settings
from app.pipeline import build

log = logging.getLogger(__name__)


class FileJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def get(self, key):
        path = self.directory / f"{key}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def claim(self, key):
        try:
            with (self.directory / f"{key}.json").open("x") as file:
                json.dump({"state": "processing"}, file)
            return True
        except FileExistsError:
            return False

    def set(self, key, state):
        path = self.directory / f"{key}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"state": state}))
        temporary.replace(path)

    def release(self, key):
        (self.directory / f"{key}.json").unlink(missing_ok=True)


class BlobJournal:
    """Persistent Azure journal; atomic blob creation claims each email once."""
    def __init__(self, connection_string):
        from azure.storage.blob import BlobServiceClient
        from azure.core.exceptions import ResourceExistsError
        self.client = BlobServiceClient.from_connection_string(connection_string)
        self.container = self.client.get_container_client("rfq-mail-journal")
        try:
            self.container.create_container()
        except ResourceExistsError:
            pass

    def get(self, key):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return json.loads(self.container.download_blob(key).readall())
        except ResourceNotFoundError:
            return None

    def claim(self, key):
        from azure.core.exceptions import ResourceExistsError
        try:
            self.container.upload_blob(key, json.dumps({"state": "processing"}), overwrite=False)
            return True
        except ResourceExistsError:
            return False

    def set(self, key, state):
        self.container.upload_blob(key, json.dumps({"state": state}), overwrite=True)

    def release(self, key):
        self.container.delete_blob(key)


def skip_reason(message, bot_email):
    sender = parseaddr(message.get("From", ""))[1].lower()
    recipient = parseaddr(message.get("Reply-To") or message.get("From", ""))[1].lower()
    if not sender or not recipient:
        return "missing sender/reply address"
    if bot_email.lower() in (sender, recipient):
        return "self message"
    if any(word in sender for word in ("noreply", "no-reply", "mailer-daemon")):
        return "automated sender"
    if message.get("Auto-Submitted", "no").lower() != "no":
        return "automatic message"
    if message.get("Precedence", "").lower() in ("bulk", "list", "junk"):
        return "bulk message"
    allowed = {x.strip().lower() for x in os.getenv("RFQ_ALLOWED_SENDERS", "").split(",") if x.strip()}
    if allowed and (sender not in allowed or recipient not in allowed):
        return "sender/reply address is outside RFQ_ALLOWED_SENDERS"
    return None


def arrived(entry_header):
    """INTERNALDATE (when Gmail received the email) from a FETCH response header, or None."""
    stamp = imaplib.Internaldate2tuple(entry_header)
    return time.mktime(stamp) if stamp else None


def check_inbox(output_dir, settings=None, dry_run=False, journal=None, max_messages=10, since=None, done=None):
    """Answer each RFQ email once.

    Unread RFQ emails are always answered. With `since` (the bot's start time), RFQ emails that
    arrived after it are answered even if someone already opened them in Gmail; the send journal,
    not the read flag, guarantees a single reply.

    `max_messages` limits how many new emails are processed per check; emails already answered or
    skipped do not count toward it. `done` (a set kept by a long-running caller) remembers finished
    email UIDs so they are not downloaded again on every check.
    """
    settings = settings or Settings.from_env()
    address = os.getenv("BOT_EMAIL", "").strip()
    password = os.getenv("BOT_PASSWORD", "").replace(" ", "")
    if not address or not password:
        raise ValueError("Set BOT_EMAIL and BOT_PASSWORD in .env before running the inbox bot")
    output_dir = Path(output_dir)
    journal = journal or FileJournal(output_dir / "mail-journal")
    sent = 0
    with imaplib.IMAP4_SSL("imap.gmail.com", timeout=30) as inbox:
        inbox.login(address, password)
        status, _ = inbox.select("INBOX", readonly=dry_run)
        if status != "OK":
            raise RuntimeError("Cannot select Gmail inbox")
        criteria = ["UNSEEN"]
        if since:
            # IMAP SINCE is by day; the exact arrival time is checked per email below.
            criteria = ["OR", "UNSEEN", "SINCE", time.strftime("%d-%b-%Y", time.localtime(since))]
        status, data = inbox.uid("SEARCH", None, *criteria, "SUBJECT", '"RFQ"')
        if status != "OK":
            raise RuntimeError("Gmail search failed")
        done = done if done is not None else set()
        attempted = 0
        for uid in (data[0] or b"").split():
            if uid in done:
                continue
            if attempted >= max_messages:
                log.info("More new RFQ emails waiting; they will be handled on the next check")
                break
            status, fetched = inbox.uid("FETCH", uid, "(FLAGS INTERNALDATE BODY.PEEK[])")
            if status != "OK":
                continue
            entry = next((e for e in fetched if isinstance(e, tuple)), None)
            if not entry or not entry[1]:
                continue
            header, raw = entry
            received = arrived(header)
            if b"\\Seen" in header:
                # Read before the bot started: someone already handled it, leave it alone.
                if not since or received is None or received < since:
                    done.add(uid)
                    continue
            key = hashlib.sha256(address.lower().encode() + b"\0" + raw).hexdigest()
            previous = journal.get(key)
            if previous and previous["state"] == "skipped":
                done.add(uid)
                continue
            message = BytesParser(policy=policy.default).parsebytes(raw)
            arrival = datetime.fromtimestamp(received, timezone.utc) if received else None
            reason = skip_reason(message, address)
            if reason:
                log.info("Skipped email: %s", reason)
                if not dry_run:
                    journal.set(key, "skipped")
                    store.skipped("gmail", message, reason, arrival)
                done.add(uid)
                continue
            if previous and previous["state"] == "sent":
                if not dry_run:
                    inbox.uid("STORE", uid, "+FLAGS", r"(\Seen)")
                done.add(uid)
                continue
            if previous:
                log.warning("Email %s has journal state %s; inspect before retrying", key[:12], previous["state"])
                done.add(uid)  # needs a person; warn once per run, not every 30 s
                continue
            log.info("New email found (%s): %s", key[:12], message.get("Subject", ""))
            attempted += 1
            if not dry_run and not journal.claim(key):
                continue
            sending = False
            request_id = store.start("gmail", message, settings, arrival)
            try:
                log.info("Running RFQ workflow")
                result = build(raw, output_dir / key, settings)
                store.built(request_id, result, status="dry_run" if dry_run else "built")
                if dry_run:
                    log.info("Dry run: reply saved at %s; inbox unchanged", result["reply"])
                    done.add(uid)
                    continue
                reply = BytesParser(policy=policy.default).parsebytes(result["reply"].read_bytes())
                del reply["Message-ID"]
                reply["Message-ID"] = f"<rfq-{key}@{address.split('@')[-1]}>"
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
                    smtp.login(address, password)
                    journal.set(key, "sending")
                    sending = True
                    smtp.send_message(reply)
                    journal.set(key, "sent")
                store.replied(request_id, reply["Message-ID"])
                inbox.uid("STORE", uid, "+FLAGS", r"(\Seen)")
                done.add(uid)
                sent += 1
                log.info("Reply sent")
            except Exception as exc:
                store.failed(request_id, f"{type(exc).__name__}: {exc}")
                if not dry_run and not sending:
                    journal.release(key)
                log.error("Email %s failed (%s). %s", key[:12], type(exc).__name__,
                          "Check Sent mail before resetting journal state." if sending else "Will retry next poll.")
    return sent
