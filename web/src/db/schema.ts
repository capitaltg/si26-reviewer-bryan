import { sql } from "drizzle-orm";
import {
  AnyPgColumn,
  boolean,
  check,
  integer,
  jsonb,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

export const analysisStatusEnum = pgEnum("analysis_status", [
  "queued",
  "running",
  "complete",
  "failed",
]);

export const documentKindEnum = pgEnum("document_kind", [
  "solicitation_base",
  "solicitation_amendment",
  "solicitation_q_and_a",
  "solicitation_attachment",
  "deck",
  "script",
]);

export const requirementSourceEnum = pgEnum("requirement_source", [
  "L",
  "M",
  "SOW",
  "limit",
  "FAR",
  "amendment",
]);

export const mappingStatusEnum = pgEnum("mapping_status", [
  "covered",
  "partial",
  "missing",
]);

export const requirementAppliesToEnum = pgEnum("requirement_applies_to", [
  "deck",
  "other_component",
  "administrative",
]);

export const requirementObligationTypeEnum = pgEnum(
  "requirement_obligation_type",
  ["content", "constraint"],
);

export const requirementObligationSideEnum = pgEnum(
  "requirement_obligation_side",
  ["quoter", "government"],
);

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  keycloakSub: text("keycloak_sub").notNull().unique(),
  email: text("email").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export const analyses = pgTable("analyses", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id),
  status: analysisStatusEnum("status").notNull().default("queued"),
  stage: text("stage"),
  stageDetail: text("stage_detail"),
  error: text("error"),
  consentLlmTransit: boolean("consent_llm_transit").notNull(),
  distributionAttestation: boolean("distribution_attestation").notNull(),
  lockedBy: text("locked_by"),
  lockedAt: timestamp("locked_at", { withTimezone: true }),
  requeueCount: integer("requeue_count").notNull().default(0),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
});

export const documents = pgTable("documents", {
  id: uuid("id").primaryKey().defaultRandom(),
  analysisId: uuid("analysis_id")
    .notNull()
    .references(() => analyses.id, { onDelete: "cascade" }),
  kind: documentKindEnum("kind").notNull(),
  displayName: text("display_name").notNull(),
  blobPathname: text("blob_pathname").notNull(),
  blobUrl: text("blob_url").notNull(),
  contentType: text("content_type").notNull(),
  pdfBlobPathname: text("pdf_blob_pathname"),
  pdfBlobUrl: text("pdf_blob_url"),
  pageCount: integer("page_count"),
});

export const uploads = pgTable("uploads", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id, { onDelete: "cascade" }),
  blobPathname: text("blob_pathname").notNull().unique(),
  blobUrl: text("blob_url").notNull(),
  displayName: text("display_name").notNull(),
  contentType: text("content_type").notNull(),
  sizeBytes: integer("size_bytes").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export const pages = pgTable(
  "pages",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    documentId: uuid("document_id")
      .notNull()
      .references(() => documents.id, { onDelete: "cascade" }),
    pageNo: integer("page_no").notNull(),
    text: text("text").notNull(),
    imageBlobPathname: text("image_blob_pathname").notNull(),
    imageBlobUrl: text("image_blob_url").notNull(),
    visionSummary: text("vision_summary"),
    scriptText: text("script_text"),
  },
  (table) => [
    uniqueIndex("pages_document_id_page_no_unique").on(
      table.documentId,
      table.pageNo,
    ),
  ],
);

export const requirements = pgTable(
  "requirements",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    analysisId: uuid("analysis_id")
      .notNull()
      .references(() => analyses.id, { onDelete: "cascade" }),
    sourceDocumentId: uuid("source_document_id")
      .notNull()
      .references(() => documents.id, { onDelete: "cascade" }),
    source: requirementSourceEnum("source").notNull(),
    ref: text("ref").notNull(),
    text: text("text").notNull(),
    pageNo: integer("page_no").notNull(),
    appliesTo: requirementAppliesToEnum("applies_to"),
    obligationType: requirementObligationTypeEnum("obligation_type"),
    obligationSide: requirementObligationSideEnum("obligation_side"),
    classificationRationale: text("classification_rationale"),
    weight: text("weight"),
    supersedesRequirementId: uuid("supersedes_requirement_id").references(
      (): AnyPgColumn => requirements.id,
    ),
  },
  (table) => [
    check(
      "requirements_classification_all_null_or_complete",
      sql`(
        (${table.appliesTo} IS NULL
          AND ${table.obligationType} IS NULL
          AND ${table.obligationSide} IS NULL
          AND ${table.classificationRationale} IS NULL)
        OR
        (${table.appliesTo} IS NOT NULL
          AND ${table.obligationType} IS NOT NULL
          AND ${table.obligationSide} IS NOT NULL
          AND ${table.classificationRationale} IS NOT NULL
          AND char_length(btrim(${table.classificationRationale})) > 0)
      )`,
    ),
  ],
);

