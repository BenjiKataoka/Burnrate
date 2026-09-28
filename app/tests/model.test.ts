import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DAY, amount, ago, byService, cells, chartGeometry, consequence, esc, eta, firstPollText,
  fmt, orbStyle, pct, readAt, trayTitle, widgetOrbStyle, worst,
  type MetricRow, type Status,
} from "../src/model.ts";

const NOW = 1_790_500_000;

function row(over: Partial<MetricRow>): MetricRow {
  return {
    metric: "neon.storage_gb", service: "Neon", label: "Storage", unit: "GB", dir: "max",
    value: 0.36, limit: 0.5, pressure: 0.72, level: "ok", at_limit: "writes fail",
    resets_at: null, updated: NOW - 60, stale: false, support: false,
    slope_per_day: null, days_to_limit: null, ...over,
  };
}

test("worst ignores stale, support and empty rows", () => {
  const rows = [
    row({ metric: "a", pressure: 0.5 }),
    row({ metric: "b", pressure: 0.9, stale: true }),
    row({ metric: "c", pressure: 1.2, support: true }),
    row({ metric: "d", pressure: null, value: null }),
    row({ metric: "e", pressure: 0.7 }),
  ];
  assert.equal(worst(rows)?.metric, "e");
  assert.equal(worst([]), null);
});

test("fmt", () => {
  assert.equal(fmt(0), "0");
  assert.equal(fmt(0.0335), "0.034");
  assert.equal(fmt(0.000372), "0.00037");
  assert.equal(fmt(7.361), "7.4");
  assert.equal(fmt(61), "61");
  assert.equal(fmt(50000), "50,000");
  assert.equal(pct(0.7249), 72);
});

test("amount for floor and limit", () => {
  assert.equal(amount(row({})), "0.36 / 0.5 GB");
  assert.equal(amount(row({ unit: "", value: 8, limit: 50000 })), "8 / 50,000");
  assert.equal(amount(row({ dir: "min", unit: "%", value: 15.52, limit: 20 })), "16% · floor 20%");
});

test("ago", () => {
  assert.equal(ago(30), "just now");
  assert.equal(ago(120), "2 min");
  assert.equal(ago(3 * 3600), "3 hours");
  assert.equal(ago(3600), "1 hour");
  assert.equal(ago(2 * DAY + 5), "2 days");
});

test("eta texts", () => {
  assert.equal(eta(row({ value: null, pressure: null }), NOW), "no data yet");
  assert.equal(eta(row({ stale: true, updated: NOW - 7200 }), NOW), "no data for 2 hours, showing last value");
  assert.equal(eta(row({ support: true }), NOW), "one of the three idle inputs");
  assert.equal(eta(row({ level: "crit", pressure: 1.02 }), NOW), "over the limit");
  assert.equal(eta(row({ dir: "min", level: "crit" }), NOW), "below the floor");
  assert.equal(eta(row({ days_to_limit: 1.2 }), NOW), "limit in about 1 day");
  assert.equal(eta(row({ days_to_limit: 23.6 }), NOW), "limit in about 24 days");
  assert.equal(eta(row({ dir: "min", days_to_limit: 6 }), NOW), "floor in about 6 days");
  assert.equal(eta(row({ resets_at: NOW + 4.2 * DAY }), NOW), "safe · resets in 5 days");
  assert.equal(eta(row({}), NOW), "flat");
  assert.equal(eta(row({ dir: "min" }), NOW), "steady");
});

test("consequence", () => {
  assert.equal(consequence(row({})), "At the limit: writes fail");
  assert.equal(consequence(row({ level: "crit" })), "Now: writes fail");
  assert.equal(consequence(row({ dir: "min", at_limit: "Oracle can reclaim the VM" })), "At the floor: Oracle can reclaim the VM");
  assert.equal(consequence(row({ at_limit: "" })), "");
});

test("byService keeps order and takes the worst tracked pressure", () => {
  const groups = byService([
    row({ service: "Neon", metric: "n1", pressure: 0.2 }),
    row({ service: "Oracle", metric: "o1", pressure: 0.9, support: true }),
    row({ service: "Neon", metric: "n2", pressure: 0.6 }),
    row({ service: "Oracle", metric: "o2", pressure: 0.4 }),
  ]);
  assert.deepEqual(groups.map((g) => [g.service, g.rows.length, g.pressure]), [["Neon", 2, 0.6], ["Oracle", 2, 0.4]]);
});

