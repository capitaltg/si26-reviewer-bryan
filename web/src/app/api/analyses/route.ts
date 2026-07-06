import { NextResponse } from "next/server";
import { and, eq, inArray, sql } from "drizzle-orm";
import { db } from "@/db";
import { analyses, documents, uploads } from "@/db/schema";
import { getUserId } from "@/lib/session";
import { createAnalysisSchema } from "@/lib/validation";

const UPLOAD_COMPLETION_WAIT_ATTEMPTS = 10;
const UPLOAD_COMPLETION_WAIT_MS = 250;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function countOwnedUploads(userId: string, pathnames: string[]) {
  const rows = await db
    .select({ blobPathname: uploads.blobPathname })
    .from(uploads)
    .where(and(eq(uploads.userId, userId), inArray(uploads.blobPathname, pathnames)));
  return rows.length;
}

async function waitForOwnedUploads(userId: string, pathnames: string[]) {
  for (let attempt = 0; attempt < UPLOAD_COMPLETION_WAIT_ATTEMPTS; attempt += 1) {
    if ((await countOwnedUploads(userId, pathnames)) === pathnames.length) {
      return true;
    }
    await sleep(UPLOAD_COMPLETION_WAIT_MS);
  }
  return false;
}

export async function POST(request: Request) {
  const userId = await getUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const parsed = createAnalysisSchema.safeParse(await request.json());
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.flatten() },
      { status: 400 },
    );
  }
  const input = parsed.data;
  const pathnames = input.documents.map((document) => document.blobPathname);
  if (!(await waitForOwnedUploads(userId, pathnames))) {
    return NextResponse.json(
      { error: "one or more uploads are missing or not owned by current user" },
      { status: 400 },
    );
  }
  const id = await db.transaction(async (tx) => {
    const [analysis] = await tx
      .insert(analyses)
      .values({
        userId,
        consentLlmTransit: input.consentLlmTransit,
        distributionAttestation: input.distributionAttestation,
        expiresAt: sql`now() + interval '7 days'`,
      })
      .returning({ id: analyses.id });
    await tx.insert(documents).values(
      input.documents.map((d) => ({
        analysisId: analysis.id,
        kind: d.kind,
        displayName: d.displayName,
        blobPathname: d.blobPathname,
      })),
    );
    return analysis.id;
  });
  return NextResponse.json({ id }, { status: 201 });
}
