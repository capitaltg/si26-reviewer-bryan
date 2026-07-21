CREATE TABLE "summaries" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"analysis_id" uuid NOT NULL,
	"summary_text" text NOT NULL,
	"disagreement_notes" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "summaries_analysis_id_unique" UNIQUE("analysis_id"),
	CONSTRAINT "summaries_summary_not_empty" CHECK (char_length(btrim("summaries"."summary_text")) > 0),
	CONSTRAINT "summaries_notes_is_array" CHECK (jsonb_typeof("summaries"."disagreement_notes") = 'array')
);
--> statement-breakpoint
ALTER TABLE "summaries" ADD CONSTRAINT "summaries_analysis_id_analyses_id_fk" FOREIGN KEY ("analysis_id") REFERENCES "public"."analyses"("id") ON DELETE cascade ON UPDATE no action;