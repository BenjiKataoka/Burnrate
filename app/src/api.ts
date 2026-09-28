import type { Point, Status } from "./model.ts";

export type Settings = { url: string; token: string };
export type Fetch = (url: string, init: { headers: Record<string, string>; signal: AbortSignal })
  => Promise<{ status: number; json(): Promise<unknown> }>;
export type Result<T> =
  | { kind: "ok"; data: T }
  | { kind: "unauthorized" }
  | { kind: "unreachable"; reason: string }
  | { kind: "unconfigured" };

// Mirrors the HTTP plugin scope in capabilities/default.json: Tailscale or loopback, port 8787.
const ALLOWED = /^http:\/\/(100\.\d{1,3}\.\d{1,3}\.\d{1,3}|127\.0\.0\.1):8787$/;

export function normalizeUrl(input: string): string | null {
  const url = input.trim().replace(/\/+$/, "");
  return ALLOWED.test(url) ? url : null;
}

export function makeClient(settings: Settings | null, doFetch: Fetch, timeoutMs = 10_000) {
  async function get<T>(path: string): Promise<Result<T>> {
    if (!settings) return { kind: "unconfigured" };
    try {
      const res = await doFetch(settings.url + path, {
        headers: { Authorization: `Bearer ${settings.token}` },
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (res.status === 401) return { kind: "unauthorized" };
      if (res.status !== 200) return { kind: "unreachable", reason: `HTTP ${res.status}` };
      return { kind: "ok", data: (await res.json()) as T };
    } catch (e) {
      // The name only: messages can carry the URL, and the UI never needs more than the kind.
      return { kind: "unreachable", reason: e instanceof Error ? e.name : "error" };
    }
  }
  return {
    status: () => get<Status>("/api/status"),
    history: (metric: string, days: number) =>
      get<{ metric: string; points: Point[] }>(`/api/history?metric=${encodeURIComponent(metric)}&days=${days}`),
  };
}
