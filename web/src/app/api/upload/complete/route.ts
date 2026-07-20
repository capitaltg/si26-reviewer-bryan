import { NextResponse } from "next/server";
import { z } from "zod";
import { getUserId } from "@/lib/session";
import { recordCompletedUpload } from "@/lib/uploads";

// Dev-only upload completion.
//
// In production, `uploads` rows are written by the `onUploadCompleted` webhook
// in `api/upload`, which Vercel Blob calls after a client upload finishes. That
// webhook cannot reach `localhost`, so in local dev the row is never recorded
// and analysis creation fails. This endpoint lets the client record the row
// directly after `upload()` resolves. It is gated on NODE_ENV so it can never
// be used to bypass the trusted webhook in production (mirrors AUTH_DEV_LOGIN).

const bodySchema = z.object({
  blobPathname: z.string().min(1),
  blobUrl: z.string().url(),
});

export async function POST(request: Request): Promise<NextResponse> {
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const userId = await getUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const parsed = bodySchema.safeParse(await request.json());
  if (!parsed.success || !parsed.data.blobPathname.startsWith("uploads/")) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }
  await recordCompletedUpload({
    userId,
    blobPathname: parsed.data.blobPathname,
    blobUrl: parsed.data.blobUrl,
  });
  return NextResponse.json({ ok: true }, { status: 201 });
}
