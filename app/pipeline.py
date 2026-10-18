import json
import logging
import os
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path

from app.config import BOT_NAME, MODES, Settings
from app.extract import extract
from app.agent import QualityAgent
from app.lookup import Lookup
from app.quality import check_products
from app.review import save_state
from app.workbook import write_workbook

log = logging.getLogger(__name__)


def make_reply(original, workbook_bytes, summary, sender=None):
    reply = EmailMessage(policy=policy.SMTP)
    reply["From"] = formataddr((BOT_NAME, sender or os.getenv("BOT_EMAIL") or "rfq-agent@example.com"))
    reply["To"] = parseaddr(original.get("Reply-To") or original.get("From", ""))[1]
    subject = str(original.get("Subject", "RFQ request"))
    reply["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
    if original.get("Message-ID"):
        reply["In-Reply-To"] = original["Message-ID"]
        reply["References"] = (str(original.get("References", "")) + " " + str(original["Message-ID"])).strip()
    reply["Date"] = formatdate(localtime=True)
    reply["Message-ID"] = make_msgid()
    reply["Auto-Submitted"] = "auto-replied"
    reply.set_content(
        "Hello,\n\nPlease find the prepared RFQ attached.\n\n"
        f"Products processed: {summary['Products Processed']}\n"
        f"Found: {summary['Products Found']}\nNot Found: {summary['Not Found']}\n\n"
        "Please review the Notes, Sources, and Summary sheets. Blank values are unknown. "
        "Any catalog prices and availability are historical and require confirmation.\n\n" + BOT_NAME + "\n"
    )
    reply.add_attachment(workbook_bytes, maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="RFQ.xlsx")
    return reply


def build(raw, output_dir, settings=None):
    settings = settings or Settings.from_env()
    if settings.quality not in ("rules", "ai"):
        raise ValueError("Quality mode must be rules or ai")
    if settings.mode not in MODES:
        raise ValueError("Scraping mode must be live or background")
    if settings.offline and settings.quality == "ai":
        raise ValueError("Offline mode cannot use AI; select --quality rules")
    if settings.quality == "ai" and not all(os.getenv(k) for k in ("OPENAI_API_KEY", "OPENAI_MODEL")):
        raise ValueError("AI review requires OPENAI_API_KEY and OPENAI_MODEL in .env")
    request = extract(raw)
    log.info("Extracted %d unique product IDs", len(request.ids))
    log.info("Scraping mode: %s", settings.describe())
    request.notes.insert(0, ("run", f"Scraping mode: {settings.describe()}"))
    products = []
    lookup = Lookup(settings)
    try:
        lookup.open()
        if lookup.browser_error:
            request.notes.insert(1, ("run", f"Browser unavailable: {lookup.browser_error}"))
        lookup.prefetch(request.ids)
        if lookup.service and lookup.service.error:
            request.notes.insert(1, ("run", "Ferguson product service unavailable "
                                            f"({lookup.service.error}); used the other sources."))
        for product_id in request.ids:
            log.info("Looking up %s", product_id)
            products.append(lookup.lookup(product_id))
    finally:
        lookup.close()
    trace = check_products(products)
    log.info("Quality agent: checking every value against its source")
    agent = QualityAgent(products)
    agent.run_rules()
    review = ""
    if settings.quality == "ai":
        try:
            log.info("Quality agent: AI investigation (%s)", os.getenv("OPENAI_MODEL"))
            review = agent.run_ai()
        except Exception as exc:
            # Rules-based findings stand; the advisory AI step must not block the reply.
            log.warning("AI review failed (%s); continuing with rules-based findings", type(exc).__name__)
            review = f"AI review FAILED ({type(exc).__name__}: {str(exc)[:200]}); rules-based findings only."
            agent.log_step("ai", "ai_review", {}, review)
    agent_summary = agent.summary()
    log.info("Quality agent: %d verified, %d inferred, %d conflicts, %d issues, %d fixes proposed",
             agent_summary["verified"], agent_summary["inferred"], agent_summary["conflicts"],
             agent_summary["issues"], agent_summary["fixes_proposed"])
    trace = [{**step, "step": number} for number, step in enumerate(trace + agent.trace, 1)]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Generating RFQ.xlsx")
    workbook_path = output_dir / "RFQ.xlsx"
    summary = write_workbook(products, request, workbook_path, settings.quality, review,
                             agent.findings, agent_summary)
    save_state(output_dir, request, products, agent.findings, settings.quality, review, agent_summary)
    reply = make_reply(request.message, workbook_path.read_bytes(), summary)
    (output_dir / "reply.eml").write_bytes(reply.as_bytes())
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "quality-trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")
    return {"workbook": workbook_path, "reply": output_dir / "reply.eml", "summary": summary,
            "products": products, "message": request.message, "findings": agent.findings,
            "agent_summary": agent_summary}
