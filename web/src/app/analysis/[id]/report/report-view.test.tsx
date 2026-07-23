import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ReportModel } from "@/lib/report";

import { ReportView } from "./report-view";

const model: ReportModel = {
  analysisId: "11111111-1111-1111-1111-111111111111",
  deckDocumentId: "22222222-2222-2222-2222-222222222222",
  sourcePages: [
    {
      documentId: "22222222-2222-2222-2222-222222222222",
      page: 3,
    },
    {
      documentId: "55555555-5555-5555-5555-555555555555",
      page: 2,
    },
  ],
  matrix: [
    {
      requirementId: "33333333-3333-3333-3333-333333333333",
      source: "L",
      ref: "L.1",
      text: "Provide the technical approach.",
      weight: "40%",
      supersededRefs: ["L.0"],
      status: "covered",
      slideRefs: [3],
      rationale: "Covered on slide 3.",
    },
  ],
  applicabilityGroups: [
    {
      kind: "other_component",
      records: [
        {
          requirementId: "88888888-8888-8888-8888-888888888888",
          source: "L",
          ref: "L.2",
          text: "Submit the written staffing response.",
          classificationRationale: "Handled in written Factor 1",
        },
      ],
    },
    {
      kind: "unclassified",
      records: [
        {
          requirementId: "99999999-9999-9999-9999-999999999999",
          source: "L",
          ref: "L.legacy",
          text: "Legacy requirement.",
          classificationRationale: null,
        },
      ],
    },
  ],
  reviewerGroups: [
    {
      reviewer: "compliance",
      findings: [
        {
          id: "44444444-4444-4444-4444-444444444444",
          reviewer: "compliance",
          findingKind: "observation",
          severity: "high",
          confidence: "medium",
          requirementSource: "L",
          requirementRef: "L.1",
          weight: "40%",
          description: "The approach is addressed on the timeline slide.",
          suggestion: "Keep it explicit.",
          evidence: {
            solicitation: {
              document_id: "55555555-5555-5555-5555-555555555555",
              document_name: "base.pdf",
              ref: "L.1",
              page: 2,
              quote: "Provide the technical approach.",
            },
            proposal: { slide: 3, quote: "phased rollout" },
          },
          evidenceProvenance: "vision_summary",
          clusterId: "66666666-6666-6666-6666-666666666666",
        },
      ],
    },
    {
      reviewer: "technical",
      findings: [
        {
          id: "77777777-7777-7777-7777-777777777777",
          reviewer: "technical",
          findingKind: "gap",
          severity: "medium",
          confidence: "high",
          requirementSource: "L",
          requirementRef: "L.1",
          weight: "40%",
          description: "The implementation detail is incomplete.",
          suggestion: "Add the missing implementation detail.",
          evidence: {
            solicitation: {
              document_id: "55555555-5555-5555-5555-555555555555",
              document_name: "base.pdf",
              ref: "L.1",
              page: 2,
              quote: "Provide the technical approach.",
            },
            searched_scope: "searched all slides",
          },
          evidenceProvenance: null,
          clusterId: "66666666-6666-6666-6666-666666666666",
        },
      ],
    },
  ],
  disagreementNotes: [
    {
      finding_ids: [
        "44444444-4444-4444-4444-444444444444",
        "77777777-7777-7777-7777-777777777777",
      ],
      reviewers: ["compliance", "technical"],
      note: "Compliance and technical disagree on severity.",
    },
  ],
  summaryText: "The deck broadly addresses the solicitation.",
};

describe("ReportView", () => {
  it("renders the summary, matrix, findings, and disagreement notes", () => {
    const html = renderToStaticMarkup(
      <ReportView model={model} analysisId={model.analysisId} />,
    );
    expect(html).toContain("The deck broadly addresses the solicitation.");
    expect(html).toContain("L.1");
    expect(html).toContain("Provide the technical approach.");
    expect(html).toContain("The approach is addressed on the timeline slide.");
    expect(html).toContain("Compliance and technical disagree on severity.");
    expect(html).toContain("Supersedes L.0");
    // The vision-only provenance badge is present.
    expect(html.toLowerCase()).toContain("vision");
    expect(html.match(/Related finding group 1/g)).toHaveLength(2);
  });

  it("renders markdown in the executive summary (bold + numbered list)", () => {
    const withMarkdown: ReportModel = {
      ...model,
      summaryText:
        "The deck is broadly compliant.\n\n" +
        "1. **Session pacing:** consolidate slides.\n" +
        "2. **Pickle format:** prefer ONNX.\n\n" +
        "Overall, address item 1 first.",
    };
    const html = renderToStaticMarkup(
      <ReportView model={withMarkdown} analysisId={withMarkdown.analysisId} />,
    );
    expect(html).toContain("<strong>Session pacing:</strong>");
    expect(html).toContain("<ol");
    expect(html).toContain("<li>");
    // The raw markdown markers must not survive into the output.
    expect(html).not.toContain("**Session pacing");
  });

  it("renders excluded records as not coverage-scored", () => {
    const html = renderToStaticMarkup(
      <ReportView model={model} analysisId={model.analysisId} />,
    );

    expect(html).toContain("Not coverage-scored");
    expect(html).toContain("Handled by another submission component");
    expect(html).toContain("L.2");
    expect(html).toContain("Unclassified legacy records");
    expect(html).toContain("Re-run analysis to classify this record.");
    expect(html).not.toContain(">missing</span>");
  });

  it("renders a resolvable proposal citation as an interactive control", () => {
    const html = renderToStaticMarkup(
      <ReportView model={model} analysisId={model.analysisId} />,
    );
    expect(html).toContain("<button");
    expect(html).toContain("Slide 3");
  });

  it("renders unresolved citations as static text instead of dropping them", () => {
    const unresolvedModel: ReportModel = {
      ...model,
      sourcePages: [],
    };
    const html = renderToStaticMarkup(
      <ReportView model={unresolvedModel} analysisId={model.analysisId} />,
    );

    expect(html).toContain("L.1 p.2");
    expect(html).toContain("Slide 3");
    expect(html).not.toContain("<button");
  });

  it("summarizes finding counts by severity", () => {
    const html = renderToStaticMarkup(
      <ReportView model={model} analysisId={model.analysisId} />,
    );

    expect(html).toContain('data-severity="high" data-count="1"');
    expect(html).toContain('data-severity="medium" data-count="1"');
    expect(html).toContain('data-severity="low" data-count="0"');
  });

  it("renders coverage status as a labeled chip", () => {
    const html = renderToStaticMarkup(
      <ReportView model={model} analysisId={model.analysisId} />,
    );

    expect(html).toContain(">covered</span>");
  });
});
