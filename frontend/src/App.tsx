import { useCallback, useEffect, useState } from "react";
import { api, type Metrics, type RequestRow, type Source } from "./api";
import { DailyChart } from "./components/DailyChart";
import { RequestDrawer } from "./components/RequestDrawer";
import { RequestsTable } from "./components/RequestsTable";
import { SimulationPanel } from "./components/SimulationPanel";
import { SourceChart } from "./components/SourceChart";
import { Tiles } from "./components/Tiles";

const SOURCES: { value: Source; label: string }[] = [
  { value: "", label: "All" }, { value: "gmail", label: "Gmail" },
  { value: "file", label: "File runs" }, { value: "api", label: "API" },
];
const RANGES = [7, 14, 30, 90];
const REFRESH_MS = 5000;
type Theme = "system" | "light" | "dark";

export default function App() {
  const [source, setSource] = useState<Source>("");
  const [days, setDays] = useState(14);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [rows, setRows] = useState<RequestRow[]>([]);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState<Date | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  // Closed by default; remembers the user's choice across refreshes.
  const [showSim, setShowSim] = useState(() => localStorage.getItem("showSimulation") === "true");
  useEffect(() => localStorage.setItem("showSimulation", String(showSim)), [showSim]);
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("theme") as Theme) || "system");

  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  const load = useCallback(async () => {
    try {
      const [m, r] = await Promise.all([api.metrics(source, days), api.requests(source, days)]);
      setMetrics(m);
      setRows(r);
      setError("");
      setUpdated(new Date());
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError(`Cannot reach the dashboard API (${e instanceof Error ? e.message : e}). Is "python dashboard.py" running?`);
    }
  }, [source, days]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const closeDrawer = useCallback(() => setSelected(null), []);

  return (
    <>
    <header className="brandbar">
      <div className="topbar">
        <div>
          <h1><span className="brand-mark">FERGUSON</span>FERG_GOAT_QUOTE</h1>
          <p>RFQ emails received, workbooks built and replies sent</p>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <span className="live" aria-live="polite">
            <span className={`live-dot${error ? " off" : ""}`} aria-hidden="true" />
            {error ? "Offline" : updated ? `Live · updated ${updated.toLocaleTimeString()}` : "Connecting…"}
          </span>
          <button className="ghost" onClick={() => setTheme(theme === "dark" ? "light" : theme === "light" ? "system" : "dark")}
            title="Switch colour theme">
            Theme: {theme}
          </button>
        </div>
      </div>
    </header>
    <div className="shell">
      <div className="filters" role="toolbar" aria-label="Filters">
        <div className="segmented" aria-label="Source">
          {SOURCES.map((s) => (
            <button key={s.value} aria-pressed={source === s.value} onClick={() => setSource(s.value)}>{s.label}</button>
          ))}
        </div>
        <div className="segmented" aria-label="Date range">
          {RANGES.map((d) => (
            <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>Last {d} days</button>
          ))}
        </div>
        <button className="ghost" style={{ marginLeft: "auto" }} aria-expanded={showSim}
          onClick={() => setShowSim(!showSim)}>
          {showSim ? "Hide simulation" : "Simulate an RFQ email"}
        </button>
      </div>

      {showSim && <SimulationPanel onOpen={setSelected} />}

      {error && <div className="banner" role="alert">{error}</div>}

      {metrics && (
        <>
          <Tiles totals={metrics.totals} agent={metrics.agent} />
          <div className="grid-2">
            <DailyChart data={metrics.daily} />
            <SourceChart sources={metrics.sources} />
          </div>
          <RequestsTable rows={rows} selected={selected} onSelect={setSelected} />
        </>
      )}

      {selected != null && <RequestDrawer id={selected} refreshKey={refreshKey} onClose={closeDrawer} />}
    </div>
    </>
  );
}
