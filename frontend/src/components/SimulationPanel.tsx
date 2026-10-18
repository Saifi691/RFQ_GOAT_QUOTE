import { useEffect, useState } from "react";
import { api, type RequestRow, type SimulationConfig, type SimulationSent } from "../api";
import { duration } from "../format";

interface Tracked extends SimulationSent {
  sentLocal: number; // ms timestamp, for elapsed time
  row: RequestRow | null;
}

const FINAL = new Set(["replied", "failed", "skipped", "dry_run"]);
const STALE_MS = 90_000; // no pickup after this: the bot is probably not running
const POLL_MS = 4000;

type StepState = "done" | "active" | "todo" | "error";

function steps(t: Tracked, now: number): { label: string; state: StepState; detail?: string }[] {
  const row = t.row;
  const status = row?.status;
  const stale = !row && now - t.sentLocal > STALE_MS;
  const built = !!row && (row.products_processed != null || status === "replied");
  return [
    { label: "Email sent to the bot", state: "done", detail: `${t.from} → ${t.to}` },
    {
      label: "Picked up by the bot",
      state: row ? "done" : stale ? "error" : "active",
      detail: row ? undefined : stale ? "Not picked up yet. Is python mailbot.py running?" : "Waiting for the next inbox check (every 30 s)",
    },
    {
      label: status === "skipped" ? "Skipped by the bot" : "RFQ workbook built",
      state: status === "skipped" ? "error" : built ? "done" : status === "failed" ? "error" : row ? "active" : "todo",
      detail: status === "skipped" ? row?.skip_reason ?? undefined
        : built ? `${row?.products_processed} products · ${row?.products_not_found} not found` : undefined,
    },
    {
      label: status === "dry_run" ? "Dry run: reply not sent" : "Reply sent with RFQ.xlsx",
      state: status === "replied" ? "done" : status === "failed" ? "error" : built && !FINAL.has(status ?? "") ? "active" : "todo",
      detail: status === "replied" ? `Response time ${duration(row?.response_s)}`
        : status === "failed" ? row?.error ?? "Failed" : undefined,
    },
  ];
}

export function SimulationPanel({ onOpen }: { onOpen: (id: number) => void }) {
  const [config, setConfig] = useState<SimulationConfig | null>(null);
  const [configError, setConfigError] = useState("");
  const [presetId, setPresetId] = useState("email-1");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [attach, setAttach] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  // Kept for this browser tab, so a refresh does not lose the live tracking.
  const [tracked, setTracked] = useState<Tracked[]>(() => {
    try { return JSON.parse(sessionStorage.getItem("simulations") ?? "[]"); } catch { return []; }
  });
  useEffect(() => sessionStorage.setItem("simulations", JSON.stringify(tracked)), [tracked]);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    api.simulationConfig().then((c) => {
      setConfig(c);
      const first = c.presets[0];
      if (first) { setSubject(first.subject); setBody(first.body); setAttach(first.attach); }
    }).catch((e) => setConfigError(String(e.message ?? e)));
  }, []);

  // Follow every simulated email until the bot reaches a final state.
  useEffect(() => {
    const timer = window.setInterval(async () => {
      setNow(Date.now());
      const open = tracked.filter((t) => !FINAL.has(t.row?.status ?? ""));
      if (!open.length) return;
      const byId = await Promise.all(open.map((t) => api.byMessageId(t.message_id).catch(() => [])));
      // Fallback if the mail service rewrote the Message-ID: same sender and subject, received after sending.
      const recent = byId.some((rows) => !rows.length) ? await api.requests("gmail", 1).catch(() => []) : [];
      const match = (t: Tracked, i: number) => byId[i][0] ?? recent.find((r) =>
        r.sender?.toLowerCase() === t.from.toLowerCase() && r.subject === t.subject &&
        new Date(r.received_at).getTime() >= t.sentLocal - 120_000) ?? null;
      setTracked((list) => list.map((t) => {
        const index = open.findIndex((o) => o.message_id === t.message_id);
        const row = index >= 0 ? match(open[index], index) : null;
        return row ? { ...t, row } : t;
      }));
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [tracked]);

  function choose(id: string) {
    setPresetId(id);
    const preset = config?.presets.find((p) => p.id === id);
    if (preset) { setSubject(preset.subject); setBody(preset.body); setAttach(preset.attach); }
  }

  async function send() {
    setSending(true);
    setError("");
    try {
      const sent = await api.simulate(subject, body, attach);
      setTracked((list) => [{ ...sent, sentLocal: Date.now(), row: null }, ...list].slice(0, 6));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  const disabled = !config?.enabled;
  const noRfq = !/rfq/i.test(subject);

  return (
    <section className="card sim" aria-labelledby="sim-title">
      <div className="card-head">
        <div>
          <h2 id="sim-title">Simulate an RFQ email</h2>
          <p className="sub">
            Sends a real email from the test sender to the bot's inbox. Keep <code>python mailbot.py</code> running
            to see it answered.
          </p>
        </div>
      </div>

      {configError && <div className="banner">{configError}</div>}
      {config && !config.enabled && (
        <div className="banner" role="alert">
          <b>Simulation is not set up yet.</b>
          <ul>{config.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          Then restart <code>python dashboard.py</code>.
        </div>
      )}

      <div className="sim-grid">
        <form className="sim-form" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <div className="sim-route">
            <span><span className="muted">From</span> {config?.sender ?? "–"}</span>
            <span aria-hidden="true">→</span>
            <span><span className="muted">To (bot)</span> {config?.recipient ?? "–"}</span>
          </div>
          <label>
            <span>Start from a sample</span>
            <select value={presetId} onChange={(e) => choose(e.target.value)} disabled={disabled}>
              {config?.presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </label>
          <label>
            <span>Subject</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200} disabled={disabled} />
          </label>
          {noRfq && <p className="warn-text">The bot only answers emails with "RFQ" in the subject.</p>}
          <label>
            <span>Body (product IDs anywhere in the text)</span>
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={9} maxLength={20000} disabled={disabled} />
          </label>
          <label className="check">
            <input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)} disabled={disabled} />
            Attach the sample item list ({config?.attachment ?? "rfq_items.xlsx"}, 8 IDs)
          </label>
          {error && <div className="banner" role="alert">{error}</div>}
          <div>
            <button className="primary" type="submit" disabled={disabled || sending || !subject.trim()}>
              {sending ? "Sending…" : "Send to bot"}
            </button>
          </div>
        </form>

        <div className="sim-track" aria-live="polite">
          <h3>Live tracking</h3>
          {tracked.length === 0 && <div className="empty">Sent simulations appear here and update every few seconds.</div>}
          {tracked.map((t) => (
            <div className="sim-item" key={t.message_id}>
              <div className="sim-item-head">
                <b className="ellipsis" title={t.subject}>{t.subject}</b>
                <span className="muted num">{duration((now - t.sentLocal) / 1000)} ago</span>
              </div>
              <ol className="timeline">
                {steps(t, now).map((s) => (
                  <li key={s.label} className={s.state}>
                    <span className="dot" aria-hidden="true">{s.state === "done" ? "✓" : s.state === "error" ? "!" : ""}</span>
                    <div>
                      <div>{s.label}<span className="sr-only"> ({s.state})</span></div>
                      {s.detail && <div className="muted small">{s.detail}</div>}
                    </div>
                  </li>
                ))}
              </ol>
              {t.row && <button className="link" onClick={() => onOpen(t.row!.id)}>Open request #{t.row.id}</button>}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
