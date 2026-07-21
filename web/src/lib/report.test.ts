import { randomUUID } from "node:crypto";

import { afterAll, describe, expect, it } from "vitest";

import { db } from "@/db";
import {
  analyses,
  documents,
  findings,
  mappings,
  pages,
  requirements,
  summaries,
  users,
} from "@/db/schema";

import { loadReport } from "./report";

afterAll(async () => {
  await db.$client.end();
});

async function createUser() {
  const [user] = await db
    .insert(users)
    .values({ keycloakSub: `test:${randomUUID()}`, email: "test@example.com" })
    .returning({ id: users.id });
  return user.id;
}

async function createAnalysis(userId: string, status: "complete" | "running" = "complete") {
  const [analysis] = await db
    .insert(analyses)
    .values({
      userId,
      status,
      consentLlmTransit: true,
      distributionAttestation: true,
      expiresAt: new Date(Date.now() + 86_400_000),
    })
    .returning({ id: analyses.id });
  return analysis.id;
}

async function createSolicitation(analysisId: string) {
  const [document] = await db
    .insert(documents)
    .values({
      analysisId,
      kind: "solicitation_base",
      displayName: "base.pdf",
      blobPathname: `orig/${randomUUID()}.pdf`,
      blobUrl: `https://blob.example/${randomUUID()}.pdf`,
      contentType: "application/pdf",
    })
    .returning({ id: documents.id });
  return document.id;
}

async function createDeck(analysisId: string) {
  const [document] = await db
    .insert(documents)
    .values({
      analysisId,
      kind: "deck",
      displayName: "deck.pdf",
      blobPathname: `orig/${randomUUID()}.pdf`,
      blobUrl: `https://blob.example/${randomUUID()}.pdf`,
      contentType: "application/pdf",
    })
    .returning({ id: documents.id });
  return document.id;
}

async function createPage(documentId: string, pageNo: number) {
  await db.insert(pages).values({
    documentId,
    pageNo,
    text: `page ${pageNo}`,
    imageBlobPathname: `pages/${documentId}/${pageNo}.png`,
    imageBlobUrl: `https://blob.example/pages/${documentId}/${pageNo}.png`,
  });
}

async function createRequirement(
  analysisId: string,
  sourceDocumentId: string,
  overrides: {
    source?: "L" | "M" | "SOW" | "limit" | "FAR" | "amendment";
    ref: string;
    weight?: string | null;
    supersedesRequirementId?: string;
    appliesTo?: "deck" | "other_component" | "administrative" | null;
    obligationType?: "content" | "constraint" | null;
    obligationSide?: "quoter" | "government" | null;
    classificationRationale?: string | null;
  },
) {
  const [row] = await db
    .insert(requirements)
    .values({
      analysisId,
      sourceDocumentId,
      source: overrides.source ?? "L",
      ref: overrides.ref,
      text: `text for ${overrides.ref}`,
      pageNo: 1,
      weight: overrides.weight ?? null,
      supersedesRequirementId: overrides.supersedesRequirementId,
      appliesTo: overrides.appliesTo === undefined ? "deck" : overrides.appliesTo,
      obligationType:
        overrides.obligationType === undefined ? "content" : overrides.obligationType,
      obligationSide:
        overrides.obligationSide === undefined ? "quoter" : overrides.obligationSide,
      classificationRationale:
        overrides.classificationRationale === undefined
          ? "test classification"
          : overrides.classificationRationale,
    })
    .returning({ id: requirements.id });
  return row.id;
}

async function createGapFinding(
  analysisId: string,
  reviewer: "compliance" | "technical" | "evaluator",
  overrides: {
    severity?: "high" | "medium" | "low";
    requirementId?: string | null;
    verification?: "verified" | "unverified" | "dropped";
  } = {},
) {
  const [row] = await db
    .insert(findings)
    .values({
      analysisId,
      reviewer,
      findingKind: "gap",
      severity: overrides.severity ?? "high",
      confidence: "medium",
      requirementId: overrides.requirementId ?? null,
      evidence: {
        solicitation: {
          document_id: "d",
          document_name: "base.pdf",
          ref: "L.1",
          page: 1,
          quote: "q",
        },
        searched_scope: "searched all slides",
      },
      description: `gap from ${reviewer}`,
      suggestion: "fix it",
      solicitationVerified: true,
      verification: overrides.verification ?? "verified",
    })
    .returning({ id: findings.id });
  return row.id;
}

