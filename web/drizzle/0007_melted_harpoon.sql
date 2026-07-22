ALTER TABLE "requirements" ADD COLUMN "evidence_quote" text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE "requirements" ADD COLUMN "grounding_verified" boolean DEFAULT false NOT NULL;