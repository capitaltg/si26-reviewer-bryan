# UI/UX Polish — Design

**Date:** 2026-07-21
**Status:** Approved
**Scope:** Cohesive light-theme polish across the three web screens (home/upload, analysis status, report) before Phase 6. Demo-grade: no new dependencies, plain Tailwind, no behavioral or data-shape changes.

## Goals

- Make the app more intuitive and easier on the eyes for demo viewers.
- Add navigation between screens (shared header) and a visual sense of pipeline progress.
- Keep it simple: no component library, no dark mode, no new pages.

## Non-goals (YAGNI)

- Dark mode (remove the unused dark-mode CSS variables; light-only).
- Past-analyses list page.
- Component library (shadcn/ui etc.) — plain Tailwind only.
- Animations beyond a pulse on the active pipeline stage.
- Mobile-specific deep work beyond what Tailwind utilities give for free.

## Design

### Shared shell (`web/src/app/layout.tsx`, `globals.css`)

- Metadata title: "AI Proposal Review Board" (replaces "Create Next App" boilerplate).
- Slim app header on every page: app name on the left linking to `/`; on the right, sign-out button showing the signed-in user's email (only when a session exists). Rendered from the root layout via a small server component so individual pages stop duplicating the sign-out form.
- Page background `bg-slate-50`; content presented in white cards (`bg-white rounded-lg border`).
- Body font switches to the already-loaded Geist Sans variable instead of Arial. Remove the `prefers-color-scheme: dark` block and dark CSS variables from `globals.css`.

### Home / upload (`page.tsx`, `upload-form.tsx`)

- Signed-out state: centered sign-in card (Keycloak button; dev sign-in form when enabled).
- Upload form grouped into two labeled card sections:
  - **Solicitation**: base document (required badge), amendments, Q&A, attachments (optional badges).
  - **Proposal**: deck (required badge), narration script (optional badge).
- Each file field shows a line with the chosen file name(s) — for multi-file fields, names plus a count.
- Attestation checkboxes styled into their own card, content unchanged.
- Submit button: full-width primary button; keeps the existing busy-label behavior ("Uploading X…", "Starting analysis…") and adds a small CSS spinner while busy.
- No changes to upload logic, validation, or API calls.

### Status page (`analysis/[id]/page.tsx`, `status-view.tsx`)

- Vertical stage tracker replacing the raw status/stage text. Fixed step list matching the worker pipeline (`worker/src/worker/pipeline.py`):
  1. Ingest
  2. Vision
  3. Script alignment *(if script provided)*
  4. Extract
  5. Map
  6. Review
  7. Assemble report (stage `orchestrate`)
- Completion inferred by position: steps before the current stage render as checked; the current step is highlighted with a pulse and shows `stageDetail` underneath; later steps are dimmed. Stage `claimed`/`queued` → nothing checked yet; stage `done`/status `complete` → all checked.
- Failed state: red error card anchored at the stage that was current when the failure occurred.
- Complete state: prominent "View report" primary button (replaces the text link).
- Polling logic, error/auth-expired handling unchanged.

### Report page (`report/page.tsx`, `report-view.tsx`)

- Severity summary strip at the top: counts of high / medium / low findings (derived from the existing model, no loader changes).
- Each section (executive summary, disagreements, traceability matrix, findings) wrapped in a white card with consistent heading style.
- Matrix: subtle zebra striping; coverage status rendered as a colored chip keyed off the existing status strings.
- Findings: existing chips/citations unchanged in behavior; spacing and typography tightened.
- Citation modal: larger max width, clearer close button. Same fetch/object-URL behavior.

## Testing

- Existing tests must stay green: `report-view.test.tsx`, `report/page.test.tsx`, `status-view.test.tsx`, plus lib/api tests (untouched).
- Styling changes are class-level only. Where tests assert on text that changes (e.g., status page raw stage text replaced by the tracker), update the assertions to the new rendering.
- Add light assertions for new intuitive behavior: stage tracker marks prior steps complete and shows current stage detail; severity summary shows correct counts; upload form shows chosen file names.

## Constraints

- `web/AGENTS.md`: this Next.js version differs from training data — consult `node_modules/next/dist/docs/` before writing code.
- No new dependencies.
