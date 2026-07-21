import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { FileInput } from "./upload-form";

describe("FileInput", () => {
  it("shows a required badge and the chosen file name", () => {
    const html = renderToStaticMarkup(
      <FileInput
        label="Solicitation (base document, PDF)"
        accept="application/pdf"
        required
        selected={[new File(["x"], "rfq.pdf", { type: "application/pdf" })]}
        onFiles={() => {}}
      />,
    );

    expect(html).toContain("Required");
    expect(html).toContain("rfq.pdf");
  });

  it("shows an optional badge and a count for multiple files", () => {
    const html = renderToStaticMarkup(
      <FileInput
        label="Amendments (PDF)"
        accept="application/pdf"
        multiple
        selected={[
          new File(["x"], "amend-1.pdf", { type: "application/pdf" }),
          new File(["x"], "amend-2.pdf", { type: "application/pdf" }),
        ]}
        onFiles={() => {}}
      />,
    );

    expect(html).toContain("Optional");
    expect(html).toContain("2 files:");
    expect(html).toContain("amend-1.pdf");
    expect(html).toContain("amend-2.pdf");
  });

  it("shows no selection line when nothing is chosen", () => {
    const html = renderToStaticMarkup(
      <FileInput
        label="Narration script"
        accept="text/plain"
        selected={[]}
        onFiles={() => {}}
      />,
    );

    expect(html).not.toContain("files:");
  });
});
