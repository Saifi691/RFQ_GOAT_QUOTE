import type { RequestRow } from "../api";
import { dateTime, duration, percent } from "../format";
import { StatusLabel } from "./StatusLabel";

const SOURCE_LABEL = { gmail: "Gmail", file: "File", api: "API" };

export function RequestsTable({ rows, selected, onSelect }: {
  rows: RequestRow[]; selected: number | null; onSelect: (id: number) => void;
}) {
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>RFQ requests</h2>
          <p className="sub">Newest first · select a row for its products and the RFQ workbook</p>
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="empty">No requests yet. Run <code>python mailbot.py</code> or <code>python build.py</code>.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Received</th><th>From</th><th>Subject</th><th>Source</th>
                <th className="r">Products</th><th className="r">Not found</th><th className="r">Fields filled</th>
                <th className="r">Response</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className={`clickable${row.id === selected ? " selected" : ""}`}
                  onClick={() => onSelect(row.id)} tabIndex={0}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(row.id)}>
                  <td className="num">{dateTime(row.received_at)}</td>
                  <td className="ellipsis" style={{ maxWidth: 200 }}>{row.sender ?? <span className="muted">–</span>}</td>
                  <td className="ellipsis">{row.subject ?? <span className="muted">(no subject)</span>}</td>
                  <td><span className="chip">{SOURCE_LABEL[row.source]}</span></td>
                  <td className="r">{row.products_processed ?? "–"}</td>
                  <td className="r">{row.products_not_found ?? "–"}</td>
                  <td className="r">{percent(row.fields_completed)}</td>
                  <td className="r">{duration(row.response_s)}</td>
                  <td><StatusLabel status={row.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
