import type { AgentTotals, Totals } from "../api";
import { count, duration, percent } from "../format";

function Tile({ label, value, hint, hero, meter }: {
  label: string; value: string; hint?: string; hero?: boolean; meter?: number | null;
}) {
  return (
    <div className={`card tile${hero ? " hero" : ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {meter != null && (
        <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(meter)}
          aria-label={label}>
          <div style={{ width: `${Math.min(100, Math.max(0, meter))}%` }} />
        </div>
      )}
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function Tiles({ totals, agent }: { totals: Totals; agent: AgentTotals }) {
  const foundRate = totals.products ? (totals.found / totals.products) * 100 : null;
  const handled = totals.received - totals.skipped;
  return (
    <>
      <div className="tiles">
        <Tile hero label="RFQs sent" value={count(totals.replied)}
          hint={`${count(handled)} RFQ emails handled · ${count(totals.received)} received in total`} />
        <Tile label="Emails received" value={count(totals.received)}
          hint={totals.skipped ? `${count(totals.skipped)} skipped (automated or own address)` : "All were RFQ requests"} />
        <Tile label="Products processed" value={count(totals.products)}
          hint={`${count(totals.found)} found · ${count(totals.not_found)} not found`} />
        <Tile label="Avg response time" value={duration(totals.response_s)} hint="Email arrival to reply sent" />
      </div>
      <div className="tiles tiles-row2 tiles-4">
        <Tile label="Products found" value={percent(foundRate)} meter={foundRate}
          hint="Competitor and unknown codes count as not found" />
        <Tile label="RFQ fields filled" value={percent(totals.fields_completed)} meter={totals.fields_completed}
          hint="Blank means unknown; values are never guessed" />
        <Tile label="Values verified by the agent" value={percent(agent.reviewed ? (agent.verified / agent.reviewed) * 100 : null)}
          meter={agent.reviewed ? (agent.verified / agent.reviewed) * 100 : null}
          hint={`${count(agent.critical)} critical · ${count(agent.warnings)} warnings · ${count(agent.fixes_pending)} fixes awaiting approval`} />
        <Tile label="Needs attention" value={count(totals.failed)}
          hint={totals.failed ? "Failed requests; open them below for the error" : "No failed requests"} />
      </div>
    </>
  );
}
