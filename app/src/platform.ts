// Everything that differs between the real app (Tauri) and a plain browser preview lives here.
import type { Fetch, Settings } from "./api.ts";
import type { Point, Status } from "./model.ts";

export const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
const PREVIEW: Settings = { url: "http://127.0.0.1:8787", token: "preview" };

export async function getFetch(): Promise<Fetch> {
  if (inTauri) {
    const { fetch } = await import("@tauri-apps/plugin-http");
    // The token must never follow a redirect (same rule as the poller's own HTTP client).
    return (url, init) => fetch(url, { headers: init.headers, signal: init.signal, connectTimeout: 10_000, maxRedirections: 0 });
  }
  return previewFetch;
}

// Browser preview: the sample status with its times moved to now, and a synthetic history.
async function previewFetch(url: string, init: { signal: AbortSignal }): ReturnType<Fetch> {
  const res = await window.fetch("/sample/status.json", { signal: init.signal });
  const sample = (await res.json()) as Status;
  const now = Math.floor(Date.now() / 1000);
  const shift = now - (sample.polled_at as number);
  const moved: Status = {
    ...sample,
    polled_at: now,
    next_poll_at: (sample.next_poll_at as number) + shift,
    metrics: sample.metrics.map((m) => ({
      ...m,
      updated: m.updated === null ? null : m.updated + shift,
      resets_at: m.resets_at === null ? null : m.resets_at + shift,
    })),
  };
  const path = new URL(url).pathname;
  if (path === "/api/status") return { status: 200, json: async () => moved };
  const metric = new URL(url).searchParams.get("metric") ?? "";
  const days = Number(new URL(url).searchParams.get("days") ?? "7");
  const row = moved.metrics.find((m) => m.metric === metric);
  const end = row?.value ?? 0;
  const points: Point[] = [];
  const n = days * 24;
  for (let i = 0; i < n; i++) {
    const t = now - (n - 1 - i) * 3600;
    points.push([t, Math.max(0, end * (0.7 + 0.3 * (i / n)) + Math.sin(i / 5) * end * 0.02)]);
  }
  return { status: 200, json: async () => ({ metric, points }) };
}

export async function loadSettings(): Promise<Settings | null> {
  if (!inTauri) return PREVIEW;
  const { load } = await import("@tauri-apps/plugin-store");
  // ponytail: plain file in the app data folder, not the Keychain; the token is read-only.
  const store = await load("settings.json", { autoSave: false });
  const url = await store.get<string>("url");
  const token = await store.get<string>("token");
  return url && token ? { url, token } : null;
}

export async function saveSettings(s: Settings): Promise<void> {
  if (!inTauri) return;
  const { load } = await import("@tauri-apps/plugin-store");
  const store = await load("settings.json", { autoSave: false });
  await store.set("url", s.url);
  await store.set("token", s.token);
  await store.save();
  // The widget refreshes at once instead of waiting for its next 5-minute tick.
  const { emit } = await import("@tauri-apps/api/event");
  await emit("settings-saved");
}

export async function onSettingsSaved(cb: () => void): Promise<void> {
  if (!inTauri) return;
  const { listen } = await import("@tauri-apps/api/event");
  await listen("settings-saved", cb);
}

// Lets the widget's "Open settings" button land the dashboard on the settings form
// instead of whatever it was last showing.
export async function requestSettings(): Promise<void> {
  if (!inTauri) return;
  const { emit } = await import("@tauri-apps/api/event");
  await emit("show-settings");
}

export async function onShowSettings(cb: () => void): Promise<void> {
  if (!inTauri) return;
  const { listen } = await import("@tauri-apps/api/event");
  await listen("show-settings", cb);
}

export async function openDashboard(): Promise<void> {
  if (!inTauri) {
    window.open("/index.html", "_blank");
    return;
  }
  const { Window } = await import("@tauri-apps/api/window");
  const w = await Window.getByLabel("dashboard");
  await w?.show();
  await w?.setFocus();
}

export async function hideCurrentOnClose(): Promise<void> {
  if (!inTauri) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const w = getCurrentWindow();
  // Closing the dashboard hides it; the app keeps running in the menu bar.
  await w.onCloseRequested(async (event) => {
    event.preventDefault();
    await w.hide();
  });
}

export async function setPinned(on: boolean): Promise<void> {
  if (!inTauri) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().setAlwaysOnTop(on);
}

export async function placeWidget(width: number): Promise<void> {
  if (!inTauri) return;
  const { getCurrentWindow, currentMonitor, PhysicalPosition } = await import("@tauri-apps/api/window");
  const monitor = await currentMonitor();
  if (!monitor) return;
  const s = monitor.scaleFactor;
  const x = monitor.position.x + monitor.size.width - Math.round((width + 18) * s);
  const y = monitor.position.y + Math.round(40 * s); // below the menu bar
  await getCurrentWindow().setPosition(new PhysicalPosition(x, y));
}

export async function startDrag(): Promise<void> {
  if (!inTauri) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().startDragging();
}

export async function getFlag(name: string): Promise<boolean> {
  if (!inTauri) return true;
  const { load } = await import("@tauri-apps/plugin-store");
  return (await (await load("settings.json", { autoSave: false })).get<boolean>(name)) === true;
}

export async function setFlag(name: string): Promise<void> {
  if (!inTauri) return;
  const { load } = await import("@tauri-apps/plugin-store");
  const store = await load("settings.json", { autoSave: false });
  await store.set(name, true);
  await store.save();
}

export const autostart = {
  async isEnabled(): Promise<boolean> {
    if (!inTauri) return false;
    const { isEnabled } = await import("@tauri-apps/plugin-autostart");
    return isEnabled();
  },
  async set(on: boolean): Promise<void> {
    if (!inTauri) return;
    const { enable, disable } = await import("@tauri-apps/plugin-autostart");
    await (on ? enable() : disable());
  },
};

export async function quit(): Promise<void> {
  if (!inTauri) return;
  const { exit } = await import("@tauri-apps/plugin-process");
  await exit(0);
}
