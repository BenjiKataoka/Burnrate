// Pure data logic. Field names mirror poller/api.py build_status; the server decides levels.

export type Dir = "max" | "min";
export type Level = "ok" | "warn" | "crit";
export type Point = [number, number];
export const DAY = 86_400;

export interface MetricRow {
  metric: string;
  service: string;
  label: string;
  unit: string;
  dir: Dir;
  value: number | null;
  limit: number;
  pressure: number | null;
  level: Level | null;
  at_limit: string;
  resets_at: number | null;
  updated: number | null;
  stale: boolean;
  support: boolean;
  slope_per_day: number | null;
  days_to_limit: number | null;
}

export interface Status {
  polled_at: number | null;
  next_poll_at: number | null;
  interval_s: number;
  collectors: Record<string, { last_ok: number | null; failing: boolean; error: string | null }>;
  metrics: MetricRow[];
}

function tracked(rows: MetricRow[]): MetricRow[] {
  return rows.filter((r) => !r.support && !r.stale && r.value !== null && r.pressure !== null);
}

export function worst(rows: MetricRow[]): MetricRow | null {
  const t = tracked(rows);
  if (t.length === 0) return null;
  return t.reduce((a, b) => ((b.pressure as number) > (a.pressure as number) ? b : a));
}

export function pct(p: number): number {
  return Math.round(p * 100);
}

