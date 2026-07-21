"use client";

import { upload } from "@vercel/blob/client";
import { useRouter } from "next/navigation";
import { useState } from "react";

type Kind =
  | "solicitation_base"
  | "solicitation_amendment"
  | "solicitation_q_and_a"
  | "solicitation_attachment"
  | "deck"
  | "script";

type PendingDoc = { kind: Kind; file: File };

export function FileInput({
  label,
  accept,
  multiple,
  disabled,
  required,
  selected,
  onFiles,
}: {
  label: string;
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  required?: boolean;
  selected: File[];
  onFiles: (files: File[]) => void;
}) {
  return (
    <label className="block space-y-1">
      <span className="flex items-center gap-2 text-sm font-medium text-slate-800">
        {label}
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            required
              ? "bg-slate-900 text-white"
              : "bg-slate-100 text-slate-500"
          }`}
        >
          {required ? "Required" : "Optional"}
        </span>
      </span>
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
        onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
      />
      {selected.length > 0 && (
        <span className="block text-xs text-slate-500">
          {selected.length > 1 ? `${selected.length} files: ` : ""}
          {selected.map((file) => file.name).join(", ")}
        </span>
      )}
    </label>
  );
}

export function UploadForm() {
  const router = useRouter();
  const [base, setBase] = useState<File | null>(null);
  const [amendments, setAmendments] = useState<File[]>([]);
  const [qAndA, setQAndA] = useState<File[]>([]);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [deck, setDeck] = useState<File | null>(null);
  const [script, setScript] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [markings, setMarkings] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ready = base && deck && consent && markings && !busy;

  async function submit() {
    if (!base || !deck) return;
    setError(null);
    const docs: PendingDoc[] = [
      { kind: "solicitation_base", file: base },
      ...amendments.map(
        (file): PendingDoc => ({ kind: "solicitation_amendment", file }),
      ),
      ...qAndA.map(
        (file): PendingDoc => ({ kind: "solicitation_q_and_a", file }),
      ),
      ...attachments.map(
        (file): PendingDoc => ({ kind: "solicitation_attachment", file }),
      ),
      { kind: "deck", file: deck },
      ...(script ? [{ kind: "script" as Kind, file: script }] : []),
    ];
    try {
      const uploaded = [];
      for (const doc of docs) {
        setBusy(`Uploading ${doc.file.name}…`);
        const blob = await upload(`uploads/${doc.file.name}`, doc.file, {
          access: "private",
          handleUploadUrl: "/api/upload",
        });
        // In production, Vercel Blob's onUploadCompleted webhook records the
        // uploads row. That webhook can't reach localhost, so in local dev we
        // record it directly via the dev-only completion endpoint.
        if (process.env.NODE_ENV !== "production") {
          const done = await fetch("/api/upload/complete", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              blobPathname: blob.pathname,
              blobUrl: blob.url,
            }),
          });
          if (!done.ok) {
            throw new Error(
              `dev upload completion failed: ${(await done.text()) || done.status}`,
            );
          }
        }
        uploaded.push({
          kind: doc.kind,
          displayName: doc.file.name,
          blobPathname: blob.pathname,
        });
      }
      setBusy("Starting analysis…");
      const res = await fetch("/api/analyses", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          consentLlmTransit: consent,
          distributionAttestation: markings,
          documents: uploaded,
        }),
      });
      if (!res.ok) throw new Error((await res.text()) || "creation failed");
      const { id } = (await res.json()) as { id: string };
      router.push(`/analysis/${id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Solicitation
        </h2>
        <FileInput
          label="Base document (PDF)"
          accept="application/pdf"
          required
          disabled={!!busy}
          selected={base ? [base] : []}
          onFiles={(f) => setBase(f[0] ?? null)}
        />
        <FileInput
          label="Amendments (PDF)"
          accept="application/pdf"
          multiple
          disabled={!!busy}
          selected={amendments}
          onFiles={setAmendments}
        />
        <FileInput
          label="Q&A documents (PDF)"
          accept="application/pdf"
          multiple
          disabled={!!busy}
          selected={qAndA}
          onFiles={setQAndA}
        />
        <FileInput
          label="Attachments (PDF)"
          accept="application/pdf"
          multiple
          disabled={!!busy}
          selected={attachments}
          onFiles={setAttachments}
        />
      </section>

      <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Proposal
        </h2>
        <FileInput
          label="Proposal deck (PPTX or PDF)"
          accept="application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation"
          required
          disabled={!!busy}
          selected={deck ? [deck] : []}
          onFiles={(f) => setDeck(f[0] ?? null)}
        />
        <FileInput
          label="Narration script (TXT with 'Slide N:' markers)"
          accept="text/plain"
          disabled={!!busy}
          selected={script ? [script] : []}
          onFiles={(f) => setScript(f[0] ?? null)}
        />
      </section>

      <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={consent}
            disabled={!!busy}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            I am authorized to submit these documents and consent to their
            content being processed by a third-party LLM API (Anthropic).
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={markings}
            disabled={!!busy}
            onChange={(e) => setMarkings(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            I have checked distribution markings: none of these documents are
            marked Proprietary, Source Selection Sensitive, CUI, or ITAR. (If
            any are, stop and get info-security sign-off first.)
          </span>
        </label>
      </div>

      <button
        disabled={!ready}
        onClick={submit}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-slate-900"
      >
        {busy && (
          <span
            aria-hidden
            className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
          />
        )}
        {busy ?? "Analyze"}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
