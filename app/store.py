"""SQLite record of RFQ emails received and RFQs sent, for the dashboard.

Recording is best effort: a database problem is logged and never stops an RFQ or a reply.
"""
import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from app.config import ROOT

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source             TEXT NOT NULL,      -- gmail | file | api
    status             TEXT NOT NULL,      -- processing | built | replied | dry_run | skipped | failed
    message_id         TEXT,
    sender             TEXT,
    subject            TEXT,
    received_at        TEXT,               -- ISO UTC; when the email arrived
    started_at         TEXT,
    finished_at        TEXT,
    replied_at         TEXT,
    scrape_mode        TEXT,
    quality_mode       TEXT,
    products_processed INTEGER,
    products_found     INTEGER,
    products_not_found INTEGER,
    fields_completed   REAL,               -- percent of requested RFQ cells filled
    warnings           INTEGER,
    workbook_path      TEXT,
    reply_message_id   TEXT,
    skip_reason        TEXT,
    error              TEXT
);
CREATE INDEX IF NOT EXISTS requests_received ON requests(received_at);
CREATE TABLE IF NOT EXISTS request_products (
    request_id   INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    product_id   TEXT NOT NULL,
    status       TEXT NOT NULL,            -- Found | Not Found
    description  TEXT,
    fields       INTEGER,                  -- values filled from any source
    from_website INTEGER,
    from_api     INTEGER,
    from_pdf     INTEGER,
    from_catalog INTEGER,
    notes        INTEGER,
    PRIMARY KEY (request_id, position)
);
CREATE TABLE IF NOT EXISTS agent_findings (
    request_id      INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    number          INTEGER NOT NULL,      -- 1-based, as in the Agent Review sheet
    product_id      TEXT NOT NULL,
    field           TEXT NOT NULL,
    verdict         TEXT NOT NULL,         -- inferred | conflict | issue
    severity        TEXT NOT NULL,         -- critical | warning | info
    message         TEXT NOT NULL,
    evidence        TEXT,
    current_value   TEXT,
    proposed_value  TEXT,
    proposed_source TEXT,
    found_by        TEXT,                  -- rules | ai
    decision        TEXT,                  -- NULL | approved | rejected
    decided_at      TEXT,
    PRIMARY KEY (request_id, number)
);
"""
MIGRATIONS = {  # columns added after a database may already exist: (table, column) -> statement
    ("requests", "agent_summary"): "ALTER TABLE requests ADD COLUMN agent_summary TEXT",  # QualityAgent JSON
    ("request_products", "from_api"): "ALTER TABLE request_products ADD COLUMN from_api INTEGER",
}
SOURCE_TYPES = {"ferguson_page": "from_website", "ferguson_api": "from_api", "spec_sheet": "from_pdf",
                "catalog": "from_catalog"}


def db_path():
    return Path(os.getenv("RFQ_DB", ROOT / "out" / "rfq.db"))


def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    for (table, column), statement in MIGRATIONS.items():  # databases created before the column existed
        if column not in {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}:
            connection.execute(statement)
    return connection


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds") if moment else None


def enabled():
    return os.getenv("RFQ_DB", "").lower() != "off"


def safe(action):
    """Run a database write; log and carry on if it fails. RFQ_DB=off disables recording."""
    def wrapper(*args, **kwargs):
        if not enabled():
            return None
        try:
            return action(*args, **kwargs)
        except Exception as exc:
            log.warning("Dashboard database not updated (%s: %s)", type(exc).__name__, exc)
            return None
    return wrapper


def email_fields(message, received=None):
    sender = parseaddr(str(message.get("Reply-To") or message.get("From", "")))[1]
    if received is None and message.get("Date"):
        try:
            received = parsedate_to_datetime(str(message["Date"]))
        except (TypeError, ValueError):
            received = None
    return {"message_id": str(message.get("Message-ID", "")) or None, "sender": sender or None,
            "subject": str(message.get("Subject", "")) or None,
            "received_at": iso(received) or now()}


@safe
def start(source, message, settings, received=None, status="processing"):
    """Record a request when work begins. Returns its id."""
    row = email_fields(message, received)
    with closing(connect()) as db, db:
        if row["message_id"]:
            # A retry of an email that failed earlier reuses its row instead of adding one per poll.
            retry = db.execute("SELECT id FROM requests WHERE source = ? AND message_id = ? AND status = 'failed'",
                               (source, row["message_id"])).fetchone()
            if retry:
                db.execute("UPDATE requests SET status = ?, started_at = ?, error = NULL WHERE id = ?",
                           (status, now(), retry["id"]))
                return retry["id"]
        cursor = db.execute(
            "INSERT INTO requests (source, status, message_id, sender, subject, received_at, started_at,"
            " scrape_mode, quality_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, status, row["message_id"], row["sender"], row["subject"], row["received_at"], now(),
             settings.describe().split(" (")[0], settings.quality))
        return cursor.lastrowid


@safe
def skipped(source, message, reason, received=None):
    row = email_fields(message, received)
    with closing(connect()) as db, db:
        db.execute(
            "INSERT INTO requests (source, status, message_id, sender, subject, received_at, started_at,"
            " finished_at, skip_reason) VALUES (?, 'skipped', ?, ?, ?, ?, ?, ?, ?)",
            (source, row["message_id"], row["sender"], row["subject"], row["received_at"], now(), now(), reason))


def percent(value):
    try:
        return float(str(value).rstrip("%"))
    except (TypeError, ValueError):
        return None


@safe
def built(request_id, result, status="built"):
    """Store the run's metrics and per-product outcome once RFQ.xlsx exists."""
    if not request_id:
        return
    summary = result["summary"]
    with closing(connect()) as db, db:
        db.execute(
            "UPDATE requests SET status = ?, finished_at = ?, products_processed = ?, products_found = ?,"
            " products_not_found = ?, fields_completed = ?, warnings = ?, workbook_path = ? WHERE id = ?",
            (status, now(), summary["Products Processed"], summary["Products Found"], summary["Not Found"],
             percent(summary["Fields Completed"]), summary.get("Warnings / Notes"),
             str(Path(result["workbook"]).resolve()), request_id))
        db.execute("UPDATE requests SET agent_summary = ? WHERE id = ?",
                   (json.dumps(result.get("agent_summary") or {}), request_id))
        db.execute("DELETE FROM agent_findings WHERE request_id = ?", (request_id,))
        for number, finding in enumerate(result.get("findings", []), 1):
            db.execute(
                "INSERT INTO agent_findings (request_id, number, product_id, field, verdict, severity, message,"
                " evidence, current_value, proposed_value, proposed_source, found_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (request_id, number, finding.product_id, finding.field, finding.verdict, finding.severity,
                 finding.message, finding.evidence, finding.current_value, finding.proposed_value or None,
                 finding.proposed_source or None, finding.found_by))
        db.execute("DELETE FROM request_products WHERE request_id = ?", (request_id,))
        for position, product in enumerate(result.get("products", []), 1):
            counts = dict.fromkeys(SOURCE_TYPES.values(), 0)
            for evidence in product.fields.values():
                if evidence.source_type in SOURCE_TYPES:
                    counts[SOURCE_TYPES[evidence.source_type]] += 1
            description = product.fields.get("Description")
            db.execute(
                "INSERT INTO request_products (request_id, position, product_id, status, description, fields,"
                " from_website, from_api, from_pdf, from_catalog, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (request_id, position, product.product_id, "Found" if product.found else "Not Found",
                 description.value if description else None, len(product.fields), counts["from_website"],
                 counts["from_api"], counts["from_pdf"], counts["from_catalog"], len(product.notes)))


