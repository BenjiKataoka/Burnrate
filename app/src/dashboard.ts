import "./styles.css";
import { makeClient, normalizeUrl, type Result } from "./api.ts";
import { renderChart } from "./chart.ts";
import {
  amount, byService, cells, connectionText, consequence, esc, eta, firstPollText, orbStyle, pct, worst,
  type MetricRow, type Status,
} from "./model.ts";
import { mountOrb } from "./orb.ts";
import { getFetch, hideCurrentOnClose, inTauri, loadSettings, onShowSettings, saveSettings } from "./platform.ts";

const REFRESH_MS = 5 * 60_000;
const app = document.getElementById("app") as HTMLElement;
let status: Status | null = null;
let lastOkAt: number | null = null;
let selected: string | null = null;
let days = 7;
let hover: number | null = null;
let editing = false; // refreshes must not wipe a half-filled settings form

app.innerHTML = `
  <section class="side">
    <div class="hero" id="hero"></div>
    <div class="srv" id="srv"></div>
    <div class="side-actions"><button id="refresh">Refresh</button><button id="open-settings">Settings</button></div>
    <div class="orb" id="orb" aria-hidden="true"></div>
    <div class="orb-cap" id="orb-cap"></div>
  </section>
  <section class="main" id="main"></section>`;

const orb = mountOrb(document.getElementById("orb") as HTMLElement, { size: 0.8, px: 3, back: "#10100f" });
const main = document.getElementById("main") as HTMLElement;

function cellsHtml(r: MetricRow): string {
  const { filled, floorAt } = cells(r, 20, false);
  const cls = r.support ? "on-support" : `on-${esc(r.level ?? "ok")}`;
  return Array.from({ length: 20 }, (_, i) => `<span class="${i < filled ? cls : ""}"></span>`).join("")
    + (floorAt === null ? "" : `<i class="floor" data-floor="${esc(String(floorAt))}"></i>`);
}

function renderSide(result: Result<Status>): void {
  const hero = document.getElementById("hero") as HTMLElement;
  const srv = document.getElementById("srv") as HTMLElement;
  const now = Date.now() / 1000;
  const w = status ? worst(status.metrics) : null;
  if (!status || !w) {
    hero.innerHTML = `<div class="n">--<small>%</small></div><h2>${status ? esc(firstPollText(status, now) ?? "No data yet") : "No data yet"}</h2>`;
  } else {
    hero.innerHTML = `<div class="n lv-${esc(w.level ?? "ok")}">${pct(w.pressure as number)}<small>%</small></div>
      <h2></h2><p></p><p class="cons"></p>`;
    (hero.querySelector("h2") as HTMLElement).textContent = `${w.service} ${w.label.toLowerCase()}`;
    (hero.querySelector("p") as HTMLElement).textContent = `${amount(w)} · ${eta(w, now)}`;
    (hero.querySelector(".cons") as HTMLElement).textContent = consequence(w);
  }
  const polled = status?.polled_at ? new Date(status.polled_at * 1000).toTimeString().slice(0, 5) : "never";
  const next = status?.next_poll_at ? new Date(status.next_poll_at * 1000).toTimeString().slice(0, 5) : "soon";
  srv.innerHTML = `Polled <b>${polled}</b> · next <b>${next}</b><br>Server <b>${result.kind === "ok" ? "reachable" : "not reachable"}</b>`;
  orb.set(orbStyle(hover ?? (w?.pressure ?? 0)));
  (document.getElementById("orb-cap") as HTMLElement).textContent = hover === null ? "" : `Previewing ${Math.round(hover * 100)}%`;
}

