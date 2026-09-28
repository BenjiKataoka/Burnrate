import { chartGeometry, eta, fmt, readAt, type MetricRow, type Point } from "./model.ts";

const NS = "http://www.w3.org/2000/svg";
const COLOUR: Record<string, string> = { ok: "#ece8e1", warn: "#ff8a2b", crit: "#ff4d3d" };

function el(name: string, attrs: Record<string, string | number>): SVGElement {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

export function renderChart(host: HTMLElement, r: MetricRow, points: Point[], days: number,
                            onDays: (d: number) => void, notice: string | null = null): void {
  host.innerHTML = `<header><h3><span class="t"></span> <span class="e"></span></h3>
      <div class="tabs"><button data-d="7">7 days</button><button data-d="30">30 days</button></div></header>
    <svg class="plot" role="img"></svg><div class="readout"></div>`;
  (host.querySelector(".t") as HTMLElement).textContent = `${r.service} ${r.label.toLowerCase()}`;
  const now = Date.now() / 1000;
  (host.querySelector(".e") as HTMLElement).textContent = `· ${r.support ? "one of the three idle inputs" : eta(r, now)}`;
  host.querySelectorAll<HTMLButtonElement>(".tabs button").forEach((b) => {
    b.setAttribute("aria-pressed", String(Number(b.dataset.d) === days));
    b.addEventListener("click", () => onDays(Number(b.dataset.d)));
  });
  const svg = host.querySelector("svg") as SVGSVGElement;
  const readout = host.querySelector(".readout") as HTMLElement;
  svg.setAttribute("aria-label", `${r.label} over the last ${days} days`);
  const { width, height } = svg.getBoundingClientRect();
  const geo = chartGeometry(points, r, days, width, height, now);
  const idle = "Hover to read a value. The dashed line is the projection from the last 7 days.";
  readout.textContent = geo ? idle : (notice ?? "No history for this period yet.");
  if (!geo) return;
  const colour = COLOUR[r.level ?? "ok"];
  const edge = r.dir === "min" ? "Idle floor" : "Limit";
  const danger = r.dir === "min"
    ? el("rect", { x: 0, y: geo.limitY, width, height: Math.max(0, height - geo.limitY), fill: "#ff4d3d", opacity: 0.06 })
    : el("rect", { x: 0, y: 0, width, height: Math.max(0, geo.limitY), fill: "#ff4d3d", opacity: 0.06 });
  svg.append(
    danger,
    el("line", { x1: 0, x2: width, y1: geo.limitY, y2: geo.limitY, stroke: "#ff4d3d", "stroke-dasharray": "3 3", opacity: 0.75 }),
    el("path", { d: geo.area, fill: colour, opacity: 0.06 }),
    el("path", { d: geo.line, fill: "none", stroke: colour, "stroke-width": 1.5, "stroke-linejoin": "round" }),
    el("line", { x1: geo.x(now), x2: geo.x(now), y1: 0, y2: height, stroke: "#2c2b28" }),
  );
  const label = el("text", { x: width, y: geo.limitY - 6, fill: "#ff7a6d", "font-size": 11, "text-anchor": "end" });
  label.textContent = `${edge} ${fmt(r.limit)}${r.unit ? ` ${r.unit}` : ""}`;
  const nowLabel = el("text", { x: geo.x(now) + 5, y: height - 5, fill: "#8f897f", "font-size": 11 });
  nowLabel.textContent = "Now";
  svg.append(label, nowLabel);
  if (geo.projection) {
    svg.append(el("path", { d: geo.projection, stroke: colour, "stroke-dasharray": "2 4", "stroke-linecap": "round", opacity: 0.55 }));
  }
  const cursor = el("line", { y1: 0, y2: height, stroke: "#8f897f", opacity: 0 });
  const dot = el("circle", { r: 3.5, fill: colour, stroke: "#0c0c0b", "stroke-width": 2, opacity: 0 });
  svg.append(cursor, dot);
  svg.addEventListener("mousemove", (e) => {
    const px = Math.max(0, Math.min(width, e.offsetX));
    const at = readAt(geo, px, r);
    const when = new Date(at.t * 1000).toLocaleString("en-US", { month: "short", day: "numeric", hour: at.projected ? undefined : "numeric" });
    readout.textContent = `${at.projected ? "Projected " : ""}${when} · ${fmt(at.v)}${r.unit ? ` ${r.unit}` : ""}`;
    cursor.setAttribute("x1", String(px)); cursor.setAttribute("x2", String(px)); cursor.setAttribute("opacity", "0.6");
    dot.setAttribute("cx", String(at.projected ? px : geo.x(at.t))); dot.setAttribute("cy", String(geo.y(at.v))); dot.setAttribute("opacity", "1");
  });
  svg.addEventListener("mouseleave", () => {
    cursor.setAttribute("opacity", "0"); dot.setAttribute("opacity", "0"); readout.textContent = idle;
  });
}
