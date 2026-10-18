import { useEffect, useState } from "react";
import { api, type RequestDetail } from "../api";
import { dateTime, duration, percent } from "../format";
import { AgentReview } from "./AgentReview";
import { StatusLabel } from "./StatusLabel";

export function RequestDrawer({ id, refreshKey, onClose }: { id: number; refreshKey: number; onClose: () => void }) {
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let current = true;
    api.request(id).then((d) => current && (setDetail(d), setError(""))).catch((e) => current && setError(String(e.message ?? e)));
    return () => { current = false; };
  }, [id, refreshKey, reload]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="RFQ request details">
        <div className="card-head">
          <div>
            <h2>{detail?.subject ?? "RFQ request"}</h2>
            <p className="sub">Request #{id}</p>
          </div>
          <button className="ghost" onClick={onClose} aria-label="Close details">Close</button>
        </div>
        {error && <div className="banner">{error}</div>}
        {detail && (
          <>
            <StatusLabel status={detail.status} />
            <dl className="meta">
              <dt>From</dt><dd>{detail.sender ?? "–"}</dd>
              <dt>Received</dt><dd>{dateTime(detail.received_at)}</dd>
              <dt>Reply sent</dt><dd>{dateTime(detail.replied_at)}{detail.response_s != null && ` (${duration(detail.response_s)})`}</dd>
              <dt>Scraping mode</dt><dd>{detail.scrape_mode ?? "–"}</dd>
              <dt>Quality check</dt><dd>{detail.quality_mode ?? "–"}</dd>
              <dt>Fields filled</dt><dd>{percent(detail.fields_completed)} · {detail.warnings ?? 0} notes</dd>
              {detail.skip_reason && (<><dt>Skipped because</dt><dd>{detail.skip_reason}</dd></>)}
              {detail.error && (<><dt>Error</dt><dd>{detail.error}</dd></>)}
            </dl>
            {detail.has_workbook ? (
              <div className="drawer-actions">
                <a className="primary" href={api.workbookUrl(id)} download>Download RFQ.xlsx</a>
              </div>
            ) : null}
            <AgentReview requestId={id} findings={detail.findings ?? []} summary={detail.agent_summary ?? {}}
              hasTrace={!!detail.has_trace} onDecided={() => setReload((n) => n + 1)} />
            <h2 style={{ fontSize: 15 }}>Products ({detail.products.length})</h2>
            {detail.products.length === 0 ? (
              <div className="empty">No products recorded for this request.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th className="r">#</th><th>Product ID</th><th>Description</th><th>Status</th>
                      <th className="r">Values</th><th className="r">Website</th><th className="r">Service</th><th className="r">PDF</th>
                      <th className="r">Catalog</th><th className="r">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.products.map((p) => (
                      <tr key={p.position}>
                        <td className="r">{p.position}</td>
                        <td className="num">{p.product_id}</td>
                        <td>{p.description ?? <span className="muted">–</span>}</td>
                        <td>
                          <span className={`status ${p.status === "Found" ? "good" : "critical"}`}>
                            <span className="icon" aria-hidden="true">{p.status === "Found" ? "✓" : "?"}</span>{p.status}
                          </span>
                        </td>
                        <td className="r">{p.fields}</td>
                        <td className="r">{p.from_website}</td>
                        <td className="r">{p.from_api ?? 0}</td>
                        <td className="r">{p.from_pdf}</td>
                        <td className="r">{p.from_catalog}</td>
                        <td className="r">{p.notes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </aside>
    </>
  );
}