function renderMain(result: Result<Status>): void {
  const notice = connectionText(result, lastOkAt);
  if (!status) {
    main.innerHTML = notice ? `<div class="notice"></div>` : "";
    if (notice) (main.querySelector(".notice") as HTMLElement).textContent = notice;
    return;
  }
  const now = Date.now() / 1000;
  const groups = byService(status.metrics);
  if (!selected || !status.metrics.some((m) => m.metric === selected)) selected = worst(status.metrics)?.metric ?? status.metrics[0]?.metric ?? null;
  main.innerHTML = `${notice ? `<div class="notice"></div>` : ""}
    <div class="grid">${groups.map((g) => `
      <div class="svc"><header><h3></h3><span class="num">${g.pressure === null ? "n/a" : `${pct(g.pressure)}%`}</span></header>
        ${g.service === "Oracle" ? `<div class="rule">Reclaimed only if all three stay under 20% for 7 days</div>` : ""}
        ${g.rows.map((r) => `
          <button class="row ${r.support ? "support" : ""} ${r.stale ? "stale" : ""}" data-metric="${esc(r.metric)}" aria-pressed="${r.metric === selected}">
            <div class="l1"><span class="name"></span><span class="v num"></span></div>
            <div class="cells">${cellsHtml(r)}</div>
            <div class="l3"><span class="eta"></span><span class="num">${r.support || r.pressure === null ? "" : `${pct(r.pressure)}%`}</span></div>
          </button>`).join("")}
      </div>`).join("")}</div>
    <div class="chart" id="chart"></div>`;
  if (notice) (main.querySelector(".notice") as HTMLElement).textContent = notice;
  main.querySelectorAll(".svc h3").forEach((el, i) => { el.textContent = groups[i].service; });
  main.querySelectorAll<HTMLElement>(".row").forEach((el) => {
    const r = status!.metrics.find((m) => m.metric === el.dataset.metric) as MetricRow;
    (el.querySelector(".name") as HTMLElement).textContent = r.label;
    (el.querySelector(".v") as HTMLElement).textContent = r.value === null ? "no data" : amount(r);
    (el.querySelector(".eta") as HTMLElement).textContent = eta(r, now);
    const floor = el.querySelector<HTMLElement>(".floor");
    if (floor) floor.style.left = `${floor.dataset.floor}%`;
    const preview = (): void => { hover = r.support || r.pressure === null ? null : r.pressure; renderSide(result); };
    el.addEventListener("mouseenter", preview);
    el.addEventListener("focus", preview);
    el.addEventListener("mouseleave", () => { hover = null; renderSide(result); });
    el.addEventListener("blur", () => { hover = null; renderSide(result); });
    el.addEventListener("click", () => { selected = r.metric; void drawChart(); main.querySelectorAll(".row").forEach((b) => b.setAttribute("aria-pressed", String(b === el))); });
  });
  void drawChart();
}

let chartReq = 0;

async function drawChart(): Promise<void> {
  const host = document.getElementById("chart");
  if (!host || !status || !selected) return;
  const reqId = ++chartReq;
  const r = status.metrics.find((m) => m.metric === selected) as MetricRow;
  const client = makeClient(await loadSettings(), await getFetch());
  const res = await client.history(r.metric, days);
  if (reqId !== chartReq) return; // a newer click already superseded this request
  const notice = res.kind === "ok" ? null : (connectionText(res, lastOkAt) ?? "Can't load history right now.");
  renderChart(host, r, res.kind === "ok" ? res.data.points : [], days, (d) => { days = d; void drawChart(); }, notice);
}

function showSettings(message = ""): void {
  editing = true;
  main.innerHTML = `<form class="settings" id="settings">
      <h2>Connect to your poller</h2>
      <p>Your server's Tailscale address and the BURNRATE_TOKEN from its .env file.</p>
      <label for="url">Server address</label><input id="url" placeholder="http://100.x.y.z:8787" autocomplete="off" spellcheck="false">
      <label for="token">Token</label><input id="token" type="password" autocomplete="off" spellcheck="false">
      <div class="err" id="err" role="alert"></div>
      <div class="actions"><button type="submit">Save and connect</button><button type="button" id="cancel">Cancel</button></div>
    </form>`;
  (document.getElementById("err") as HTMLElement).textContent = message;
  const form = document.getElementById("settings") as HTMLFormElement;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = normalizeUrl((document.getElementById("url") as HTMLInputElement).value);
    const token = (document.getElementById("token") as HTMLInputElement).value.trim();
    const err = document.getElementById("err") as HTMLElement;
    if (!url) { err.textContent = "Use your server's Tailscale address on port 8787, like http://100.101.102.103:8787."; return; }
    if (token.length < 32) { err.textContent = "The token is at least 32 characters. Copy BURNRATE_TOKEN from the server's .env."; return; }
    const probe = await makeClient({ url, token }, await getFetch()).status();
    if (probe.kind === "unauthorized") { err.textContent = "The server rejected that token."; return; }
    if (probe.kind === "unreachable") { err.textContent = "Can't reach that address. Is Tailscale on?"; return; }
    await saveSettings({ url, token });
    editing = false;
    await refresh();
  });
  (document.getElementById("cancel") as HTMLElement).addEventListener("click", () => { editing = false; void refresh(); });
}

async function refresh(): Promise<void> {
  const client = makeClient(await loadSettings(), await getFetch());
  const result = await client.status();
  if (result.kind === "ok") { status = result.data; lastOkAt = Date.now() / 1000; }
  renderSide(result);
  if (editing) return;
  if (result.kind === "unconfigured") { showSettings(); return; }
  if (result.kind === "unauthorized" && !status) { showSettings("The server rejected the saved token."); return; }
  renderMain(result);
}

(document.getElementById("refresh") as HTMLElement).addEventListener("click", () => void refresh());
(document.getElementById("open-settings") as HTMLElement).addEventListener("click", () => showSettings());
void hideCurrentOnClose();
void onShowSettings(() => showSettings());
void refresh();
setInterval(() => void refresh(), REFRESH_MS);
window.addEventListener("focus", () => void refresh());
if (!inTauri) document.title = "Burnrate (preview)";
