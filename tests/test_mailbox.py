from email.message import EmailMessage

from app.mailbox import FileJournal, check_inbox, skip_reason


def test_skip_auto_and_self():
    msg = EmailMessage()
    msg['From'] = 'bot@example.com'
    assert skip_reason(msg, 'bot@example.com') == 'self message'
    msg.replace_header('From', 'buyer@example.com')
    msg['Auto-Submitted'] = 'auto-replied'
    assert skip_reason(msg, 'bot@example.com') == 'automatic message'


def test_journal_claim_and_persistence(tmp_path):
    journal = FileJournal(tmp_path)
    assert journal.claim('key')
    assert not journal.claim('key')
    journal.set('key', 'sent')
    assert FileJournal(tmp_path).get('key') == {'state': 'sent'}


def test_bot_sends_once_and_marks_read_after_send(tmp_path, monkeypatch):
    import app.mailbox as mailbox
    from app.config import ROOT, Settings
    raw = (ROOT / 'emails/email-1-ids-in-body.eml').read_bytes()
    events = []

    class Inbox:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def select(self, *args, **kwargs): return 'OK', []
        def uid(self, command, *args):
            if command == 'SEARCH': return 'OK', [b'1']
            if command == 'FETCH': return 'OK', [(b'1', raw)]
            if command == 'STORE': events.append('read'); return 'OK', []

    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, message):
            assert message['In-Reply-To'] == '<rfq-sample-1@sourcing.example.com>'
            assert next(message.iter_attachments()).get_filename() == 'RFQ.xlsx'
            events.append('sent')

    monkeypatch.setenv('BOT_EMAIL', 'bot@example.com')
    monkeypatch.setenv('BOT_PASSWORD', 'test')
    monkeypatch.delenv('RFQ_ALLOWED_SENDERS', raising=False)
    monkeypatch.setattr(mailbox.imaplib, 'IMAP4_SSL', Inbox)
    monkeypatch.setattr(mailbox.smtplib, 'SMTP_SSL', SMTP)
    assert check_inbox(tmp_path, Settings(offline=True)) == 1
    assert check_inbox(tmp_path, Settings(offline=True)) == 0
    assert events == ['sent', 'read', 'read']

    events.clear()
    check_inbox(tmp_path / 'dry', Settings(offline=True), dry_run=True)
    assert events == []

    def fail_send(self, message):
        events.append('attempt')
        raise TimeoutError('SMTP result uncertain')
    monkeypatch.setattr(SMTP, 'send_message', fail_send)
    check_inbox(tmp_path / 'uncertain', Settings(offline=True))
    check_inbox(tmp_path / 'uncertain', Settings(offline=True))
    assert events == ['attempt']


def test_email_opened_in_gmail_after_start_is_still_answered(tmp_path, monkeypatch):
    import time
    import app.mailbox as mailbox
    from app.config import ROOT, Settings
    raw = (ROOT / 'emails/email-1-ids-in-body.eml').read_bytes()
    started = time.time()
    def header(seconds_after_start):
        stamp = time.strftime('%d-%b-%Y %H:%M:%S +0000', time.gmtime(started + seconds_after_start))
        return f'1 (UID 1 FLAGS (\\Seen) INTERNALDATE "{stamp}" BODY[] {{{len(raw)}}}'.encode()
    sent = []

    class Inbox:
        arrival = 60
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def select(self, *args, **kwargs): return 'OK', []
        def uid(self, command, *args):
            if command == 'SEARCH': return 'OK', [b'1']
            if command == 'FETCH': return 'OK', [(header(Inbox.arrival), raw)]
            return 'OK', []

    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, message): sent.append(message)

    monkeypatch.setenv('BOT_EMAIL', 'bot@example.com')
    monkeypatch.setenv('BOT_PASSWORD', 'test')
    monkeypatch.delenv('RFQ_ALLOWED_SENDERS', raising=False)
    monkeypatch.setattr(mailbox.imaplib, 'IMAP4_SSL', Inbox)
    monkeypatch.setattr(mailbox.smtplib, 'SMTP_SSL', SMTP)
    # Already opened in Gmail, but arrived after the bot started: answered once.
    assert check_inbox(tmp_path, Settings(offline=True), since=started) == 1
    assert check_inbox(tmp_path, Settings(offline=True), since=started) == 0
    # Opened before the bot started: left alone.
    Inbox.arrival = -3600
    assert check_inbox(tmp_path / 'old', Settings(offline=True), since=started) == 0
    assert len(sent) == 1


def test_new_email_found_behind_many_answered_ones(tmp_path, monkeypatch):
    """Regression: 10+ answered RFQs today used to hide every newer email from the bot."""
    import app.mailbox as mailbox
    from app.config import ROOT, Settings
    from app.mailbox import FileJournal
    import hashlib
    raw = (ROOT / 'emails/email-1-ids-in-body.eml').read_bytes()
    old = [raw.replace(b'rfq-sample-1@', f'old-{i}@'.encode()) for i in range(12)]
    new = raw.replace(b'rfq-sample-1@', b'new@')
    mail = {str(i).encode(): body for i, body in enumerate(old + [new], 1)}
    journal = FileJournal(tmp_path / 'mail-journal')
    for body in old:  # already answered earlier today
        journal.set(hashlib.sha256(b'bot@example.com\0' + body).hexdigest(), 'sent')
    sent, fetched = [], []

    class Inbox:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def select(self, *args, **kwargs): return 'OK', []
        def uid(self, command, *args):
            if command == 'SEARCH': return 'OK', [b' '.join(mail)]
            if command == 'FETCH':
                fetched.append(args[0])
                return 'OK', [(args[0] + b' (UID)', mail[args[0]])]
            return 'OK', []

    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, message): sent.append(message['In-Reply-To'])

    monkeypatch.setenv('BOT_EMAIL', 'bot@example.com')
    monkeypatch.setenv('BOT_PASSWORD', 'test')
    monkeypatch.delenv('RFQ_ALLOWED_SENDERS', raising=False)
    monkeypatch.setattr(mailbox.imaplib, 'IMAP4_SSL', Inbox)
    monkeypatch.setattr(mailbox.smtplib, 'SMTP_SSL', SMTP)
    done = set()
    assert check_inbox(tmp_path, Settings(offline=True), done=done) == 1
    assert sent == ['<new@sourcing.example.com>']
    fetched.clear()
    assert check_inbox(tmp_path, Settings(offline=True), done=done) == 0
    assert fetched == []  # finished emails are not downloaded again
