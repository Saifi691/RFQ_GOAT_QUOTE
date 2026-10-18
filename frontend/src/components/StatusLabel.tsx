import type { Status } from "../api";

// Status colour sits on the icon; the label always carries the meaning.
const STATUS: Record<Status, { label: string; tone: string; icon: string }> = {
  replied: { label: "Replied", tone: "good", icon: "✓" },
  built: { label: "Built, not sent", tone: "neutral", icon: "•" },
  dry_run: { label: "Dry run", tone: "neutral", icon: "•" },
  processing: { label: "Processing", tone: "warning", icon: "…" },
  skipped: { label: "Skipped", tone: "neutral", icon: "–" },
  failed: { label: "Failed", tone: "critical", icon: "!" },
};

export function StatusLabel({ status }: { status: Status }) {
  const s = STATUS[status] ?? { label: status, tone: "neutral", icon: "•" };
  return (
    <span className={`status ${s.tone}`}>
      <span className="icon" aria-hidden="true">{s.icon}</span>
      {s.label}
    </span>
  );
}
