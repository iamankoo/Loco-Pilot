import { describe, expect, it } from "vitest";
import { formatDuration, formatDurationMs, isActiveExecution, statusLabel, statusTone, truncate } from "./format";

describe("formatDuration", () => {
  it("returns an em dash for null/undefined", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });

  it("formats sub-second durations", () => {
    expect(formatDuration(0.4)).toBe("<1s");
  });

  it("formats seconds", () => {
    expect(formatDuration(42)).toBe("42s");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(125)).toBe("2m 5s");
  });

  it("formats hours and minutes", () => {
    expect(formatDuration(3725)).toBe("1h 2m");
  });
});

describe("formatDurationMs", () => {
  it("formats sub-second millisecond durations directly", () => {
    expect(formatDurationMs(250)).toBe("250ms");
  });

  it("delegates to formatDuration above 1000ms", () => {
    expect(formatDurationMs(2000)).toBe("2s");
  });

  it("returns an em dash for null", () => {
    expect(formatDurationMs(null)).toBe("—");
  });
});

describe("statusLabel", () => {
  it("maps known statuses to display labels", () => {
    expect(statusLabel("needs_review")).toBe("Needs Review");
    expect(statusLabel("timed_out")).toBe("Timed Out");
    expect(statusLabel("passed")).toBe("Passed");
  });

  it("falls back to the raw value for unknown statuses", () => {
    expect(statusLabel("some_future_status")).toBe("some_future_status");
  });
});

describe("statusTone", () => {
  it("maps terminal success/failure statuses correctly", () => {
    expect(statusTone("passed")).toBe("success");
    expect(statusTone("failed")).toBe("error");
    expect(statusTone("error")).toBe("error");
    expect(statusTone("needs_review")).toBe("error");
  });

  it("maps active statuses correctly", () => {
    expect(statusTone("running")).toBe("running");
    expect(statusTone("pending")).toBe("pending");
  });

  it("maps cancelled-like statuses correctly", () => {
    expect(statusTone("cancelled")).toBe("cancelled");
    expect(statusTone("timed_out")).toBe("cancelled");
  });
});

describe("isActiveExecution", () => {
  it("treats pending and running as active", () => {
    expect(isActiveExecution("pending")).toBe(true);
    expect(isActiveExecution("running")).toBe(true);
  });

  it("treats terminal statuses as inactive", () => {
    expect(isActiveExecution("passed")).toBe(false);
    expect(isActiveExecution("failed")).toBe(false);
    expect(isActiveExecution("cancelled")).toBe(false);
  });
});

describe("truncate", () => {
  it("leaves short strings untouched", () => {
    expect(truncate("hello", 10)).toBe("hello");
  });

  it("truncates long strings with an ellipsis", () => {
    expect(truncate("hello world", 8)).toBe("hello w…");
    expect(truncate("hello world", 8).length).toBe(8);
  });
});