@safe
def replied(request_id, reply_message_id):
    if request_id:
        with closing(connect()) as db, db:
            db.execute("UPDATE requests SET status = 'replied', replied_at = ?, reply_message_id = ? WHERE id = ?",
                       (now(), reply_message_id, request_id))


@safe
def failed(request_id, error):
    if request_id:
        with closing(connect()) as db, db:
            db.execute("UPDATE requests SET status = 'failed', finished_at = ?, error = ? WHERE id = ?",
                       (now(), str(error)[:500], request_id))


# ---- Queries for the dashboard -------------------------------------------------------------

def filters(source=None, days=None, table=""):
    prefix = f"{table}." if table else ""
    clauses, params = [], []
    if source:
        clauses.append(f"{prefix}source = ?")
        params.append(source)
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        clauses.append(f"{prefix}received_at >= ?")
        params.append(iso(since))
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


RESPONSE_SECONDS = "(julianday(replied_at) - julianday(received_at)) * 86400"


def metrics(source=None, days=30):
    where, params = filters(source, days)
    with closing(connect()) as db:
        totals = dict(db.execute(f"""
            SELECT COUNT(*)                                             AS received,
                   COALESCE(SUM(status = 'replied'), 0)                 AS replied,
                   COALESCE(SUM(status = 'failed'), 0)                  AS failed,
                   COALESCE(SUM(status = 'skipped'), 0)                 AS skipped,
                   COALESCE(SUM(status IN ('built', 'replied', 'dry_run')), 0) AS built,
                   COALESCE(SUM(products_processed), 0)                 AS products,
                   COALESCE(SUM(products_found), 0)                     AS found,
                   COALESCE(SUM(products_not_found), 0)                 AS not_found,
                   AVG(fields_completed)                                AS fields_completed,
                   AVG(CASE WHEN replied_at IS NOT NULL THEN {RESPONSE_SECONDS} END) AS response_s
            FROM requests{where}""", params).fetchone())
        joined, joined_params = filters(source, days, table="r")
        agent = dict(db.execute(f"""
            SELECT COALESCE(SUM(json_extract(r.agent_summary, '$.values_reviewed')), 0) AS reviewed,
                   COALESCE(SUM(json_extract(r.agent_summary, '$.verified')), 0)        AS verified
            FROM requests r{joined}""", joined_params).fetchone())
        agent.update(dict(db.execute(f"""
            SELECT COALESCE(SUM(f.severity = 'critical' AND f.verdict != 'inferred'), 0)   AS critical,
                   COALESCE(SUM(f.severity = 'warning' AND f.verdict != 'inferred'), 0)    AS warnings,
                   COALESCE(SUM(f.proposed_value IS NOT NULL), 0)                         AS fixes_proposed,
                   COALESCE(SUM(f.decision = 'approved'), 0)                              AS fixes_approved,
                   COALESCE(SUM(f.proposed_value IS NOT NULL AND f.decision IS NULL), 0)  AS fixes_pending
            FROM agent_findings f JOIN requests r ON r.id = f.request_id{joined}""", joined_params).fetchone()))
        sources = dict(db.execute(f"""
            SELECT COALESCE(SUM(p.from_website), 0) AS website, COALESCE(SUM(p.from_api), 0) AS api,
                   COALESCE(SUM(p.from_pdf), 0) AS pdf,
                   COALESCE(SUM(p.from_catalog), 0) AS catalog
            FROM request_products p JOIN requests r ON r.id = p.request_id{joined}""",
            joined_params).fetchone())
        # Days are local dates, matching what the user sees in Gmail.
        start_day = datetime.now().date() - timedelta(days=days - 1)
        daily = {(start_day + timedelta(days=i)).isoformat(): {"received": 0, "replied": 0} for i in range(days)}
        for row in db.execute(f"""
                SELECT date(received_at, 'localtime') AS day, COUNT(*) AS received,
                       SUM(status = 'replied') AS replied
                FROM requests{where} GROUP BY day""", params):
            if row["day"] in daily:
                daily[row["day"]] = {"received": row["received"], "replied": row["replied"] or 0}
    return {"totals": totals, "sources": sources, "agent": agent,
            "daily": [{"day": day, **values} for day, values in daily.items()]}


