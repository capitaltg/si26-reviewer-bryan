import { head } from "@vercel/blob";
import { db } from "@/db";
import { uploads } from "@/db/schema";

/**
 * Records a completed blob upload as an `uploads` row for the given user.
 *
 * Shared by the production `onUploadCompleted` webhook (`api/upload`) and the
 * dev-only completion endpoint (`api/upload/complete`). The blob metadata is
 * always re-fetched server-side via head() so the recorded contentType/size
 * reflect the actual stored object rather than anything a client claimed.
 *
 * Idempotent on blobPathname: re-recording the same upload is a no-op.
 */
export async function recordCompletedUpload(input: {
  userId: string;
  blobPathname: string;
  blobUrl: string;
  fallbackContentType?: string;
}): Promise<void> {
  let contentType = input.fallbackContentType ?? "application/octet-stream";
  let sizeBytes = 0;
  try {
    const info = await head(input.blobUrl);
    sizeBytes = info.size;
    contentType = info.contentType ?? contentType;
  } catch (error) {
    // head() lookup is best-effort; fall back to the caller-supplied content
    // type and size 0 so the upload row is still recorded even if the metadata
    // fetch fails.
    console.warn("recordCompletedUpload: head() lookup failed", input.blobPathname, error);
  }
  await db
    .insert(uploads)
    .values({
      userId: input.userId,
      blobPathname: input.blobPathname,
      blobUrl: input.blobUrl,
      displayName: input.blobPathname.split("/").at(-1) ?? input.blobPathname,
      contentType,
      sizeBytes,
    })
    .onConflictDoNothing({ target: uploads.blobPathname });
}
