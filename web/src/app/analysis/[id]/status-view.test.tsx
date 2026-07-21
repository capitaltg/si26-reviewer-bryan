import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CompletedStatus } from "./status-view";

describe("CompletedStatus", () => {
  it("links a completed analysis to its terminal report", () => {
    const analysisId = "11111111-1111-1111-1111-111111111111";
    const html = renderToStaticMarkup(
      <CompletedStatus analysisId={analysisId} />,
    );

    expect(html).toContain(`href="/analysis/${analysisId}/report"`);
    expect(html).toContain("View report");
  });
});