test("cells", () => {
  assert.deepEqual(cells(row({}), 20, false), { filled: 14, floorAt: null });
  assert.deepEqual(cells(row({ pressure: 1.4 }), 20, false), { filled: 20, floorAt: null });
  assert.deepEqual(cells(row({ dir: "min", value: 15.5, limit: 20, pressure: 1.29 }), 20, false), { filled: 3, floorAt: 20 });
  assert.deepEqual(cells(row({ dir: "min", value: 15.5, limit: 20, pressure: 1.29 }), 10, true), { filled: 10, floorAt: null });
  assert.deepEqual(cells(row({ value: null, pressure: null }), 10, true), { filled: 0, floorAt: null });
});

test("tray title", () => {
  assert.equal(trayTitle(null), "Burnrate");
  const status: Status = { polled_at: NOW, next_poll_at: NOW + 900, interval_s: 900, collectors: {}, metrics: [row({})] };
  assert.equal(trayTitle(status), "Neon 72%");
  assert.equal(trayTitle({ ...status, metrics: [row({ stale: true })] }), "Burnrate");
});

test("first poll text", () => {
  const empty: Status = { polled_at: null, next_poll_at: null, interval_s: 900, collectors: {}, metrics: [] };
  assert.equal(firstPollText(empty, NOW), "Waiting for the first poll");
  assert.equal(firstPollText({ ...empty, next_poll_at: NOW + 600 }, NOW), "First poll in about 10 min");
  assert.equal(firstPollText({ ...empty, next_poll_at: NOW + 10 }, NOW), "First poll in about 1 min");
  const polled: Status = { ...empty, polled_at: NOW - 60, next_poll_at: NOW + 840 };
  assert.equal(firstPollText(polled, NOW), null);
});

test("orb styles", () => {
  assert.deepEqual(orbStyle(0.3), { color: "#2e2c29", speed: 0.06 + 0.3 * 0.9 });
  assert.equal(orbStyle(0.9).color, "#c4621f");
  assert.equal(orbStyle(1.3).color, "#d23a2c");
  assert.deepEqual(widgetOrbStyle("ok"), { color: "#3a3834", speed: 0 });
  assert.deepEqual(widgetOrbStyle(null), { color: "#3a3834", speed: 0 });
  assert.deepEqual(widgetOrbStyle("warn"), { color: "#ff8a2b", speed: 0.8 });
  assert.deepEqual(widgetOrbStyle("crit"), { color: "#d23a2c", speed: 1.4 });
});

test("chart geometry", () => {
  const r = row({ limit: 1, slope_per_day: 0.1 });
  const pts: [number, number][] = [[NOW - 2 * DAY, 0.4], [NOW - DAY, 0.5], [NOW, 0.6]];
  const g = chartGeometry(pts, r, 7, 700, 100, NOW);
  assert.ok(g !== null);
  assert.equal(g.x(g.t0), 0);
  assert.equal(Math.round(g.x(g.t1)), 700);
  assert.equal(Math.round(g.y(g.ymin)), 100);
  assert.ok(g.line.startsWith("M0.0 "));
  assert.ok(g.projection && g.projection.startsWith(`M${g.x(NOW).toFixed(1)}`));
  assert.ok(g.limitY > 0 && g.limitY < 100);
  assert.equal(chartGeometry([], r, 7, 700, 100, NOW), null);
  assert.equal(chartGeometry([[NOW - 30 * DAY, 1]], r, 7, 700, 100, NOW), null);
  const past = readAt(g, g.x(NOW - DAY), r);
  assert.deepEqual([past.t, past.v, past.projected], [NOW - DAY, 0.5, false]);
  const future = readAt(g, 700, r);
  assert.equal(future.projected, true);
  assert.ok(future.v > 0.6);
});

test("esc", () => {
  assert.equal(esc(`<b a="x">&'`), "&lt;b a=&quot;x&quot;&gt;&amp;&#39;");
});
