import { and, eq } from "drizzle-orm";

import { db } from "@/db";
import {
  analyses,
  documents,
  findings,
  mappings,
  requirements,
  summaries,
} from "@/db/schema";
import { sortFindings } from "@/lib/report-ordering";

export type CoverageStatus = "covered" | "partial" | "missing";

export type FindingEvidence = {
  solicitation?: {
    document_id: string;
    document_name: string;
    ref: string;
    page: number;
    quote: string;
  };
  proposal?: { slide: number; quote: string };
  searched_scope?: string;
};

export type MatrixRow = {
  requirementId: string;
  source: string;
  ref: string;
  text: string;
  weight: string | null;
  supersededRefs: string[];
  status: CoverageStatus | null;
  slideRefs: number[];
  rationale: string | null;
};

export type ReportFinding = {
  id: string;
  reviewer: "compliance" | "technical" | "evaluator";
  findingKind: "gap" | "observation";
  severity: "high" | "medium" | "low";
  confidence: "high" | "medium" | "low";
  requirementSource: string | null;
  requirementRef: string | null;
  weight: string | null;
  description: string;
  suggestion: string;
  evidence: FindingEvidence;
  evidenceProvenance: "native_text" | "script" | "vision_summary" | null;
  clusterId: string | null;
};

export type ReviewerGroup = {
  reviewer: "compliance" | "technical" | "evaluator";
  findings: ReportFinding[];
};

export type DisagreementNote = {
  finding_ids: string[];
  reviewers: string[];
  note: string;
};

export type ReportModel = {
  analysisId: string;
  deckDocumentId: string | null;
  matrix: MatrixRow[];
  reviewerGroups: ReviewerGroup[];
  disagreementNotes: DisagreementNote[];
  summaryText: string;
};

export type LoadReportResult =
  | { kind: "not_found" }
  | { kind: "not_complete" }
  | { kind: "ok"; model: ReportModel };

const REVIEWER_ORDER: ReportFinding["reviewer"][] = [
  "compliance",
  "technical",
  "evaluator",
];

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function loadReport(
  userId: string,
  analysisId: string,
): Promise<LoadReportResult> {
  if (!UUID_RE.test(analysisId)) return { kind: "not_found" };

  const [analysis] = await db
    .select({ id: analyses.id, status: analyses.status })
    .from(analyses)
    .where(and(eq(analyses.id, analysisId), eq(analyses.userId, userId)));
  if (!analysis) return { kind: "not_found" };
  if (analysis.status !== "complete") return { kind: "not_complete" };

  const [deck] = await db
    .select({ id: documents.id })
    .from(documents)
    .where(and(eq(documents.analysisId, analysisId), eq(documents.kind, "deck")));

  const requirementRows = await db
    .select({
      id: requirements.id,
      source: requirements.source,
      ref: requirements.ref,
      text: requirements.text,
      weight: requirements.weight,
      supersedesRequirementId: requirements.supersedesRequirementId,
    })
    .from(requirements)
    .where(eq(requirements.analysisId, analysisId));

  const supersededIds = new Set(
    requirementRows
      .map((row) => row.supersedesRequirementId)
      .filter((id): id is string => id !== null),
  );
  const requirementById = new Map(requirementRows.map((row) => [row.id, row]));

  function supersededRefsFor(
    requirement: (typeof requirementRows)[number],
  ): string[] {
    const refs: string[] = [];
    const seen = new Set<string>();
    let predecessorId = requirement.supersedesRequirementId;
    while (predecessorId && !seen.has(predecessorId)) {
      seen.add(predecessorId);
      const predecessor = requirementById.get(predecessorId);
      if (!predecessor) break;
      refs.push(predecessor.ref);
      predecessorId = predecessor.supersedesRequirementId;
    }
    return refs;
  }

  const mappingRows = await db
    .select({
      requirementId: mappings.requirementId,
      status: mappings.status,
      slideRefs: mappings.slideRefs,
      rationale: mappings.rationale,
    })
    .from(mappings)
    .innerJoin(requirements, eq(requirements.id, mappings.requirementId))
    .where(eq(requirements.analysisId, analysisId));
  const mappingByRequirement = new Map(
    mappingRows.map((row) => [row.requirementId, row]),
  );

  const matrix: MatrixRow[] = requirementRows
    .filter((row) => !supersededIds.has(row.id))
    .sort((a, b) => a.ref.localeCompare(b.ref))
    .map((row) => {
      const mapping = mappingByRequirement.get(row.id);
      return {
        requirementId: row.id,
        source: row.source,
        ref: row.ref,
        text: row.text,
        weight: row.weight,
        supersededRefs: supersededRefsFor(row),
        status: (mapping?.status as CoverageStatus | undefined) ?? null,
        slideRefs: (mapping?.slideRefs as number[] | undefined) ?? [],
        rationale: mapping?.rationale ?? null,
      };
    });

  const findingRows = await db
    .select({
      id: findings.id,
      reviewer: findings.reviewer,
      findingKind: findings.findingKind,
      severity: findings.severity,
      confidence: findings.confidence,
      requirementSource: requirements.source,
      requirementRef: requirements.ref,
      weight: requirements.weight,
      description: findings.description,
      suggestion: findings.suggestion,
      evidence: findings.evidence,
      evidenceProvenance: findings.evidenceProvenance,
      clusterId: findings.clusterId,
    })
    .from(findings)
    .leftJoin(
      requirements,
      and(
        eq(requirements.id, findings.requirementId),
        eq(requirements.analysisId, findings.analysisId),
      ),
    )
    .where(
      and(eq(findings.analysisId, analysisId), eq(findings.verification, "verified")),
    );

  const reportFindings: ReportFinding[] = findingRows.map((row) => ({
    id: row.id,
    reviewer: row.reviewer,
    findingKind: row.findingKind,
    severity: row.severity,
    confidence: row.confidence,
    requirementSource: row.requirementSource,
    requirementRef: row.requirementRef,
    weight: row.weight,
    description: row.description,
    suggestion: row.suggestion,
    evidence: (row.evidence as FindingEvidence) ?? {},
    evidenceProvenance: row.evidenceProvenance,
    clusterId: row.clusterId,
  }));

  const reviewerGroups: ReviewerGroup[] = REVIEWER_ORDER.map((reviewer) => ({
    reviewer,
    findings: sortFindings(reportFindings.filter((f) => f.reviewer === reviewer)),
  })).filter((group) => group.findings.length > 0);

  const [summary] = await db
    .select({
      summaryText: summaries.summaryText,
      disagreementNotes: summaries.disagreementNotes,
    })
    .from(summaries)
    .where(eq(summaries.analysisId, analysisId));

  return {
    kind: "ok",
    model: {
      analysisId,
      deckDocumentId: deck?.id ?? null,
      matrix,
      reviewerGroups,
      disagreementNotes: (summary?.disagreementNotes as DisagreementNote[]) ?? [],
      summaryText: summary?.summaryText ?? "",
    },
  };
}
