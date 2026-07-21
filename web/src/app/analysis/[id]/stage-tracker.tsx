const PIPELINE_STAGES: { key: string; label: string; note?: string }[] = [
  { key: "ingest", label: "Ingest documents" },
  { key: "vision", label: "Vision enrichment" },
  { key: "script_align", label: "Script alignment", note: "if script provided" },
  { key: "extract", label: "Extract requirements" },
  { key: "map", label: "Map requirements to slides" },
  { key: "review", label: "Compliance / technical / evaluator review" },
  { key: "orchestrate", label: "Assemble report" },
];

type StepState = "done" | "active" | "failed" | "pending";

const MARKER_CLASS: Record<StepState, string> = {
  done: "bg-green-600 text-white",
  active: "bg-blue-600",
  failed: "bg-red-600 text-white",
  pending: "border border-slate-300",
};

export function StageTracker({
  status,
  stage,
  stageDetail,
  error,
}: {
  status: "queued" | "running" | "complete" | "failed";
  stage: string | null;
  stageDetail: string | null;
  error: string | null;
}) {
  const currentIndex =
    status === "complete"
      ? PIPELINE_STAGES.length
      : status === "queued" || stage === "claimed" || stage === null
        ? -1
        : status !== "failed" && stage === "done"
          ? PIPELINE_STAGES.length
          : PIPELINE_STAGES.findIndex((step) => step.key === stage);
  const unanchoredFailure = status === "failed" && currentIndex === -1;

  return (
    <div>
      <ol className="space-y-1">
        {PIPELINE_STAGES.map((step, index) => {
          let state: StepState = "pending";
          if (index < currentIndex) state = "done";
          else if (index === currentIndex)
            state = status === "failed" ? "failed" : "active";
          return (
            <li
              key={step.key}
              data-state={state}
              className="flex items-start gap-3 py-1.5"
            >
              <span
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${MARKER_CLASS[state]}`}
              >
                {state === "done" && "✓"}
                {state === "failed" && "!"}
                {state === "active" && (
                  <span className="h-2 w-2 animate-pulse rounded-full bg-white" />
                )}
              </span>
              <span className="min-w-0">
                <span
                  className={`block text-sm ${
                    state === "pending"
                      ? "text-slate-400"
                      : "font-medium text-slate-800"
                  }`}
                >
                  {step.label}
                  {step.note && (
                    <span className="ml-1 text-xs font-normal text-slate-400">
                      ({step.note})
                    </span>
                  )}
                </span>
                {state === "active" && stageDetail && (
                  <span className="block text-xs text-slate-500">
                    {stageDetail}
                  </span>
                )}
                {state === "failed" && (
                  <span className="mt-1 block rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                    {error ?? "Analysis failed."}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>
      {unanchoredFailure && (
        <p className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error ?? "Analysis failed."}
        </p>
      )}
    </div>
  );
}
