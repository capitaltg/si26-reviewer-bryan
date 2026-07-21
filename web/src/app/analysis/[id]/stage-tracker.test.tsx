import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StageTracker } from "./stage-tracker";

function states(html: string): string[] {
  return [...html.matchAll(/data-state="([a-z]+)"/g)].map((m) => m[1]);
}

describe("StageTracker", () => {
  it("checks steps before the current stage and dims later ones", () => {
    const html = renderToStaticMarkup(
      <StageTracker
        status="running"
        stage="map"
        stageDetail="mapping requirements to proposal content"
        error={null}
      />,
    );

    expect(states(html)).toEqual([
      "done",
      "done",
      "done",
      "done",
      "active",
      "pending",
      "pending",
    ]);
    expect(html).toContain("mapping requirements to proposal content");
  });

  it("shows every step pending while the job is queued, even with a stale stage", () => {
    const html = renderToStaticMarkup(
      <StageTracker
        status="queued"
        stage="review"
        stageDetail="stale detail from the interrupted attempt"
        error={null}
      />,
    );

    expect(states(html)).toEqual([
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
  });

  it("checks every step when the analysis is complete", () => {
    const html = renderToStaticMarkup(
      <StageTracker status="complete" stage="done" stageDetail={null} error={null} />,
    );

    expect(states(html)).toEqual([
      "done",
      "done",
      "done",
      "done",
      "done",
      "done",
      "done",
    ]);
  });

  it("anchors the error at the stage that failed", () => {
    const html = renderToStaticMarkup(
      <StageTracker
        status="failed"
        stage="review"
        stageDetail={null}
        error="reviewer pass crashed"
      />,
    );

    expect(states(html)).toEqual([
      "done",
      "done",
      "done",
      "done",
      "done",
      "failed",
      "pending",
    ]);
    expect(html).toContain("reviewer pass crashed");
  });

  it("shows the error when failure occurs before a recognized stage", () => {
    const html = renderToStaticMarkup(
      <StageTracker
        status="failed"
        stage="claimed"
        stageDetail={null}
        error="worker timed out before ingest"
      />,
    );

    expect(states(html)).toEqual([
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
    expect(html).toContain("worker timed out before ingest");
  });
});
