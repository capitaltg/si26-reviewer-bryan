import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  auth: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("@/auth", () => ({ auth: mocks.auth, signOut: mocks.signOut }));

import { AppHeader } from "./app-header";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AppHeader", () => {
  it("shows the app name and a sign-out control for a signed-in user", async () => {
    mocks.auth.mockResolvedValue({ user: { email: "reviewer@example.com" } });

    const html = renderToStaticMarkup(await AppHeader());

    expect(html).toContain("AI Proposal Review Board");
    expect(html).toContain('href="/"');
    expect(html).toContain("Sign out");
    expect(html).toContain("reviewer@example.com");
  });

  it("keeps sign-out available when the signed-in session has no email", async () => {
    mocks.auth.mockResolvedValue({ user: {} });

    const html = renderToStaticMarkup(await AppHeader());

    expect(html).toContain("Sign out");
    expect(html).not.toContain("reviewer@example.com");
  });

  it("shows only the app name when signed out", async () => {
    mocks.auth.mockResolvedValue(null);

    const html = renderToStaticMarkup(await AppHeader());

    expect(html).toContain("AI Proposal Review Board");
    expect(html).not.toContain("Sign out");
  });
});
