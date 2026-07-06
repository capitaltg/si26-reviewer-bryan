import { head } from "@vercel/blob";
import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";
import { NextResponse } from "next/server";
import { db } from "@/db";
import { uploads } from "@/db/schema";
import { getUserId } from "@/lib/session";

const ALLOWED_CONTENT_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "text/plain",
];

export async function POST(request: Request): Promise<NextResponse> {
  const userId = await getUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const body = (await request.json()) as HandleUploadBody;
  try {
    const jsonResponse = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname) => {
        if (!pathname.startsWith("uploads/")) {
          throw new Error("pathname must start with uploads/");
        }
        return {
          allowedContentTypes: ALLOWED_CONTENT_TYPES,
          maximumSizeInBytes: 100 * 1024 * 1024,
          addRandomSuffix: true,
          tokenPayload: JSON.stringify({ userId }),
        };
      },
      onUploadCompleted: async ({ blob, tokenPayload }) => {
        const parsed = JSON.parse(tokenPayload as string) as { userId?: string };
        if (!parsed.userId) {
          throw new Error("upload token payload missing userId");
        }
        let contentType = blob.contentType ?? "application/octet-stream";
        let sizeBytes = 0;
        try {
          const info = await head(blob.url);
          sizeBytes = info.size;
          contentType = info.contentType ?? contentType;
        } catch (error) {
          // head() lookup is best-effort; fall back to blob.contentType and size 0
          // so the upload row is still recorded even if metadata fetch fails.
          console.warn("upload: head() lookup failed", blob.pathname, error);
        }
        await db
          .insert(uploads)
          .values({
            userId: parsed.userId,
            blobPathname: blob.pathname,
            blobUrl: blob.url,
            displayName: blob.pathname.split("/").at(-1) ?? blob.pathname,
            contentType,
            sizeBytes,
          })
          .onConflictDoNothing({ target: uploads.blobPathname });
      },
    });
    return NextResponse.json(jsonResponse);
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error).message },
      { status: 400 },
    );
  }
}
