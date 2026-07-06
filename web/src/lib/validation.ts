import { z } from "zod";

export const documentKinds = [
  "solicitation_base",
  "solicitation_amendment",
  "solicitation_q_and_a",
  "solicitation_attachment",
  "deck",
  "script",
] as const;

export const createAnalysisSchema = z
  .object({
    consentLlmTransit: z.literal(true),
    distributionAttestation: z.literal(true),
    documents: z
      .array(
        z.object({
          kind: z.enum(documentKinds),
          displayName: z.string().min(1),
          blobPathname: z.string().min(1),
        }),
      )
      .min(2)
      .max(50),
  })
  .superRefine((val, ctx) => {
    const count = (k: string) =>
      val.documents.filter((d) => d.kind === k).length;
    if (count("solicitation_base") !== 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "exactly one solicitation_base is required",
      });
    }
    if (count("deck") !== 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "exactly one deck is required",
      });
    }
    if (count("script") > 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "at most one script is allowed",
      });
    }
    const seen = new Set<string>();
    for (const document of val.documents) {
      if (seen.has(document.blobPathname)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `duplicate blobPathname: ${document.blobPathname}`,
        });
      }
      seen.add(document.blobPathname);
    }
  });

export type CreateAnalysisInput = z.infer<typeof createAnalysisSchema>;
