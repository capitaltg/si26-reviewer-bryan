import { randomUUID } from "node:crypto";
import { afterAll, describe, expect, it, vi } from "vitest";
import { eq } from "drizzle-orm";
import { db } from "@/db";
import { documents, uploads, users } from "@/db/schema";
import { getUserId } from "@/lib/session";
import { POST } from "./route";

vi.mock("@/lib/session", () => ({ getUserId: vi.fn() }));

afterAll(async () => {
  await db.$client.end();
});

async function createUser() {
  const [user] = await db
    .insert(users)
    .values({ keycloakSub: `test:${randomUUID()}`, email: "test@example.com" })
    .returning({ id: users.id });
  return user.id;
}

async function createUpload(
  userId: string,
  overrides: { blobPathname: string; blobUrl: string; contentType: string },
) {
  await db.insert(uploads).values({
    userId,
    blobPathname: overrides.blobPathname,
    blobUrl: overrides.blobUrl,
    displayName: overrides.blobPathname.split("/").at(-1)!,
    contentType: overrides.contentType,
    sizeBytes: 123,
  });
}

function postRequest(body: unknown) {
  return new Request("http://localhost/api/analyses", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

describe("POST /api/analyses", () => {
  it("copies blobUrl/contentType from the owning uploads row into documents", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);

    const basePathname = `uploads/base-${randomUUID()}.pdf`;
    const deckPathname = `uploads/deck-${randomUUID()}.pptx`;
    const baseUpload = {
      blobPathname: basePathname,
      blobUrl: `https://example-store.private.blob.vercel-storage.com/${basePathname}`,
      contentType: "application/pdf",
    };
    const deckUpload = {
      blobPathname: deckPathname,
      blobUrl: `https://example-store.private.blob.vercel-storage.com/${deckPathname}`,
      contentType:
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    };
    await createUpload(userId, baseUpload);
    await createUpload(userId, deckUpload);

    const response = await POST(
      postRequest({
        consentLlmTransit: true,
        distributionAttestation: true,
        documents: [
          {
            kind: "solicitation_base",
            displayName: "base.pdf",
            blobPathname: basePathname,
          },
          {
            kind: "deck",
            displayName: "deck.pptx",
            blobPathname: deckPathname,
          },
        ],
      }),
    );

    expect(response.status).toBe(201);
    const { id: analysisId } = (await response.json()) as { id: string };

    const rows = await db
      .select()
      .from(documents)
      .where(eq(documents.analysisId, analysisId));
    expect(rows).toHaveLength(2);

    const base = rows.find((r) => r.blobPathname === basePathname);
    const deck = rows.find((r) => r.blobPathname === deckPathname);
    expect(base?.blobUrl).toBe(baseUpload.blobUrl);
    expect(base?.contentType).toBe(baseUpload.contentType);
    expect(deck?.blobUrl).toBe(deckUpload.blobUrl);
    expect(deck?.contentType).toBe(deckUpload.contentType);
  });

  it("returns 400 without inserting an analysis when a referenced upload is missing", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);

    const basePathname = `uploads/base-${randomUUID()}.pdf`;
    const missingDeckPathname = `uploads/deck-${randomUUID()}.pptx`;
    await createUpload(userId, {
      blobPathname: basePathname,
      blobUrl: `https://example-store.private.blob.vercel-storage.com/${basePathname}`,
      contentType: "application/pdf",
    });

    const response = await POST(
      postRequest({
        consentLlmTransit: true,
        distributionAttestation: true,
        documents: [
          {
            kind: "solicitation_base",
            displayName: "base.pdf",
            blobPathname: basePathname,
          },
          {
            kind: "deck",
            displayName: "deck.pptx",
            blobPathname: missingDeckPathname,
          },
        ],
      }),
    );

    expect(response.status).toBe(400);
  });
});
