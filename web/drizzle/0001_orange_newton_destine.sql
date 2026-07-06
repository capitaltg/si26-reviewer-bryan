ALTER TABLE "documents" ADD COLUMN "blob_url" text NOT NULL;--> statement-breakpoint
ALTER TABLE "documents" ADD COLUMN "content_type" text NOT NULL;--> statement-breakpoint
ALTER TABLE "documents" ADD COLUMN "pdf_blob_url" text;--> statement-breakpoint
ALTER TABLE "uploads" ADD COLUMN "blob_url" text NOT NULL;