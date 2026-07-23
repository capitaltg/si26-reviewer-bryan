import { describe, expect, it } from "vitest";

import { parseWeight, sortFindings } from "./report-ordering";

describe("parseWeight", () => {
  it("extracts a bare percentage token", () => {
    expect(parseWeight("30%")).toBe(30);
  });

  it("extracts the first percentage when surrounded by text", () => {
    expect(parseWeight("weighted at 12.5% of the total score")).toBe(12.5);
  });

  it("preserves a percentage decimal that omits the leading zero", () => {
    expect(parseWeight("weighted at .5% of the total score")).toBe(0.5);
  });

  it("prefers a later percentage over an earlier non-percentage number", () => {
    expect(parseWeight("factor 3, weighted at 20%")).toBe(20);
  });

  it("falls back to the first numeric token when there is no percentage", () => {
    expect(parseWeight("evaluation factor 3")).toBe(3);
  });

  it("returns null for an unparseable weight", () => {
    expect(parseWeight("most important")).toBeNull();
  });

  it("returns null for a null weight", () => {
    expect(parseWeight(null)).toBeNull();
  });
});

describe("sortFindings", () => {
  const make = (
    id: string,
    severity: "high" | "medium" | "low",
    weight: string | null,
    confidence: "high" | "medium" | "low" = "medium",
  ) => ({ id, severity, weight, confidence });

  it("orders parseable weights highest-first, before unweighted findings", () => {
    const ordered = sortFindings([
      make("a", "low", null),
      make("b", "low", "10%"),
      make("c", "low", "40%"),
    ]).map((f) => f.id);
    expect(ordered).toEqual(["c", "b", "a"]);
  });

  it("treats an unparseable weight as unweighted (after weighted findings)", () => {
    const ordered = sortFindings([
      make("a", "high", "most important"),
      make("b", "low", "5%"),
    ]).map((f) => f.id);
    expect(ordered).toEqual(["b", "a"]);
  });

  it("breaks ties by severity rank then by ascending UUID", () => {
    const ordered = sortFindings([
      make("y", "low", null),
      make("z", "high", null),
      make("x", "high", null),
    ]).map((f) => f.id);
    expect(ordered).toEqual(["x", "z", "y"]);
  });

  it("breaks equal-severity ties by confidence rank, high first", () => {
    const ordered = sortFindings([
      make("a", "low", null, "low"),
      make("b", "low", null, "high"),
      make("c", "low", null, "medium"),
    ]).map((f) => f.id);
    expect(ordered).toEqual(["b", "c", "a"]);
  });

  it("prefers severity over confidence", () => {
    const ordered = sortFindings([
      make("a", "low", null, "high"),
      make("b", "high", null, "low"),
    ]).map((f) => f.id);
    expect(ordered).toEqual(["b", "a"]);
  });

  it("does not mutate the input array", () => {
    const input = [make("b", "low", "1%"), make("a", "low", "2%")];
    const copy = [...input];
    sortFindings(input);
    expect(input).toEqual(copy);
  });
});
