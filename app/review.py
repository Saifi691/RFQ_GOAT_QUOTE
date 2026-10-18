"""Human approval of the review agent's proposed fixes.

Each run saves `review-state.json` beside RFQ.xlsx: the products with their evidence, the agent's
findings and summary. Approving a proposal writes the value into the RFQ with source type
`agent_fix` (citing the evidence and the approval time) and regenerates RFQ.xlsx; the workbook as
first produced is kept as RFQ-original.xlsx. Rejecting only records the decision.
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.models import Evidence, Finding, Product
from app.workbook import write_workbook

STATE = "review-state.json"


def save_state(output_dir, request, products, findings, mode, review, agent_summary):
    state = {
        "request": {"ids": request.ids, "origins": request.origins, "notes": request.notes},
        "products": [p.to_dict() for p in products],
        "findings": [f.to_dict() for f in findings],
        "mode": mode, "review": review, "agent_summary": agent_summary,
    }
    (Path(output_dir) / STATE).write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")


def load_state(output_dir):
    state = json.loads((Path(output_dir) / STATE).read_text(encoding="utf-8"))
    request = SimpleNamespace(ids=state["request"]["ids"], origins=state["request"]["origins"],
                              notes=[tuple(n) for n in state["request"]["notes"]])
    products = [Product.from_dict(p) for p in state["products"]]
    findings = [Finding(**f) for f in state["findings"]]
    return state, request, products, findings


def decide(output_dir, number, decision):
    """Approve or reject finding `number` (1-based). Returns the updated finding and summary."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    output_dir = Path(output_dir)
    state, request, products, findings = load_state(output_dir)
    if not 1 <= number <= len(findings):
        raise ValueError("Unknown finding")
    finding = findings[number - 1]
    if not finding.proposed_value:
        raise ValueError("This finding has no proposed fix to approve or reject")
    if finding.decision:
        raise ValueError(f"Already {finding.decision}")
    finding.decision = decision
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if decision == "approved":
        product = next(p for p in products if p.product_id == finding.product_id)
        before = product.fields.get(finding.field)
        product.fields[finding.field] = Evidence(
            finding.proposed_value, "agent_fix",
            f"Reviewer approved agent proposal on {stamp}; evidence: {finding.proposed_source}", "high")
        product.notes.append(f"Reviewer approved fix: {finding.field} "
                             f"{before.value if before else '(blank)'!r} -> {finding.proposed_value!r}.")
        original = output_dir / "RFQ-original.xlsx"
        if not original.exists():
            shutil.copyfile(output_dir / "RFQ.xlsx", original)
    summary = write_workbook(products, request, output_dir / "RFQ.xlsx", state["mode"], state["review"],
                             findings, state["agent_summary"])
    state.update(products=[p.to_dict() for p in products], findings=[f.to_dict() for f in findings])
    (output_dir / STATE).write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")
    return finding, summary
