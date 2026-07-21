import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReportModel } from "@/lib/report";

const mocks = vi.hoisted(() => ({
  auth: vi.fn(),
  loadReport: vi.fn(),
  redirect: vi.fn((destination: string): never => {
    throw new Error(`redirect:${destination}`);
  }),
}));

vi.mock("@/auth", () => ({ auth: mocks.auth }));
vi.mock("@/lib/report", () => ({ loadReport: mocks.loadReport }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));

import ReportPage from "./page";

const analysisId = "11111111-1111-1111-1111-111111111111";
const model: ReportModel = {
  analysisId,
  deckDocumentId: null,
  sourcePages: [],
  matrix: [],
  applicabilityGroups: [],
  reviewerGroups: [],
  disagreementNotes: [],
  summaryText: "Executive summary.",
};

const props = { params: Promise.resolve({ id: analysisId }) };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ReportPage", () => {
  it("redirects an unauthenticated request to the landing page", async () => {
    mocks.auth.mockResolvedValue(null);

    await expect(ReportPage(props)).rejects.toThrow("redirect:/");
    expect(mocks.loadReport).not.toHaveBeenCalled();
  });

  it("redirects a missing or unowned analysis to the landing page", async () => {
    mocks.auth.mockResolvedValue({ userId: "user-1" });
    mocks.loadReport.mockResolvedValue({ kind: "not_found" });

    await expect(ReportPage(props)).rejects.toThrow("redirect:/");
  });

  it("redirects an incomplete analysis to its status page", async () => {
    mocks.auth.mockResolvedValue({ userId: "user-1" });
    mocks.loadReport.mockResolvedValue({ kind: "not_complete" });

    await expect(ReportPage(props)).rejects.toThrow(
      `redirect:/analysis/${analysisId}`,
    );
  });

  it("renders a completed report", async () => {
    mocks.auth.mockResolvedValue({ userId: "user-1" });
    mocks.loadReport.mockResolvedValue({ kind: "ok", model });

    const html = renderToStaticMarkup(await ReportPage(props));

    expect(html).toContain("Analysis report");
    expect(html).toContain("Executive summary.");
    expect(mocks.loadReport).toHaveBeenCalledWith("user-1", analysisId);
  });
});
