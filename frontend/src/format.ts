const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat();

/** 1,284 / 12.9K / 4.2M — compact only from 10,000 up so small counts stay exact. */
export function count(value: number | null | undefined): string {
  if (value == null) return "–";
  return Math.abs(value) >= 10_000 ? compact.format(value) : whole.format(value);
}

export function percent(value: number | null | undefined, digits = 0): string {
  return value == null ? "–" : `${value.toFixed(digits)}%`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 90 * 60) return `${(seconds / 60).toFixed(1)} min`;
  if (seconds < 48 * 3600) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} days`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** "2026-10-16" (a local date from the API) → "Oct 16" without a timezone shift. */
export function shortDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function longDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

/** Clean axis ticks: 0, then a 1/2/5 × 10^n step, up to at least `max`. */
export function niceTicks(max: number, target = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? 10 * magnitude;
  const integerStep = Math.max(1, Math.round(step));
  const ticks = [];
  for (let value = 0; value < max + integerStep; value += integerStep) ticks.push(value);
  return ticks;
}
