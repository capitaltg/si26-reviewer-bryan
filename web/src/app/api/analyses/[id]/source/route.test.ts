import { randomUUID } from "node:crypto";

import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import { db } from "@/db";
import { analyses, documents, pages, users } from "@/db/schema";
import { getUserId } from "@/lib/session";
import { get } from "@vercel/blob";

import { GET } from "./route";

vi.mock("@/lib/session", () => ({ getUserId: vi.fn() }));
vi.mock("@vercel/blob", () => ({ get: vi.fn() }));

afterAll(async () => {
  await db.$client.end();
});

beforeEach(() => {
  vi.clearAllMocks();
});

async function createUser() {
  const [user] = await db
    .insert(users)
    .values({ keycloakSub: `test:${randomUUID()}`, email: "test@example.com" })
    .returning({ id: users.id });
  return user.id;
}

async function createAnalysis(userId: string) {
  const [analysis] = await db
    .insert(analyses)
    .values({
      userId,
      status: "complete",
      consentLlmTransit: true,
      distributionAttestation: true,
      expiresAt: new Date(Date.now() + 86_400_000),
    })
    .returning({ id: analyses.id });
  return analysis.id;
}

async function createDeckPage(analysisId: string, pageNo = 1, kind: "deck" | "script" = "deck") {
  const [document] = await db
    .insert(documents)
    .values({
      analysisId,
      kind,
      displayName: "deck.pdf",
      blobPathname: `orig/${randomUUID()}.pdf`,
      blobUrl: `https://blob.example/${randomUUID()}.pdf`,
      contentType: "application/pdf",
    })
    .returning({ id: documents.id });
  const pathname = `analyses/${analysisId}/pages/${document.id}/${pageNo}.png`;
  await db.insert(pages).values({
    documentId: document.id,
    pageNo,
    text: "page text",
    imageBlobPathname: pathname,
    imageBlobUrl: `https://blob.example/${pathname}`,
  });
  return { documentId: document.id, pathname };
}

function sourceRequest(analysisId: string, query: Record<string, string>) {
  const params = new URLSearchParams(query).toString();
  return new Request(`http://localhost/api/analyses/${analysisId}/source?${params}`);
}

function routeParams(id: string) {
  return { params: Promise.resolve({ id }) };
}

function okBlob() {
  return {
    statusCode: 200 as const,
    stream: new Response(new Uint8Array([137, 80, 78, 71])).body,
    headers: new Headers(),
    blob: { contentType: "image/png", size: 4 },
  };
}

describe("GET /api/analyses/[id]/source", () => {
  it("streams the private PNG for an owned deck page", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);
    const analysisId = await createAnalysis(userId);
    const { documentId, pathname } = await createDeckPage(analysisId);
    vi.mocked(get).mockResolvedValue(okBlob() as never);

    const response = await GET(
      sourceRequest(analysisId, { documentId, page: "1" }),
      routeParams(analysisId),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(
      new Uint8Array([137, 80, 78, 71]),
    );
    expect(vi.mocked(get)).toHaveBeenCalledWith(pathname, { access: "private" });
  });

  it("returns 401 when unauthenticated", async () => {
    vi.mocked(getUserId).mockResolvedValue(null);
    const response = await GET(
      sourceRequest(randomUUID(), { documentId: randomUUID(), page: "1" }),
      routeParams(randomUUID()),
    );
    expect(response.status).toBe(401);
  });

  it("returns 404 for a non-integer page", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);
    const analysisId = await createAnalysis(userId);
    const { documentId } = await createDeckPage(analysisId);
    const response = await GET(
      sourceRequest(analysisId, { documentId, page: "abc" }),
      routeParams(analysisId),
    );
    expect(response.status).toBe(404);
  });

  it("returns 404 for a script document (not a source kind)", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);
    const analysisId = await createAnalysis(userId);
    const { documentId } = await createDeckPage(analysisId, 1, "script");
    const response = await GET(
      sourceRequest(analysisId, { documentId, page: "1" }),
      routeParams(analysisId),
    );
    expect(response.status).toBe(404);
  });

  it("returns 404 for a page in another user's analysis", async () => {
    const ownerId = await createUser();
    const otherId = await createUser();
    const analysisId = await createAnalysis(ownerId);
    const { documentId } = await createDeckPage(analysisId);
    vi.mocked(getUserId).mockResolvedValue(otherId);
    const response = await GET(
      sourceRequest(analysisId, { documentId, page: "1" }),
      routeParams(analysisId),
    );
    expect(response.status).toBe(404);
  });

  it("returns 404 for a cross-analysis target owned by the same user", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);
    const requestedAnalysisId = await createAnalysis(userId);
    const otherAnalysisId = await createAnalysis(userId);
    const { documentId } = await createDeckPage(otherAnalysisId);

    const response = await GET(
      sourceRequest(requestedAnalysisId, { documentId, page: "1" }),
      routeParams(requestedAnalysisId),
    );

    expect(response.status).toBe(404);
    expect(vi.mocked(get)).not.toHaveBeenCalled();
  });

  it("returns 502 when the Blob fetch throws", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);
    const analysisId = await createAnalysis(userId);
    const { documentId } = await createDeckPage(analysisId);
    vi.mocked(get).mockRejectedValue(new Error("blob down"));
    const response = await GET(
      sourceRequest(analysisId, { documentId, page: "1" }),
      routeParams(analysisId),
    );
    expect(response.status).toBe(502);
  });
});
