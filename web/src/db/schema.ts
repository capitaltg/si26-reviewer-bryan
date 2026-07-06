import {
  boolean,
  integer,
  pgEnum,
  pgTable,
  text,
  timestamp,
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