export function fmt(v: number): string {
  // Small values keep two significant digits so 0.00037 TB never reads as 0.
  if (v !== 0 && Math.abs(v) < 1) return v.toLocaleString("en-US", { maximumSignificantDigits: 2 });
  return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

export function amount(r: MetricRow): string {
  const v = r.value ?? 0;
  if (r.dir === "min") return `${Math.round(v)}% · floor ${fmt(r.limit)}%`;
  return `${fmt(v)} / ${fmt(r.limit)}${r.unit ? ` ${r.unit}` : ""}`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function ago(seconds: number): string {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < DAY) return plural(Math.round(seconds / 3600), "hour");
  return plural(Math.round(seconds / DAY), "day");
}

export function eta(r: MetricRow, now: number): string {
  if (r.value === null) return "no data yet";
  if (r.stale) return r.updated === null ? "no data yet" : `no data for ${ago(now - r.updated)}, showing last value`;
  if (r.support) return "one of the three idle inputs";
  if (r.level === "crit") return r.dir === "min" ? "below the floor" : "over the limit";
  const edge = r.dir === "min" ? "floor" : "limit";
  if (r.days_to_limit !== null) return `${edge} in about ${plural(Math.max(1, Math.round(r.days_to_limit)), "day")}`;
  if (r.resets_at !== null) return `safe · resets in ${plural(Math.max(1, Math.ceil((r.resets_at - now) / DAY)), "day")}`;
  return r.dir === "min" ? "steady" : "flat";
}

export function consequence(r: MetricRow): string {
  if (!r.at_limit) return "";
  if (r.level === "crit") return `Now: ${r.at_limit}`;
  return `At the ${r.dir === "min" ? "floor" : "limit"}: ${r.at_limit}`;
}

export function byService(rows: MetricRow[]): { service: string; rows: MetricRow[]; pressure: number | null }[] {
  const order: string[] = [];
  const groups = new Map<string, MetricRow[]>();
  for (const r of rows) {
    if (!groups.has(r.service)) {
      groups.set(r.service, []);
      order.push(r.service);
    }
    (groups.get(r.service) as MetricRow[]).push(r);
  }
  return order.map((service) => {
    const members = groups.get(service) as MetricRow[];
    const top = worst(members);
    return { service, rows: members, pressure: top ? top.pressure : null };
  });
}

export function cells(r: MetricRow, n: number, byRisk: boolean): { filled: number; floorAt: number | null } {
  if (r.value === null || r.pressure === null) return { filled: 0, floorAt: null };
  if (r.dir === "min" && !byRisk) {
    // Floors show activity against the floor marker; the widget shows risk for every service.
    return { filled: Math.round((Math.min(100, r.value) / 100) * n), floorAt: r.limit };
  }
  return { filled: Math.min(n, Math.round(r.pressure * n)), floorAt: null };
}

export function trayTitle(status: Status | null): string {
  const w = status ? worst(status.metrics) : null;
  return w ? `${w.service} ${pct(w.pressure as number)}%` : "Burnrate";
}

export function firstPollText(status: Status, now: number): string | null {
  if (status.polled_at !== null) return null;
  if (status.next_poll_at === null) return "Waiting for the first poll";
  return `First poll in about ${Math.max(1, Math.round((status.next_poll_at - now) / 60))} min`;
}

export function orbStyle(p: number): { color: string; speed: number } {
  const color = p < 0.5 ? "#2e2c29" : p < 0.8 ? "#4f4b45" : p < 1 ? "#c4621f" : "#d23a2c";
  return { color, speed: 0.06 + Math.min(1.2, p) * 0.9 };
}

export function widgetOrbStyle(level: Level | null): { color: string; speed: number } {
  // Still and dark unless something needs attention (PRODUCT.md: calm until it matters).
  if (level === "crit") return { color: "#d23a2c", speed: 1.4 };
  if (level === "warn") return { color: "#ff8a2b", speed: 0.8 };
  return { color: "#3a3834", speed: 0 };
}

export interface ChartGeo {
  width: number;
  height: number;
  t0: number;
  t1: number;
  now: number;
  ymin: number;
  ymax: number;
  points: Point[];
  line: string;
  area: string;
  projection: string | null;
  limitY: number;
  x: (t: number) => number;
  y: (v: number) => number;
}

export function chartGeometry(points: Point[], r: MetricRow, days: number, width: number, height: number,
                              now: number): ChartGeo | null {
  const pts = points.filter(([t]) => t > now - days * DAY);
  if (pts.length === 0) return null;
  const t0 = pts[0][0];
  const t1 = now + days * DAY * 0.2; // room for the projection tail
  const vals = pts.map(([, v]) => v);
  const ymax = Math.max(r.limit, ...vals) * 1.12;
  const ymin = Math.max(0, Math.min(r.limit, ...vals) * 0.8);
  const x = (t: number): number => ((t - t0) / (t1 - t0 || 1)) * width;
  const y = (v: number): number => height - ((v - ymin) / (ymax - ymin || 1)) * height;
  const line = pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const last = pts[pts.length - 1];
  const area = `${line}L${x(last[0]).toFixed(1)} ${height}L${x(t0).toFixed(1)} ${height}Z`;
  let projection: string | null = null;
  if (r.slope_per_day !== null) {
    const end = Math.max(ymin, last[1] + (r.slope_per_day * (t1 - now)) / DAY);
    projection = `M${x(now).toFixed(1)} ${y(last[1]).toFixed(1)}L${width.toFixed(1)} ${y(end).toFixed(1)}`;
  }
  return { width, height, t0, t1, now, ymin, ymax, points: pts, line, area, projection, limitY: y(r.limit), x, y };
}

export function readAt(geo: ChartGeo, px: number, r: MetricRow): { t: number; v: number; projected: boolean } {
  const t = geo.t0 + (px / geo.width) * (geo.t1 - geo.t0);
  const last = geo.points[geo.points.length - 1];
  if (t > geo.now && r.slope_per_day !== null) {
    return { t, v: Math.max(0, last[1] + (r.slope_per_day * (t - geo.now)) / DAY), projected: true };
  }
  const nearest = geo.points.reduce((a, b) => (Math.abs(b[0] - t) < Math.abs(a[0] - t) ? b : a));
  return { t: nearest[0], v: nearest[1], projected: false };
}

export function connectionText(result: { kind: string }, lastOkAt: number | null): string | null {
  if (result.kind === "ok") return null;
  if (result.kind === "unauthorized") return "The server rejected the token. Check it in Settings.";
  if (result.kind === "unconfigured") return "Connect Burnrate to your poller in Settings.";
  if (lastOkAt === null) return "Can't reach the server.";
  return `Can't reach the server since ${new Date(lastOkAt * 1000).toTimeString().slice(0, 5)}. Showing the last data.`;
}

export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}