def requests(source=None, days=30, limit=100, message_id=None):
    where, params = filters(source, days)
    if message_id:
        where += (" AND " if where else " WHERE ") + "message_id = ?"
        params.append(message_id)
    with closing(connect()) as db:
        rows = db.execute(f"""
            SELECT id, source, status, message_id, sender, subject, received_at, replied_at, scrape_mode, quality_mode,
                   products_processed, products_found, products_not_found, fields_completed, warnings,
                   skip_reason, error, workbook_path IS NOT NULL AS has_workbook,
                   CASE WHEN replied_at IS NOT NULL THEN ROUND({RESPONSE_SECONDS}) END AS response_s
            FROM requests{where} ORDER BY received_at DESC, id DESC LIMIT ?""", params + [limit])
        return [dict(row) for row in rows]


def request_detail(request_id):
    with closing(connect()) as db:
        row = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if not row:
            return None
        detail = dict(row)
        detail.pop("workbook_path", None)  # never expose server paths
        detail["has_workbook"] = int(workbook_for(request_id) is not None)
        replied, received = detail.get("replied_at"), detail.get("received_at")
        detail["response_s"] = (round((datetime.fromisoformat(replied) - datetime.fromisoformat(received))
                                      .total_seconds()) if replied and received else None)
        detail["products"] = [dict(p) for p in db.execute(
            "SELECT * FROM request_products WHERE request_id = ? ORDER BY position", (request_id,))]
        detail["findings"] = [dict(f) for f in db.execute(
            "SELECT * FROM agent_findings WHERE request_id = ? ORDER BY CASE severity WHEN 'critical' THEN 0"
            " WHEN 'warning' THEN 1 ELSE 2 END, verdict = 'inferred', number", (request_id,))]
        detail["agent_summary"] = json.loads(detail.get("agent_summary") or "{}")
        detail["has_trace"] = int(trace(request_id) is not None)
        return detail


def output_dir(request_id):
    workbook = workbook_for(request_id)
    return workbook.parent if workbook else None


def trace(request_id):
    folder = output_dir(request_id)
    path = folder / "quality-trace.json" if folder else None
    return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None


def decide(request_id, number, decision):
    """A reviewer approves or rejects a proposed fix; approval regenerates the RFQ workbook."""
    from app.review import decide as apply_decision
    folder = output_dir(request_id)
    if not folder or not (folder / "review-state.json").is_file():
        raise ValueError("This request has no saved review state (it ran before the review agent existed)")
    finding, summary = apply_decision(folder, number, decision)
    with closing(connect()) as db, db:
        db.execute("UPDATE agent_findings SET decision = ?, decided_at = ? WHERE request_id = ? AND number = ?",
                   (decision, now(), request_id, number))
        db.execute("UPDATE requests SET fields_completed = ? WHERE id = ?",
                   (percent(summary["Fields Completed"]), request_id))
    return finding.to_dict()


def workbook_for(request_id):
    """Path of a request's RFQ.xlsx, only if it is inside the project's out/ folder."""
    with closing(connect()) as db:
        row = db.execute("SELECT workbook_path FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not row or not row["workbook_path"]:
        return None
    path = Path(row["workbook_path"]).resolve()
    allowed = (ROOT / "out").resolve()
    return path if path.is_file() and path.is_relative_to(allowed) else None
