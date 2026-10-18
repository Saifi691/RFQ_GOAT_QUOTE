"""Azure Functions v2: authenticated RFQ endpoint and optional Gmail timer."""
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import azure.functions as func

# The dashboard database is local-only; the Azure app folder is read-only and has no dashboard.
os.environ.setdefault("RFQ_DB", "off")

from app.config import Settings
from app.extract import MAX_EMAIL_BYTES
from app.pipeline import build

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="healthz", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def healthz(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"status": "ok", "service": "FERG_GOAT_QUOTE"}), mimetype="application/json")


@app.route(route="rfq", methods=["POST"])
def rfq(req: func.HttpRequest) -> func.HttpResponse:
    raw = req.get_body()
    if len(raw) > MAX_EMAIL_BYTES:
        return func.HttpResponse("Email exceeds 15 MB", status_code=413)
    settings = Settings.from_env()
    settings.browser = False
    if req.params.get("offline", "false").lower() == "true":
        settings.offline = True
        settings.quality = "rules"
    try:
        with TemporaryDirectory(prefix="rfq-") as directory:
            result = build(raw, directory, settings)
            return func.HttpResponse(result["workbook"].read_bytes(),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="RFQ.xlsx"'})
    except ValueError as exc:
        return func.HttpResponse(str(exc), status_code=400)
    except Exception:
        logging.exception("RFQ processing failed")
        return func.HttpResponse("RFQ processing failed; see application logs", status_code=500)


@app.timer_trigger(schedule="*/30 * * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def poll_gmail(timer: func.TimerRequest):
    if os.getenv("RFQ_MAIL_ENABLED", "false").lower() != "true":
        return
    from app.mailbox import BlobJournal, check_inbox
    connection = os.getenv("RFQ_STORAGE_CONNECTION") or os.getenv("AzureWebJobsStorage")
    if not connection:
        raise ValueError("Gmail timer requires RFQ_STORAGE_CONNECTION for its durable send journal")
    settings = Settings.from_env()
    settings.browser = False
    with TemporaryDirectory(prefix="rfq-mail-") as directory:
        check_inbox(Path(directory), settings, journal=BlobJournal(connection), max_messages=3)
