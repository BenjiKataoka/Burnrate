import assert from "node:assert/strict";
import { test } from "node:test";
import { makeClient, normalizeUrl, type Fetch } from "../src/api.ts";

const SETTINGS = { url: "http://100.101.102.103:8787", token: "t".repeat(43) }; // scan:allow

function fake(status: number, body: unknown, seen: { url?: string; auth?: string } = {}): Fetch {
  return async (url, init) => {
    seen.url = url;
    seen.auth = init.headers.Authorization;
    return { status, json: async () => body };
  };
}

test("ok returns the data and sends the bearer token", async () => {
  const seen: { url?: string; auth?: string } = {};
  const r = await makeClient(SETTINGS, fake(200, { metrics: [] }, seen)).status();
  assert.deepEqual(r, { kind: "ok", data: { metrics: [] } });
  assert.equal(seen.url, "http://100.101.102.103:8787/api/status"); // scan:allow
  assert.equal(seen.auth, `Bearer ${"t".repeat(43)}`);
});

test("401 is unauthorized", async () => {
  assert.deepEqual(await makeClient(SETTINGS, fake(401, {})).status(), { kind: "unauthorized" });
});

test("unreachable is a state not a throw", async () => {
  const boom: Fetch = async () => { throw new TypeError("network down"); };
  assert.deepEqual(await makeClient(SETTINGS, boom).status(), { kind: "unreachable", reason: "TypeError" });
  assert.deepEqual(await makeClient(SETTINGS, fake(500, {})).status(), { kind: "unreachable", reason: "HTTP 500" });
});

test("a hung server times out", async () => {
  const hang: Fetch = (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(new DOMException("timed out", "TimeoutError")));
  });
  const r = await makeClient(SETTINGS, hang, 50).status();
  assert.deepEqual(r, { kind: "unreachable", reason: "TimeoutError" });
});

test("unconfigured without settings", async () => {
  assert.deepEqual(await makeClient(null, fake(200, {})).status(), { kind: "unconfigured" });
});

test("history encodes the metric", async () => {
  const seen: { url?: string } = {};
  await makeClient(SETTINGS, fake(200, { points: [] }, seen)).history("neon.storage_gb", 7);
  assert.equal(seen.url, "http://100.101.102.103:8787/api/history?metric=neon.storage_gb&days=7"); // scan:allow
});

test("normalizeUrl accepts only Tailscale or loopback on 8787", () => {
  assert.equal(normalizeUrl(" http://100.101.102.103:8787/ "), "http://100.101.102.103:8787"); // scan:allow
  assert.equal(normalizeUrl("http://127.0.0.1:8787"), "http://127.0.0.1:8787");
  for (const bad of ["https://100.1.2.3:8787", "http://10.0.0.5:8787", "http://100.1.2.3:9000",
                     "http://example.com:8787", "100.1.2.3:8787", "http://100.1.2.3:8787/api", ""]) {
    assert.equal(normalizeUrl(bad), null, bad);
  }
});