describe("loadReport", () => {
  it("returns not_found for a missing or unowned analysis", async () => {
    const userId = await createUser();
    expect(await loadReport(userId, "not-a-uuid")).toEqual({ kind: "not_found" });
    expect(await loadReport(userId, randomUUID())).toEqual({ kind: "not_found" });

    const otherId = await createUser();
    const analysisId = await createAnalysis(otherId, "complete");
    expect(await loadReport(userId, analysisId)).toEqual({ kind: "not_found" });
  });

  it("returns not_complete when the analysis is still running", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "running");
    expect(await loadReport(userId, analysisId)).toEqual({ kind: "not_complete" });
  });

  it("loads the existing source pages that citations may resolve to", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "complete");
    const solicitationId = await createSolicitation(analysisId);
    const deckId = await createDeck(analysisId);
    await createPage(solicitationId, 2);
    await createPage(deckId, 3);

    const otherAnalysisId = await createAnalysis(userId, "complete");
    const otherDeckId = await createDeck(otherAnalysisId);
    await createPage(otherDeckId, 99);

    const result = await loadReport(userId, analysisId);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;

    expect(result.model.sourcePages).toHaveLength(2);
    expect(result.model.sourcePages).toEqual(
      expect.arrayContaining([
        { documentId: solicitationId, page: 2 },
        { documentId: deckId, page: 3 },
      ]),
    );
  });

  it("includes only verified findings, grouped by reviewer and priority-ordered", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "complete");
    const solicitationId = await createSolicitation(analysisId);
    const deckId = await createDeck(analysisId);

    const heavy = await createRequirement(analysisId, solicitationId, {
      source: "M",
      ref: "M.1",
      weight: "40%",
      obligationSide: "government",
    });
    const light = await createRequirement(analysisId, solicitationId, {
      source: "M",
      ref: "M.2",
      weight: "10%",
      obligationSide: "government",
    });

    const lowWeighted = await createGapFinding(analysisId, "compliance", {
      requirementId: light,
      severity: "high",
    });
    const highWeighted = await createGapFinding(analysisId, "compliance", {
      requirementId: heavy,
      severity: "low",
    });
    const unverified = await createGapFinding(analysisId, "compliance", {
      verification: "unverified",
    });
    const technical = await createGapFinding(analysisId, "technical");

    await db.insert(summaries).values({
      analysisId,
      summaryText: "The executive summary.",
      disagreementNotes: [
        {
          finding_ids: [highWeighted, technical],
          reviewers: ["compliance", "technical"],
          note: "They disagree.",
        },
      ],
    });

    const result = await loadReport(userId, analysisId);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;

    expect(result.model.summaryText).toBe("The executive summary.");
    expect(result.model.deckDocumentId).toBe(deckId);
    expect(result.model.disagreementNotes[0].note).toBe("They disagree.");

    const compliance = result.model.reviewerGroups.find(
      (group) => group.reviewer === "compliance",
    );
    expect(compliance).toBeDefined();
    // Only the two verified compliance findings; the unverified one is excluded.
    expect(compliance!.findings.map((f) => f.id)).toEqual([highWeighted, lowWeighted]);
    // The unverified finding never appears in any group.
    const allIds = result.model.reviewerGroups.flatMap((g) => g.findings.map((f) => f.id));
    expect(allIds).toHaveLength(3);
    expect(allIds).not.toContain(unverified);
    expect(result.model.reviewerGroups.map((g) => g.reviewer)).toContain("technical");
  });

  it("uses numeric weights for Section M findings only", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "complete");
    const solicitationId = await createSolicitation(analysisId);

    const nonM = await createRequirement(analysisId, solicitationId, {
      source: "L",
      ref: "L.1",
      weight: "99%",
    });
    const sectionM = await createRequirement(analysisId, solicitationId, {
      source: "M",
      ref: "M.1",
      weight: "10%",
      obligationSide: "government",
    });
    const nonMFinding = await createGapFinding(analysisId, "compliance", {
      requirementId: nonM,
      severity: "high",
    });
    const sectionMFinding = await createGapFinding(analysisId, "compliance", {
      requirementId: sectionM,
      severity: "low",
    });

    const result = await loadReport(userId, analysisId);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;

    const compliance = result.model.reviewerGroups.find(
      (group) => group.reviewer === "compliance",
    );
    expect(compliance?.findings.map((finding) => finding.id)).toEqual([
      sectionMFinding,
      nonMFinding,
    ]);
    expect(compliance?.findings.find((finding) => finding.id === nonMFinding)?.weight).toBeNull();
  });

  it("does not expose requirement metadata through a cross-analysis finding link", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "complete");
    await createDeck(analysisId);

    const otherUserId = await createUser();
    const otherAnalysisId = await createAnalysis(otherUserId, "complete");
    const otherSolicitationId = await createSolicitation(otherAnalysisId);
    const foreignRequirementId = await createRequirement(
      otherAnalysisId,
      otherSolicitationId,
      { source: "M", ref: "M.SECRET", weight: "99%" },
    );
    const findingId = await createGapFinding(analysisId, "compliance", {
      requirementId: foreignRequirementId,
    });
    await db.insert(summaries).values({
      analysisId,
      summaryText: "Summary.",
      disagreementNotes: [],
    });

    const result = await loadReport(userId, analysisId);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;

    const finding = result.model.reviewerGroups
      .flatMap((group) => group.findings)
      .find((item) => item.id === findingId);
    expect(finding?.requirementRef).toBeNull();
    expect(finding?.weight).toBeNull();
  });

  it("emits one matrix row per effective requirement (superseded ones excluded)", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "complete");
    const solicitationId = await createSolicitation(analysisId);
    await createDeck(analysisId);

    const original = await createRequirement(analysisId, solicitationId, {
      ref: "L.1",
      weight: "20%",
    });
    const replacement = await createRequirement(analysisId, solicitationId, {
      ref: "L.1-rev",
      supersedesRequirementId: original,
    });
    await db.insert(mappings).values({
      requirementId: replacement,
      status: "covered",
      slideRefs: [3],
      rationale: "Covered on slide 3.",
    });

    await db.insert(summaries).values({
      analysisId,
      summaryText: "Summary.",
      disagreementNotes: [],
    });

    const result = await loadReport(userId, analysisId);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;

    const refs = result.model.matrix.map((row) => row.ref);
    expect(refs).toEqual(["L.1-rev"]);
    expect(result.model.matrix[0].supersededRefs).toEqual(["L.1"]);
    expect(result.model.matrix[0].status).toBe("covered");
    expect(result.model.matrix[0].slideRefs).toEqual([3]);
  });

  it("excludes requirement categories that are not coverage-mapped", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "complete");
    const solicitationId = await createSolicitation(analysisId);

    const lRequirement = await createRequirement(analysisId, solicitationId, {
      source: "L",
      ref: "L.1",
    });
    const sowRequirement = await createRequirement(analysisId, solicitationId, {
      source: "SOW",
      ref: "SOW.1",
    });
    for (const [source, ref] of [
      ["M", "M.1"],
      ["limit", "LIMIT.1"],
      ["FAR", "FAR.1"],
      ["amendment", "AMD.1"],
    ] as const) {
      await createRequirement(analysisId, solicitationId, { source, ref });
    }
    await db.insert(mappings).values([
      {
        requirementId: lRequirement,
        status: "covered",
        slideRefs: [1],
        rationale: "Covered.",
      },
      {
        requirementId: sowRequirement,
        status: "partial",
        slideRefs: [2],
        rationale: "Partially covered.",
      },
    ]);

    const result = await loadReport(userId, analysisId);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;

    expect(result.model.matrix.map((row) => row.ref)).toEqual(["L.1", "SOW.1"]);
    expect(result.model.matrix.every((row) => row.status !== null)).toBe(true);
  });

  it("separates mapped obligations from non-coverage classifications", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "complete");
    const solicitationId = await createSolicitation(analysisId);

    const included = await createRequirement(analysisId, solicitationId, {
      ref: "L.deck",
    });
    await db.insert(mappings).values({
      requirementId: included,
      status: "covered",
      slideRefs: [1],
      rationale: "Covered.",
    });
    await createRequirement(analysisId, solicitationId, {
      ref: "L.other",
      appliesTo: "other_component",
      classificationRationale: "Written Factor 1 response",
    });
    await createRequirement(analysisId, solicitationId, {
      source: "limit",
      ref: "LIMIT.1",
      obligationType: "constraint",
      classificationRationale: "Deck constraint",
    });
    await createRequirement(analysisId, solicitationId, {
      ref: "L.legacy",
      appliesTo: null,
      obligationType: null,
      obligationSide: null,
      classificationRationale: null,
    });
    const result = await loadReport(userId, analysisId);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;

    expect(result.model.matrix.map((row) => row.ref)).toEqual(["L.deck"]);
    expect(
      result.model.applicabilityGroups.map((group) => [
        group.kind,
        group.records.map((row) => row.ref),
      ]),
    ).toEqual([
      ["other_component", ["L.other"]],
      ["deck_context", ["LIMIT.1"]],
      ["unclassified", ["L.legacy"]],
    ]);

  });

  it("sorts duplicate applicability refs by source and requirement id", async () => {
    const userId = await createUser();
    const analysisId = await createAnalysis(userId, "complete");
    const solicitationId = await createSolicitation(analysisId);

    const sowDuplicate = await createRequirement(analysisId, solicitationId, {
      source: "SOW",
      ref: "DUP.1",
      appliesTo: "other_component",
    });
    const lDuplicate = await createRequirement(analysisId, solicitationId, {
      source: "L",
      ref: "DUP.1",
      appliesTo: "other_component",
    });
    const laterLDuplicate = await createRequirement(analysisId, solicitationId, {
      source: "L",
      ref: "DUP.1",
      appliesTo: "other_component",
    });

    const result = await loadReport(userId, analysisId);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;

    const duplicateGroup = result.model.applicabilityGroups.find(
      (group) => group.kind === "other_component",
    );
    expect(
      duplicateGroup?.records.map((record) => [record.source, record.requirementId]),
    ).toEqual([
      ["L", lDuplicate],
      ["L", laterLDuplicate],
      ["SOW", sowDuplicate],
    ].sort(([sourceA, idA], [sourceB, idB]) =>
      sourceA.localeCompare(sourceB) || idA.localeCompare(idB),
    ));
  });
});