export const mappings = pgTable("mappings", {
  id: uuid("id").primaryKey().defaultRandom(),
  requirementId: uuid("requirement_id")
    .notNull()
    .unique()
    .references(() => requirements.id, { onDelete: "cascade" }),
  status: mappingStatusEnum("status").notNull(),
  slideRefs: jsonb("slide_refs").notNull(),
  rationale: text("rationale").notNull(),
});

export const findingReviewerEnum = pgEnum("finding_reviewer", [
  "compliance",
  "technical",
  "evaluator",
]);
export const findingKindEnum = pgEnum("finding_kind", ["gap", "observation"]);
export const findingSeverityEnum = pgEnum("finding_severity", [
  "high",
  "medium",
  "low",
]);
export const findingConfidenceEnum = pgEnum("finding_confidence", [
  "high",
  "medium",
  "low",
]);
export const evidenceProvenanceEnum = pgEnum("evidence_provenance", [
  "native_text",
  "script",
  "vision_summary",
]);
export const findingVerificationEnum = pgEnum("finding_verification", [
  "verified",
  "unverified",
  "dropped",
]);

export const findings = pgTable(
  "findings",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    analysisId: uuid("analysis_id")
      .notNull()
      .references(() => analyses.id, { onDelete: "cascade" }),
    reviewer: findingReviewerEnum("reviewer").notNull(),
    findingKind: findingKindEnum("finding_kind").notNull(),
    severity: findingSeverityEnum("severity").notNull(),
    confidence: findingConfidenceEnum("confidence").notNull(),
    requirementId: uuid("requirement_id").references(() => requirements.id, {
      onDelete: "set null",
    }),
    evidence: jsonb("evidence").notNull(),
    evidenceProvenance: evidenceProvenanceEnum("evidence_provenance"),
    description: text("description").notNull(),
    suggestion: text("suggestion").notNull(),
    clusterId: uuid("cluster_id"),
    solicitationVerified: boolean("solicitation_verified").notNull(),
    proposalVerified: boolean("proposal_verified"),
    verification: findingVerificationEnum("verification").notNull(),
  },
  (table) => [
    check(
      "findings_gap_no_proposal",
      sql`(${table.findingKind} <> 'gap') OR (${table.proposalVerified} IS NULL AND ${table.evidenceProvenance} IS NULL)`,
    ),
    check(
      "findings_observation_has_proposal",
      sql`(${table.findingKind} <> 'observation') OR (${table.proposalVerified} IS NOT NULL)`,
    ),
    check(
      "findings_provenance_iff_proposal",
      sql`(${table.evidenceProvenance} IS NOT NULL) = (${table.proposalVerified} IS TRUE)`,
    ),
    check(
      "findings_verified_requires_sides",
      sql`(${table.verification} <> 'verified') OR (${table.solicitationVerified} AND (${table.findingKind} = 'gap' OR ${table.proposalVerified}))`,
    ),
  ],
);

export const summaries = pgTable(
  "summaries",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    analysisId: uuid("analysis_id")
      .notNull()
      .unique()
      .references(() => analyses.id, { onDelete: "cascade" }),
    summaryText: text("summary_text").notNull(),
    disagreementNotes: jsonb("disagreement_notes")
      .notNull()
      .default(sql`'[]'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (table) => [
    check(
      "summaries_summary_not_empty",
      sql`char_length(btrim(${table.summaryText})) > 0`,
    ),
    check(
      "summaries_notes_is_array",
      sql`jsonb_typeof(${table.disagreementNotes}) = 'array'`,
    ),
  ],
);
