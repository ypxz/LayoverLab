import { describe, expect, it } from "vitest";
import { parseSSE } from "./api";
import { formatMoney } from "./format";

describe("parseSSE", () => {
  it("parses complete blocks and keeps the partial remainder", () => {
    const buffer =
      'event: candidates\ndata: [{"a":1}]\n\nevent: verified\ndata: [{"b":2}]\n\nevent: done\nda';
    const { events, rest } = parseSSE(buffer);
    expect(events).toEqual([
      { event: "candidates", data: '[{"a":1}]' },
      { event: "verified", data: '[{"b":2}]' },
    ]);
    expect(rest).toBe("event: done\nda");
  });

  it("handles CRLF and multi-line data", () => {
    const buffer = "event: x\r\ndata: line1\r\ndata: line2\r\n\r\n";
    const { events, rest } = parseSSE(buffer);
    expect(events).toEqual([{ event: "x", data: "line1\nline2" }]);
    expect(rest).toBe("");
  });

  it("defaults to message event", () => {
    const { events } = parseSSE("data: hi\n\n");
    expect(events[0].event).toBe("message");
  });
});

describe("formatMoney", () => {
  it("renders whole euros without decimals", () => {
    expect(formatMoney(2500)).toBe("€25");
  });
  it("renders cents when present", () => {
    expect(formatMoney(1999)).toBe("€19.99");
  });
});
