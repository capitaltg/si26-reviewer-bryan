"use client";

import { useEffect, useState } from "react";

import type {
  ApplicabilityGroupKind,
  ReportFinding,
  ReportModel,
  ReviewerGroup,
} from "@/lib/report";

type Citation = { documentId: string; page: number; label: string };

const SEVERITY_CLASS: Record<ReportFinding["severity"], string> = {
  high: "bg-red-100 text-red-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-slate-100 text-slate-700",
};

const COVERAGE_CLASS: Record<string, string> = {
  covered: "bg-green-100 text-green-800",
  partial: "bg-amber-100 text-amber-800",
  missing: "bg-red-100 text-red-800",
};

const REVIEWER_LABEL: Record<ReviewerGroup["reviewer"], string> = {
  compliance: "Compliance",
  technical: "Technical",
  evaluator: "Evaluator",
};

const APPLICABILITY_LABEL: Record<ApplicabilityGroupKind, string> = {
  other_component: "Handled by another submission component",
  administrative: "Administrative or not deck-applicable",
  deck_context: "Deck constraints or evaluation context",
  unclassified: "Unclassified legacy records",
};

// Minimal, dependency-free Markdown for model-authored prose (the orchestrator
// writes the summary with **bold** labels and numbered lists). Supports
// paragraphs, ordered/unordered lists, and inline bold/italic/code. It builds
// React nodes directly — never dangerouslySetInnerHTML — so it cannot inject
// HTML. Anything it doesn't recognize renders as plain text.
function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|`([^`]+)`|(?:\*|_)([^*_]+)(?:\*|_)/g;
  let last = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    if (match[1] !== undefined) {
      nodes.push(<strong key={key++}>{match[1]}</strong>);
    } else if (match[2] !== undefined) {
      nodes.push(
        <code key={key++} className="rounded bg-slate-100 px-1 text-[0.9em]">
          {match[2]}
        </code>,
      );
    } else {
      nodes.push(<em key={key++}>{match[3]}</em>);
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let key = 0;

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push(
        <p key={key++} className="mb-3 last:mb-0">
          {renderInline(paragraph.join(" "))}
        </p>,
      );
      paragraph = [];
    }
  };
  const flushList = () => {
    if (!list) return;
    const items = list.items.map((item, index) => (
      <li key={index}>{renderInline(item)}</li>
    ));
    blocks.push(
      list.ordered ? (
        <ol key={key++} className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">
          {items}
        </ol>
      ) : (
        <ul key={key++} className="mb-3 list-disc space-y-1 pl-5 last:mb-0">
          {items}
        </ul>
      ),
    );
    list = null;
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushParagraph(); // keep an in-progress list across blank lines
      continue;
    }
    const ordered = line.match(/^\d+[.)]\s+(.*)$/);
    const unordered = line.match(/^[-*]\s+(.*)$/);
    if (ordered) {
      flushParagraph();
      if (!list || !list.ordered) {
        flushList();
        list = { ordered: true, items: [] };
      }
      list.items.push(ordered[1]);
    } else if (unordered) {
      flushParagraph();
      if (!list || list.ordered) {
        flushList();
        list = { ordered: false, items: [] };
      }
      list.items.push(unordered[1]);
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();

  return <div className={className}>{blocks}</div>;
}

function Chip({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function SectionCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function CitationButton({
  citation,
  fallbackLabel,
  onOpen,
}: {
  citation: Citation | null;
  fallbackLabel?: string;
  onOpen: (citation: Citation) => void;
}) {
  if (!citation) {
    return fallbackLabel ? (
      <span className="rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-500">
        {fallbackLabel}
      </span>
    ) : null;
  }
  return (
    <button
      type="button"
      onClick={() => onOpen(citation)}
      className="rounded border border-blue-300 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-50"
    >
      {citation.label}
    </button>
  );
}

export function ReportView({
  model,
  analysisId,
}: {
  model: ReportModel;
  analysisId: string;
}) {
  const [active, setActive] = useState<Citation | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sourcePageKeys = new Set(
    model.sourcePages.map(({ documentId, page }) => `${documentId}:${page}`),
  );
  const hasSourcePage = (documentId: string, page: number) =>
    sourcePageKeys.has(`${documentId}:${page}`);

  const openCitation = (citation: Citation) => {
    setImageUrl(null);
    setError(null);
    setActive(citation);
  };

  const allFindings = model.reviewerGroups.flatMap((group) => group.findings);
  const severityCounts = { high: 0, medium: 0, low: 0 };
  for (const finding of allFindings) {
    severityCounts[finding.severity] += 1;
  }
  const clusterCounts = new Map<string, number>();
  for (const finding of allFindings) {
    if (finding.clusterId) {
      clusterCounts.set(
        finding.clusterId,
        (clusterCounts.get(finding.clusterId) ?? 0) + 1,
      );
    }
  }
  const clusterLabelById = new Map(
    [...clusterCounts.entries()]
      .filter(([, count]) => count > 1)
      .map(([clusterId]) => clusterId)
      .sort()
      .map(
        (clusterId, index) =>
          [clusterId, `Related finding group ${index + 1}`] as const,
      ),
  );

  useEffect(() => {
    if (!active) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    const params = new URLSearchParams({
      documentId: active.documentId,
      page: String(active.page),
    });
    fetch(`/api/analyses/${analysisId}/source?${params.toString()}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`source request failed (${res.status})`);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the source page.");
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [active, analysisId]);

  const solicitationCitation = (finding: ReportFinding): Citation | null => {
    const solicitation = finding.evidence.solicitation;
    if (
      !solicitation?.document_id ||
      !hasSourcePage(solicitation.document_id, solicitation.page)
    ) {
      return null;
    }
    return {
      documentId: solicitation.document_id,
      page: solicitation.page,
      label: `${solicitation.ref} p.${solicitation.page}`,
    };
  };

  const proposalCitation = (finding: ReportFinding): Citation | null => {
    const proposal = finding.evidence.proposal;
    if (
      !proposal ||
      !model.deckDocumentId ||
      !hasSourcePage(model.deckDocumentId, proposal.slide)
    ) {
      return null;
    }
    return {
      documentId: model.deckDocumentId,
      page: proposal.slide,
      label: `Slide ${proposal.slide}`,
    };
  };

  const slideCitation = (slide: number): Citation | null => {
    if (!model.deckDocumentId || !hasSourcePage(model.deckDocumentId, slide)) {
      return null;
    }
    return { documentId: model.deckDocumentId, page: slide, label: `Slide ${slide}` };
  };

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {(["high", "medium", "low"] as const).map((severity) => (
          <div
            key={severity}
            data-severity={severity}
            data-count={severityCounts[severity]}
            className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          >
            <div className="text-2xl font-semibold">
              {severityCounts[severity]}
            </div>
            <Chip className={`mt-1 ${SEVERITY_CLASS[severity]}`}>
              {severity} severity
            </Chip>
          </div>
        ))}
      </section>

      <SectionCard title="Executive summary">
        <Markdown
          text={model.summaryText}
          className="max-w-prose text-sm leading-7 text-slate-700"
        />
      </SectionCard>

      {model.disagreementNotes.length > 0 && (
        <SectionCard title="Reviewer disagreements">
          <ul className="space-y-2">
            {model.disagreementNotes.map((note, index) => (
              <li
                key={index}
                className="rounded border border-amber-300 bg-amber-50 p-3 text-sm leading-relaxed"
              >
                <span className="font-medium">
                  {note.reviewers.join(" vs ")}: {" "}
                </span>
                {note.note}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      <SectionCard title="Traceability matrix">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b">
                <th className="py-2 pr-4">Requirement</th>
                <th className="py-2 pr-4">Coverage</th>
                <th className="py-2 pr-4">Slides</th>
                <th className="py-2">Rationale</th>
              </tr>
            </thead>
            <tbody>
              {model.matrix.map((row) => (
                <tr
                  key={row.requirementId}
                  className="border-b align-top odd:bg-slate-50"
                >
                  <td className="py-2 pr-4 font-mono">
                    {row.source} {row.ref}
                    {row.weight ? ` (${row.weight})` : ""}
                    <span className="mt-1 block max-w-md font-sans leading-relaxed text-slate-700">
                      {row.text}
                    </span>
                    {row.supersededRefs.length > 0 && (
                      <span className="mt-1 block font-sans text-xs text-slate-500">
                        Supersedes {row.supersededRefs.join(", ")}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    {row.status ? (
                      <Chip
                        className={
                          COVERAGE_CLASS[row.status] ??
                          "bg-slate-100 text-slate-700"
                        }
                      >
                        {row.status}
                      </Chip>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex flex-wrap gap-1">
                      {row.slideRefs.length === 0
                        ? "—"
                        : row.slideRefs.map((slide) => (
                            <CitationButton
                              key={slide}
                              citation={slideCitation(slide)}
                              fallbackLabel={`Slide ${slide}`}
                              onOpen={openCitation}
                            />
                          ))}
                    </div>
                  </td>
                  <td className="max-w-md py-2 leading-relaxed text-slate-700">
                    {row.rationale ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Findings">
        <div className="space-y-6">
          {model.reviewerGroups.map((group) => (
            <div key={group.reviewer}>
              <h3 className="mb-2 font-medium">
                {REVIEWER_LABEL[group.reviewer]}
              </h3>
              <ul className="space-y-3">
                {group.findings.map((finding) => {
                  const clusterLabel = finding.clusterId
                    ? clusterLabelById.get(finding.clusterId)
                    : undefined;
                  return (
                    <li
                      key={finding.id}
                      className={`rounded border p-3 text-sm ${
                        clusterLabel
                          ? "border-l-4 border-l-blue-500 bg-blue-50/30"
                          : ""
                      }`}
                      data-cluster-id={finding.clusterId ?? undefined}
                    >
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <Chip className={SEVERITY_CLASS[finding.severity]}>
                          {finding.severity}
                        </Chip>
                        <Chip className="bg-slate-100 text-slate-700">
                          confidence: {finding.confidence}
                        </Chip>
                        {finding.evidenceProvenance === "vision_summary" && (
                          <Chip className="bg-purple-100 text-purple-800">
                            grounded in vision summary
                          </Chip>
                        )}
                        {clusterLabel && (
                          <Chip className="bg-blue-100 text-blue-800">
                            {clusterLabel}
                          </Chip>
                        )}
                      </div>
                      <p className="mb-2 max-w-prose leading-relaxed text-slate-800">
                        {finding.description}
                      </p>
                      <p className="mb-2 max-w-prose leading-relaxed text-slate-600">
                        <span className="font-medium text-slate-700">
                          Suggestion:{" "}
                        </span>
                        {finding.suggestion}
                      </p>
                      <div className="flex flex-wrap gap-1">
                        <CitationButton
                          citation={solicitationCitation(finding)}
                          fallbackLabel={
                            finding.evidence.solicitation
                              ? `${finding.evidence.solicitation.ref} p.${finding.evidence.solicitation.page}`
                              : undefined
                          }
                          onOpen={openCitation}
                        />
                        <CitationButton
                          citation={proposalCitation(finding)}
                          fallbackLabel={
                            finding.evidence.proposal
                              ? `Slide ${finding.evidence.proposal.slide}`
                              : undefined
                          }
                          onOpen={openCitation}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </SectionCard>

      {model.applicabilityGroups.length > 0 && (
        <SectionCard title="Not coverage-scored">
          <div className="space-y-5">
            {model.applicabilityGroups.map((group) => (
              <div key={group.kind}>
                <h3 className="mb-2 font-medium">
                  {APPLICABILITY_LABEL[group.kind]}
                </h3>
                <ul className="space-y-2">
                  {group.records.map((record) => (
                    <li
                      key={record.requirementId}
                      className="rounded border p-3 text-sm"
                    >
                      <div className="font-mono">
                        {record.source} {record.ref}
                      </div>
                      <p className="mt-1 max-w-prose leading-relaxed text-slate-700">
                        {record.text}
                      </p>
                      <p className="mt-1 max-w-prose leading-relaxed text-slate-600">
                        {record.classificationRationale ??
                          "Re-run analysis to classify this record."}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {active && (
        <div
          className="fixed inset-0 z-10 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setActive(null)}
        >
          <div
            className="max-h-full w-full max-w-4xl overflow-auto rounded-lg bg-white p-4 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="font-medium">{active.label}</span>
              <button
                type="button"
                onClick={() => setActive(null)}
                className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
              >
                Close
              </button>
            </div>
            {error && <p className="text-red-600">{error}</p>}
            {!error && !imageUrl && <p>Loading…</p>}
            {imageUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={imageUrl} alt={active.label} className="max-w-full" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
