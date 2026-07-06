import { NextResponse } from "next/server";
import { and, eq } from "drizzle-orm";
import { db } from "@/db";
import { analyses } from "@/db/schema";
import { getUserId } from "@/lib/session";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const userId = await getUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const uuidRe =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!uuidRe.test(id)) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const [row] = await db
    .select({
      id: analyses.id,
      status: analyses.status,
      stage: analyses.stage,
      stageDetail: analyses.stageDetail,
      error: analyses.error,
      createdAt: analyses.createdAt,
    })
    .from(analyses)
    .where(and(eq(analyses.id, id), eq(analyses.userId, userId)));
  if (!row) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json(row);
}
