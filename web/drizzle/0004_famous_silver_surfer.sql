CREATE TYPE "public"."finding_reviewer" AS ENUM('compliance', 'technical', 'evaluator');--> statement-breakpoint
CREATE TYPE "public"."finding_kind" AS ENUM('gap', 'observation');--> statement-breakpoint
CREATE TYPE "public"."finding_severity" AS ENUM('high', 'medium', 'low');--> statement-breakpoint
CREATE TYPE "public"."finding_confidence" AS ENUM('high', 'medium', 'low');--> statement-breakpoint
CREATE TYPE "public"."evidence_provenance" AS ENUM('native_text', 'script', 'vision_summary');--> statement-breakpoint
CREATE TYPE "public"."finding_verification" AS ENUM('verified', 'unverified', 'dropped');--> statement-breakpoint
CREATE TABLE "findings" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"analysis_id" uuid NOT NULL,
	"reviewer" "finding_reviewer" NOT NULL,
	"finding_kind" "finding_kind" NOT NULL,
	"severity" "finding_severity" NOT NULL,
	"confidence" "finding_confidence" NOT NULL,
	"requirement_id" uuid,
	"evidence" jsonb NOT NULL,
	"evidence_provenance" "evidence_provenance",
	"description" text NOT NULL,
	"suggestion" text NOT NULL,
	"cluster_id" uuid,
	"solicitation_verified" boolean NOT NULL,
	"proposal_verified" boolean,
	"verification" "finding_verification" NOT NULL
);
--> statement-breakpoint
ALTER TABLE "findings" ADD CONSTRAINT "findings_analysis_id_analyses_id_fk" FOREIGN KEY ("analysis_id") REFERENCES "public"."analyses"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "findings" ADD CONSTRAINT "findings_requirement_id_requirements_id_fk" FOREIGN KEY ("requirement_id") REFERENCES "public"."requirements"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "findings" ADD CONSTRAINT "findings_gap_no_proposal" CHECK (("findings"."finding_kind" <> 'gap') OR ("findings"."proposal_verified" IS NULL AND "findings"."evidence_provenance" IS NULL));--> statement-breakpoint
ALTER TABLE "findings" ADD CONSTRAINT "findings_observation_has_proposal" CHECK (("findings"."finding_kind" <> 'observation') OR ("findings"."proposal_verified" IS NOT NULL));--> statement-breakpoint
ALTER TABLE "findings" ADD CONSTRAINT "findings_provenance_iff_proposal" CHECK (("findings"."evidence_provenance" IS NOT NULL) = ("findings"."proposal_verified" IS TRUE));--> statement-breakpoint
ALTER TABLE "findings" ADD CONSTRAINT "findings_verified_requires_sides" CHECK (("findings"."verification" <> 'verified') OR ("findings"."solicitation_verified" AND ("findings"."finding_kind" = 'gap' OR "findings"."proposal_verified")));
