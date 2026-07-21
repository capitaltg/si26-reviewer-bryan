// Deterministic priority ordering for report findings, applied at read time so
// it stays auditable and re-derivable (the LLM never ranks). Sort key, in
// descending priority:
//   1. parseable Section-M weight, numeric value highest first;
//   2. findings with no / unparseable weight, after all weighted findings;
//   3. severity rank high > medium > low;
//   4. finding UUID ascending lexical (final tiebreaker).

export type OrderableFinding = {
  id: string;
  severity: "high" | "medium" | "low";
  weight: string | null;
};

const SEVERITY_RANK: Record<OrderableFinding["severity"], number> = {
  high: 0,
  medium: 1,
  low: 2,
};

export function parseWeight(weight: string | null): number | null {
  if (weight === null) return null;
  const numericToken = String.raw`(?:\d+(?:\.\d+)?|\.\d+)`;
  const percent = weight.match(new RegExp(`(${numericToken})\\s*%`));
  if (percent) return Number.parseFloat(percent[1]);
  const numeric = weight.match(new RegExp(numericToken));
  if (numeric) return Number.parseFloat(numeric[0]);
  return null;
}

export function compareFindings(a: OrderableFinding, b: OrderableFinding): number {
  const weightA = parseWeight(a.weight);
  const weightB = parseWeight(b.weight);

  const hasWeightA = weightA !== null;
  const hasWeightB = weightB !== null;
  if (hasWeightA !== hasWeightB) return hasWeightA ? -1 : 1;
  if (weightA !== null && weightB !== null && weightA !== weightB) {
    return weightB - weightA; // higher weight first
  }

  const severity = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
  if (severity !== 0) return severity;

  if (a.id < b.id) return -1;
  if (a.id > b.id) return 1;
  return 0;
}

export function sortFindings<T extends OrderableFinding>(findings: T[]): T[] {
  return [...findings].sort(compareFindings);
}
