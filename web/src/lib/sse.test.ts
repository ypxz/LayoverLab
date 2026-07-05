import { describe, expect, it, vi } from "vitest";
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

describe("searchStream watchdog", () => {
  it("cancels a stalled stream instead of spinning forever", async () => {
    const { searchStream } = await import("./api");
    let cancelled = false;
    const stalledBody = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
      // never enqueues and never closes — simulates a hung connection
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(stalledBody, { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    try {
      const events: string[] = [];
      await searchStream(
        { origin: "BER", dest: "ALC" } as never,
        (event) => events.push(event),
        undefined,
        50,
      );
      expect(cancelled).toBe(true);
      expect(events).toEqual([]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
