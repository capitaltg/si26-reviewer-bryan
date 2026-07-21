CREATE TYPE "public"."requirement_applies_to" AS ENUM('deck', 'other_component', 'administrative');--> statement-breakpoint
CREATE TYPE "public"."requirement_obligation_side" AS ENUM('quoter', 'government');--> statement-breakpoint
CREATE TYPE "public"."requirement_obligation_type" AS ENUM('content', 'constraint');--> statement-breakpoint
ALTER TABLE "requirements" ADD COLUMN "applies_to" "requirement_applies_to";--> statement-breakpoint
ALTER TABLE "requirements" ADD COLUMN "obligation_type" "requirement_obligation_type";--> statement-breakpoint
ALTER TABLE "requirements" ADD COLUMN "obligation_side" "requirement_obligation_side";--> statement-breakpoint
ALTER TABLE "requirements" ADD COLUMN "classification_rationale" text;--> statement-breakpoint
ALTER TABLE "requirements" ADD CONSTRAINT "requirements_classification_all_null_or_complete" CHECK ((
        ("requirements"."applies_to" IS NULL
          AND "requirements"."obligation_type" IS NULL
          AND "requirements"."obligation_side" IS NULL
          AND "requirements"."classification_rationale" IS NULL)
        OR
        ("requirements"."applies_to" IS NOT NULL
          AND "requirements"."obligation_type" IS NOT NULL
          AND "requirements"."obligation_side" IS NOT NULL
          AND "requirements"."classification_rationale" IS NOT NULL
          AND char_length(btrim("requirements"."classification_rationale")) > 0)
      ));--> statement-breakpoint
DELETE FROM "mappings";
