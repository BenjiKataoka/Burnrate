import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// plugin-http matches its scope with the Rust urlpattern crate, which follows the same spec as
// Node's URLPattern. A literal "100." hostname prefix gets rewritten to 0.0.0.100 and matches
// nothing, so this guards the real capability file against that class of mistake.
const cap = JSON.parse(readFileSync(new URL("../src-tauri/capabilities/default.json", import.meta.url), "utf8"));
const http = cap.permissions.find((p: { identifier?: string }) => p.identifier === "http:default");
const patterns = http.allow.map((a: { url: string }) => new URLPattern(a.url));
const allowed = (url: string): boolean => patterns.some((p: URLPattern) => p.test(url));

test("scope allows the Tailscale API and localhost", () => {
  assert.ok(allowed("http://100.101.102.103:8787/api/status")); // scan:allow
  assert.ok(allowed("http://100.101.102.103:8787/api/history?metric=x&days=7")); // scan:allow
  assert.ok(allowed("http://127.0.0.1:8787/api/status"));
});

test("scope rejects other hosts, ports and paths", () => {
  assert.ok(!allowed("http://100.101.102.103:8788/api/status")); // scan:allow
  assert.ok(!allowed("http://100.101.102.103:8787/other")); // scan:allow
  assert.ok(!allowed("http://10.0.0.1:8787/api/status"));
  assert.ok(!allowed("http://100.101.102.103.evil.com:8787/api/status")); // scan:allow
  assert.ok(!allowed("https://100.101.102.103:8787/api/status")); // scan:allow
});
