"use client";

import { useEffect, useState } from "react";

type AnalysisStatus = {
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  stage: string | null;
  stageDetail: string | null;
  error: string | null;
};

export function CompletedStatus({ analysisId }: { analysisId: string }) {
  return (
    <p className="text-green-700">
      Analysis complete.{" "}
      <a className="underline" href={`/analysis/${analysisId}/report`}>
        View report
      </a>
    </p>
  );
}

export function StatusView({ analysisId }: { analysisId: string }) {
  const [data, setData] = useState<AnalysisStatus | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [authExpired, setAuthExpired] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    async function poll() {
      try {
        const res = await fetch(`/api/analyses/${analysisId}`, {
          signal: controller.signal,
        });
        if (cancelled) return;

        if (res.status === 404) {
          setNotFound(true);
          return;
        }

        // A 401 mid-poll means the session is gone; retrying won't help
        // until the user signs in again, so stop polling.
        if (res.status === 401) {
          setAuthExpired(true);
          return;
        }

        if (!res.ok) {
          setPollError("Connection problem — retrying…");
          timeoutId = setTimeout(poll, 2000);
          return;
        }

        const body = (await res.json()) as AnalysisStatus;
        if (cancelled) return;
        setPollError(null);
        setData(body);
        if (body.status === "queued" || body.status === "running") {
          timeoutId = setTimeout(poll, 2000);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") {
          // Aborted by our own cleanup (unmount / analysisId change); silent.
          return;
        }
        setPollError("Connection problem — retrying…");
        timeoutId = setTimeout(poll, 2000);
      }
    }

    poll();
    return () => {
      cancelled = true;
      controller.abort();
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [analysisId]);

  if (notFound) return <p>Analysis not found.</p>;
  if (authExpired) {
    return (
      <p className="text-red-600">
        Your session has expired. Please sign in again.
      </p>
    );
  }
  if (!data) {
    if (pollError) return <p className="text-red-600">{pollError}</p>;
    return <p>Loading…</p>;
  }

  return (
    <div className="space-y-2">
      {pollError && <p className="text-red-600">{pollError}</p>}
      <p>
        Status: <span className="font-mono">{data.status}</span>
      </p>
      {data.stage && (
        <p>
          Stage: <span className="font-mono">{data.stage}</span>
          {data.stageDetail ? ` — ${data.stageDetail}` : null}
        </p>
      )}
      {data.status === "failed" && (
        <p className="text-red-600">Failed: {data.error}</p>
      )}
      {data.status === "complete" && (
        <CompletedStatus analysisId={analysisId} />
      )}
    </div>
  );
}
