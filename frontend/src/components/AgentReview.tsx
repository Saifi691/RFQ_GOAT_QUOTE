import { useState } from "react";
import { api, type AgentSummary, type Finding, type TraceStep } from "../api";

const SEVERITY = {
  critical: { label: "Critical", tone: "critical", icon: "!" },
  warning: { label: "Warning", tone: "warning", icon: "!" },
  info: { label: "Info", tone: "neutral", icon: "i" },
} as const;
const VERDICT = { issue: "Issue", conflict: "Source conflict", inferred: "Inferred" };

function Severity({ finding }: { finding: Finding }) {
  const s = SEVERITY[finding.severity];
  return (
    <span className={`status ${s.tone}`}>
      <span className="icon" aria-hidden="true">{s.icon}</span>{s.label}
    </span>
  );
}

function FindingCard({ finding, requestId, onDecided }: {
  finding: Finding; requestId: number; onDecided: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setError("");
    try {
      await api.decide(requestId, finding.number, decision);
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className={`finding ${finding.severity}`}>
      <div className="finding-head">
        <Severity finding={finding} />
        <span className="chip">{VERDICT[finding.verdict]}</span>
        <span className="num"><b>{finding.product_id}</b> · {finding.field}</span>
        <span className="chip" title={finding.found_by === "ai" ? "Found by the AI planner" : "Found by a deterministic check"}>
          {finding.found_by === "ai" ? "AI agent" : "Rule check"}
        </span>
      </div>
      <p className="finding-msg">{finding.message}</p>
      {finding.evidence && <p className="evidence"><span className="muted">Evidence:</span> {finding.evidence}</p>}
      {finding.proposed_value && (
        <div className="proposal">
          <div>
            <span className="muted">Proposed fix:</span>{" "}
            <s>{finding.current_value || "(blank)"}</s> → <b>{finding.proposed_value}</b>
          </div>
          {finding.decision ? (
            <span className={`status ${finding.decision === "approved" ? "good" : "neutral"}`}>
              <span className="icon" aria-hidden="true">{finding.decision === "approved" ? "✓" : "–"}</span>
              {finding.decision === "approved" ? "Approved · RFQ.xlsx regenerated" : "Rejected"}
            </span>
          ) : (
            <div className="proposal-actions">
              <button className="primary" disabled={busy} onClick={() => decide("approve")}>Approve fix</button>
              <button className="ghost" disabled={busy} onClick={() => decide("reject")}>Reject</button>
            </div>
          )}
          {error && <div className="banner" role="alert">{error}</div>}
        </div>
      )}
    </li>
  );
}

function Trace({ requestId }: { requestId: number }) {
  const [steps, setSteps] = useState<TraceStep[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [aiOnly, setAiOnly] = useState(false);
  async function toggle() {
    setOpen(!open);
    if (!steps) api.trace(requestId).then(setSteps).catch((e) => setError(String(e.message ?? e)));
  }
  const shown = (steps ?? []).filter((s) => !aiOnly || s.actor === "ai");
  const aiCount = (steps ?? []).filter((s) => s.actor === "ai").length;
  return (
    <div className="trace">
      <button className="link" onClick={toggle} aria-expanded={open}>
        {open ? "Hide agent trace" : "Show agent trace (every tool call, in order)"}
      </button>
      {open && error && <div className="banner">{error}</div>}
      {open && steps && (
        <>
          {aiCount > 0 && (
            <label className="check small">
              <input type="checkbox" checked={aiOnly} onChange={(e) => setAiOnly(e.target.checked)} />
              {" "}Only the AI planner's {aiCount} steps
            </label>
          )}
          <ol className="trace-list">
            {shown.map((s) => (
              <li key={s.step}>
                <span className="num muted">{s.step}</span>
                <span className={`chip ${s.actor === "ai" ? "chip-ai" : ""}`}>{s.actor === "ai" ? "AI" : "rules"}</span>
                <code>{s.tool}</code>
                <span className="muted trace-args">{typeof s.arguments === "string" ? s.arguments : JSON.stringify(s.arguments)}</span>
                <div className="trace-result">{s.result}</div>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

export function AgentReview({ requestId, findings, summary, hasTrace, onDecided }: {
  requestId: number; findings: Finding[]; summary: AgentSummary; hasTrace: boolean; onDecided: () => void;
}) {
  const [showInferred, setShowInferred] = useState(false);
  const main = findings.filter((f) => f.verdict !== "inferred");
  const inferred = findings.filter((f) => f.verdict === "inferred");
  const reviewed = summary.values_reviewed ?? 0;
  const verifiedPct = reviewed ? Math.round(((summary.verified ?? 0) / reviewed) * 100) : null;
  const pending = findings.filter((f) => f.proposed_value && !f.decision).length;

  return (
    <section className="agent-review" aria-labelledby="agent-title">
      <h2 id="agent-title" style={{ fontSize: 15 }}>Agent review</h2>
      {reviewed === 0 && findings.length === 0 ? (
        <div className="empty">No agent review stored for this request.</div>
      ) : (
        <>
          <div className="agent-stats">
            <div><b>{verifiedPct ?? "–"}%</b><span>values verified at source</span></div>
            <div><b>{summary.inferred ?? 0}</b><span>inferred</span></div>
            <div><b>{summary.conflicts ?? 0}</b><span>source conflicts</span></div>
            <div><b>{summary.issues ?? 0}</b><span>issues</span></div>
            <div><b>{pending}</b><span>fixes awaiting approval</span></div>
          </div>
          {main.length === 0 ? (
            <p className="muted">No issues or conflicts. Every value is verified at source or marked as inferred.</p>
          ) : (
            <ul className="findings">
              {main.map((f) => <FindingCard key={f.number} finding={f} requestId={requestId} onDecided={onDecided} />)}
            </ul>
          )}
          {inferred.length > 0 && (
            <>
              <button className="link" onClick={() => setShowInferred(!showInferred)} aria-expanded={showInferred}>
                {showInferred ? "Hide" : "Show"} {inferred.length} inferred values (not stated for this exact product)
              </button>
              {showInferred && (
                <ul className="findings">
                  {inferred.map((f) => <FindingCard key={f.number} finding={f} requestId={requestId} onDecided={onDecided} />)}
                </ul>
              )}
            </>
          )}
        </>
      )}
      {hasTrace && <Trace requestId={requestId} />}
    </section>
  );
}
