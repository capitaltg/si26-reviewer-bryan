CREATE TYPE "public"."mapping_status" AS ENUM('covered', 'partial', 'missing');--> statement-breakpoint
CREATE TYPE "public"."requirement_source" AS ENUM('L', 'M', 'SOW', 'limit', 'FAR', 'amendment');--> statement-breakpoint
CREATE TABLE "mappings" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"requirement_id" uuid NOT NULL,
	"status" "mapping_status" NOT NULL,
	"slide_refs" jsonb NOT NULL,
	"rationale" text NOT NULL,
	CONSTRAINT "mappings_requirement_id_unique" UNIQUE("requirement_id")
);
--> statement-breakpoint
CREATE TABLE "requirements" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"analysis_id" uuid NOT NULL,
	"source_document_id" uuid NOT NULL,
	"source" "requirement_source" NOT NULL,
	"ref" text NOT NULL,
	"text" text NOT NULL,
	"page_no" integer NOT NULL,
	"weight" text,
	"supersedes_requirement_id" uuid
);
--> statement-breakpoint
ALTER TABLE "mappings" ADD CONSTRAINT "mappings_requirement_id_requirements_id_fk" FOREIGN KEY ("requirement_id") REFERENCES "public"."requirements"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "requirements" ADD CONSTRAINT "requirements_analysis_id_analyses_id_fk" FOREIGN KEY ("analysis_id") REFERENCES "public"."analyses"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "requirements" ADD CONSTRAINT "requirements_source_document_id_documents_id_fk" FOREIGN KEY ("source_document_id") REFERENCES "public"."documents"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "requirements" ADD CONSTRAINT "requirements_supersedes_requirement_id_requirements_id_fk" FOREIGN KEY ("supersedes_requirement_id") REFERENCES "public"."requirements"("id") ON DELETE no action ON UPDATE no action;