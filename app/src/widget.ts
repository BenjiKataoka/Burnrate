import "./styles.css";
import { makeClient, type Result } from "./api.ts";
import { byService, cells, esc, eta, pct, trayTitle, widgetOrbStyle, worst, type MetricRow, type Status } from "./model.ts";
import { mountOrb } from "./orb.ts";
import {
  autostart, getFetch, getFlag, loadSettings, onSettingsSaved, openDashboard, placeWidget, quit, requestSettings,
  setFlag, setPinned, startDrag,
} from "./platform.ts";
import { createTray } from "./tray.ts";

const REFRESH_MS = 5 * 60_000; // the poller updates every 15 minutes; faster would be wasted
const root = document.getElementById("widget") as HTMLElement;
let last: Status | null = null;
let lastOkAt: Date | null = null;
let pinned = true;

function cellsHtml(r: MetricRow): string {
  const { filled } = cells(r, 10, true);
  const cls = `on-${esc(r.level ?? "ok")}`;
  return Array.from({ length: 10 }, (_, i) => `<span class="${i < filled ? cls : ""}"></span>`).join("");
}

function render(result: Result<Status> | null): void {
  const offline = result !== null && result.kind !== "ok";
  root.classList.toggle("offline", offline);
  const head = `<div class="w-head" data-drag><span><span class="w-dot"></span>Burnrate</span><span>${
    offline && lastOkAt ? `since ${lastOkAt.toTimeString().slice(0, 5)}` : "live"}</span></div>`;
  if (result?.kind === "unconfigured") {
    root.innerHTML = `${head}<div class="w-msg">Connect Burnrate to your poller.<br><button id="setup">Set up</button></div>`;
    root.dataset.level = "ok";
    return;
  }
  if (result?.kind === "unauthorized") {
    root.innerHTML = `${head}<div class="w-msg">The server rejected the token.<br><button id="setup">Open settings</button></div>`;
    root.dataset.level = "ok";
    return;
  }
  if (!last) {
    root.innerHTML = `${head}<div class="w-msg">${offline ? "Can't reach the server." : "Loading."}</div>`;
    return;
  }
  const w = worst(last.metrics);
  const now = Date.now() / 1000;
  const level = w?.level ?? "ok";
  root.dataset.level = offline ? "ok" : level;
  root.innerHTML = `${head}
    <div class="w-num lv-${esc(level)}">${w ? pct(w.pressure as number) : "--"}<small>%</small></div>
    <div class="w-what"></div>
    <div class="w-orb" aria-hidden="true"></div>
    <div class="w-rows">${byService(last.metrics).map((g) => {
      const top = worst(g.rows) ?? g.rows[0];
      const stale = g.rows.every((r) => r.stale || r.value === null);
      return `<div class="w-row"><span class="w-svc"></span><div class="cells">${stale ? "" : cellsHtml(top)}</div>
        <span class="p num lv-${stale ? "ok" : esc(top.level ?? "ok")}">${stale || g.pressure === null ? "n/a" : `${pct(g.pressure)}%`}</span></div>`;
    }).join("")}</div>`;
  // Server text goes in with textContent only.
  (root.querySelector(".w-what") as HTMLElement).textContent = w ? `${w.service} ${w.label.toLowerCase()} · ${eta(w, now)}` : "No data yet";
  const groups = byService(last.metrics);
  root.querySelectorAll(".w-svc").forEach((el, i) => { el.textContent = groups[i].service; });
  orb.set(widgetOrbStyle(offline ? null : w?.level ?? null));
  const orbEl = root.querySelector(".w-orb") as HTMLElement;
  orbEl.replaceWith(orbHost);
}

// The orb canvas lives outside innerHTML re-renders so WebGL is created once.
const orbHost = document.createElement("div");
orbHost.className = "w-orb";
orbHost.setAttribute("aria-hidden", "true");
const orb = mountOrb(orbHost, { size: 0.9, px: 2, back: "#0c0c0b" });

let tray: { setTitle(title: string): Promise<void> } | null = null;

async function refresh(): Promise<void> {
  const client = makeClient(await loadSettings(), await getFetch());
  const result = await client.status();
  if (result.kind === "ok") {
    last = result.data;
    lastOkAt = new Date();
  }
  render(result);
  await tray?.setTitle(result.kind === "ok" ? trayTitle(last) : result.kind === "unreachable" ? "Burnrate offline" : "Burnrate");
}

root.addEventListener("mousedown", (e) => {
  const target = e.target as HTMLElement;
  if (target.closest("[data-drag]")) void startDrag();
});
root.addEventListener("click", (e) => {
  const target = e.target as HTMLElement;
  if (target.closest("[data-drag]")) return;
  if (target.closest("#setup")) void requestSettings();
  void openDashboard();
});
root.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") void openDashboard(); });

async function main(): Promise<void> {
  await placeWidget(220);
  await setPinned(pinned);
  // Dev builds must never register target/debug/app as a login item.
  if (import.meta.env.PROD) {
    try {
      if (!(await getFlag("autostart_set"))) {
        // Best effort: an unsigned app can fail to register as a login item, and that must
        // never block startup. Set the flag either way so we don't retry every launch; the
        // user can still turn it on from the menu.
        try {
          await autostart.set(true);
        } catch {
          // Nothing to do: isEnabled() below reports what's actually true.
        }
        await setFlag("autostart_set");
      }
    } catch {
      // First-launch bookkeeping (store reads/writes) must never abort main() before the
      // tray, and its Quit item, exist.
    }
    try {
      // The LaunchAgent plist pins the executable path at enable() time; if the app moved
      // since, re-write it with the current path so autostart still points at the right binary.
      if (await autostart.isEnabled()) await autostart.set(true);
    } catch {
      // Best effort, same as above.
    }
  }
  let atLogin = await autostart.isEnabled();
  tray = await createTray({
    open: () => void openDashboard(),
    refresh: () => void refresh(),
    pinned,
    togglePin: () => { pinned = !pinned; void setPinned(pinned); return pinned; },
    atLogin,
    toggleLogin: async () => {
      const target = !atLogin;
      try {
        await autostart.set(target);
        atLogin = target;
      } catch {
        // The set failed: show what's actually true, not what we attempted.
        atLogin = await autostart.isEnabled();
      }
      return atLogin;
    },
    quit: () => void quit(),
  });
  await onSettingsSaved(() => void refresh());
  await refresh();
  setInterval(() => void refresh(), REFRESH_MS);
  window.addEventListener("focus", () => void refresh());
}

void main();
