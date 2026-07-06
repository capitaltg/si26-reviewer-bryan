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

function FileInput({
  label,
  accept,
  multiple,
  disabled,
  onFiles,
}: {
  label: string;
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="block w-full text-sm"
        onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
      />
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
      <FileInput
        label="Solicitation (base document, PDF) — required"
        accept="application/pdf"
        disabled={!!busy}
        onFiles={(f) => setBase(f[0] ?? null)}
      />
      <FileInput
        label="Amendments (PDF, optional)"
        accept="application/pdf"
        multiple
        disabled={!!busy}
        onFiles={setAmendments}
      />
      <FileInput
        label="Q&A documents (PDF, optional)"
        accept="application/pdf"
        multiple
        disabled={!!busy}
        onFiles={setQAndA}
      />
      <FileInput
        label="Solicitation attachments (PDF, optional)"
        accept="application/pdf"
        multiple
        disabled={!!busy}
        onFiles={setAttachments}
      />
      <FileInput
        label="Proposal deck (PPTX or PDF) — required"
        accept="application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation"
        disabled={!!busy}
        onFiles={(f) => setDeck(f[0] ?? null)}
      />
      <FileInput
        label="Narration script (TXT with 'Slide N:' markers, optional)"
        accept="text/plain"
        disabled={!!busy}
        onFiles={(f) => setScript(f[0] ?? null)}
      />

      <div className="space-y-2 rounded border p-4">
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={consent}
            disabled={!!busy}
            onChange={(e) => setConsent(e.target.checked)}
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
        className="rounded bg-black px-4 py-2 text-white disabled:opacity-40"
      >
        {busy ?? "Analyze"}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
