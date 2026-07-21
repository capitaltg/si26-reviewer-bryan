import { NextResponse } from "next/server";
import { and, eq, inArray } from "drizzle-orm";
import { get } from "@vercel/blob";

import { db } from "@/db";
import { analyses, documents, pages } from "@/db/schema";
import { getUserId } from "@/lib/session";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Only the solicitation documents and the deck may be rendered; the narration
// script has no page images and must never be streamable.
const SOURCE_KINDS = [
  "solicitation_base",
  "solicitation_amendment",
  "solicitation_q_and_a",
  "solicitation_attachment",
  "deck",
] as const;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const userId = await getUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const { searchParams } = new URL(request.url);
  const documentId = searchParams.get("documentId");
  const page = Number(searchParams.get("page"));

  if (
    !UUID_RE.test(id) ||
    !documentId ||
    !UUID_RE.test(documentId) ||
    !Number.isInteger(page) ||
    page < 1
  ) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  const [row] = await db
    .select({ pathname: pages.imageBlobPathname })
    .from(pages)
    .innerJoin(documents, eq(documents.id, pages.documentId))
    .innerJoin(analyses, eq(analyses.id, documents.analysisId))
    .where(
      and(
        eq(analyses.id, id),
        eq(analyses.userId, userId),
        eq(documents.id, documentId),
        eq(pages.pageNo, page),
        inArray(documents.kind, SOURCE_KINDS),
      ),
    );

  if (!row) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  try {
    const blob = await get(row.pathname, { access: "private" });
    if (!blob || blob.statusCode !== 200) {
      return NextResponse.json({ error: "bad gateway" }, { status: 502 });
    }
    return new Response(blob.stream, {
      headers: {
        "Content-Type": blob.blob.contentType ?? "image/png",
        "Cache-Control": "private, no-store",
      },
    });
  } catch {
    return NextResponse.json({ error: "bad gateway" }, { status: 502 });
  }
}
