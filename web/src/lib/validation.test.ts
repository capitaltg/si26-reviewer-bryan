import { describe, expect, it } from "vitest";
import { createAnalysisSchema } from "./validation";

const doc = (kind: string, n = 1) => ({
  kind,
  displayName: `doc-${n}.pdf`,
  blobPathname: `uploads/doc-${n}.pdf`,
});

const valid = {
  consentLlmTransit: true,
  distributionAttestation: true,
  documents: [doc("solicitation_base"), doc("deck", 2)],
};

describe("createAnalysisSchema", () => {
  it("accepts base solicitation + deck with both attestations", () => {
    expect(createAnalysisSchema.safeParse(valid).success).toBe(true);
  });

  it("accepts optional amendments, q&a, attachments, and one script", () => {
    const input = {
      ...valid,
      documents: [
        ...valid.documents,
        doc("solicitation_amendment", 3),
        doc("solicitation_q_and_a", 4),
        doc("solicitation_attachment", 5),
        doc("script", 6),
      ],
    };
    expect(createAnalysisSchema.safeParse(input).success).toBe(true);
  });

  it("rejects when consent is not literally true", () => {
    expect(
      createAnalysisSchema.safeParse({ ...valid, consentLlmTransit: false })
        .success,
    ).toBe(false);
  });

  it("rejects when distribution attestation is missing", () => {
    const { distributionAttestation: _omit, ...rest } = valid;
    expect(createAnalysisSchema.safeParse(rest).success).toBe(false);
  });

  it("rejects without exactly one solicitation_base", () => {
    expect(
      createAnalysisSchema.safeParse({ ...valid, documents: [doc("deck")] })
        .success,
    ).toBe(false);
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [
          doc("solicitation_base"),
          doc("solicitation_base", 2),
          doc("deck", 3),
        ],
      }).success,
    ).toBe(false);
  });

  it("rejects without exactly one deck", () => {
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [doc("solicitation_base")],
      }).success,
    ).toBe(false);
  });

  it("rejects more than one script", () => {
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [...valid.documents, doc("script", 3), doc("script", 4)],
      }).success,
    ).toBe(false);
  });

  it("rejects unknown document kinds", () => {
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [...valid.documents, doc("resume")],
      }).success,
    ).toBe(false);
  });

  it("rejects duplicate blob pathnames", () => {
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [
          doc("solicitation_base"),
          {
            kind: "deck",
            displayName: "same-path.pptx",
            blobPathname: "uploads/doc-1.pdf",
          },
        ],
      }).success,
    ).toBe(false);
  });
});
