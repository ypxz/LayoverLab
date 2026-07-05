// k6 load test: 20 VUs for 60s against POST /api/search (SSE) on the fixture stack.
//
// Run locally (stack must be up with RATE_LIMIT_ENABLED=false — see e2e/README.md):
//   k6 run e2e/load/search_sse.js
//
// k6's http client buffers the whole SSE body, so `http_req_waiting` (TTFB) is used as the
// first-event latency proxy: the server sends the `candidates` event as its first bytes.
import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";

const BASE = __ENV.API_BASE || "http://localhost:8000/api";

const streamErrors = new Rate("search_stream_errors");

export const options = {
  vus: 20,
  duration: "60s",
  thresholds: {
    http_req_failed: ["rate<0.01"], // transport/HTTP error rate < 1%
    search_stream_errors: ["rate<0.01"], // SSE `error` events also count as errors
    http_req_waiting: ["p(95)<2000"], // first event (TTFB) p95 < 2s
  },
};

const PAIRS = [
  ["BER", "ALC"],
  ["BER", "BKK"],
  ["HAM", "ALC"],
  ["MAD", "PMI"],
  ["BER", "MUC"],
];

function monthStart() {
  if (__ENV.E2E_MONTH) return `${__ENV.E2E_MONTH}-01`;
  const now = new Date();
  const shifted = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1 + 62));
  return new Date(Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), 1))
    .toISOString()
    .slice(0, 10);
}

export default function () {
  const [origin, dest] = PAIRS[Math.floor(Math.random() * PAIRS.length)];
  const from = monthStart();
  const to = new Date(new Date(from).getTime() + 6 * 86400000).toISOString().slice(0, 10);
  const res = http.post(
    `${BASE}/search`,
    JSON.stringify({ origin, dest, date_from: from, date_to: to, round_trip: false }),
    { headers: { "Content-Type": "application/json" }, timeout: "90s" },
  );
  const body = typeof res.body === "string" ? res.body : "";
  streamErrors.add(res.status !== 200 || body.includes("event: error"));
  check(res, {
    "status 200": (r) => r.status === 200,
    "stream completed with done": () => body.includes("event: done"),
    "candidates event present": () => body.includes("event: candidates"),
  });
}
