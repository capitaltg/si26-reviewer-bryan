import { randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { and, eq } from "drizzle-orm";
import { db } from "@/db";
import { uploads, users } from "@/db/schema";
import { getUserId } from "@/lib/session";
import { POST } from "./route";

vi.mock("@/lib/session", () => ({ getUserId: vi.fn() }));
vi.mock("@vercel/blob", () => ({
  head: vi.fn(async () => ({
    size: 4096,
    contentType: "application/pdf",
  })),
}));

afterAll(async () => {
  await db.$client.end();
});

beforeEach(() => {
  // The endpoint is dev-only; NODE_ENV is "test" here, which is not
  // "production", so it is enabled unless a test overrides it.
  vi.unstubAllEnvs();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

async function createUser() {
  const [user] = await db
    .insert(users)
    .values({ keycloakSub: `test:${randomUUID()}`, email: "test@example.com" })
    .returning({ id: users.id });
  return user.id;
}

function postRequest(body: unknown) {
  return new Request("http://localhost/api/upload/complete", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

describe("POST /api/upload/complete (dev-only)", () => {
  it("records an uploads row for the current user", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);
    const blobPathname = `uploads/base-${randomUUID()}.pdf`;

    const response = await POST(
      postRequest({
        blobPathname,
        blobUrl: `https://example-store.private.blob.vercel-storage.com/${blobPathname}`,
      }),
    );

    expect(response.status).toBe(201);
    const [row] = await db
      .select()
      .from(uploads)
      .where(and(eq(uploads.userId, userId), eq(uploads.blobPathname, blobPathname)));
    expect(row).toBeDefined();
    expect(row.contentType).toBe("application/pdf");
    expect(row.sizeBytes).toBe(4096);
  });

  it("returns 404 in production so the trusted webhook cannot be bypassed", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);
    const blobPathname = `uploads/base-${randomUUID()}.pdf`;

    const response = await POST(
      postRequest({
        blobPathname,
        blobUrl: `https://example-store.private.blob.vercel-storage.com/${blobPathname}`,
      }),
    );

    expect(response.status).toBe(404);
    const rows = await db
      .select()
      .from(uploads)
      .where(eq(uploads.blobPathname, blobPathname));
    expect(rows).toHaveLength(0);
  });

  it("returns 401 when unauthenticated", async () => {
    vi.mocked(getUserId).mockResolvedValue(null);
    const response = await POST(
      postRequest({
        blobPathname: `uploads/base-${randomUUID()}.pdf`,
        blobUrl: "https://example-store.private.blob.vercel-storage.com/x",
      }),
    );
    expect(response.status).toBe(401);
  });

  it("rejects a blobPathname outside the uploads/ prefix", async () => {
    const userId = await createUser();
    vi.mocked(getUserId).mockResolvedValue(userId);
    const response = await POST(
      postRequest({
        blobPathname: `secrets/base-${randomUUID()}.pdf`,
        blobUrl: "https://example-store.private.blob.vercel-storage.com/x",
      }),
    );
    expect(response.status).toBe(400);
  });
});
