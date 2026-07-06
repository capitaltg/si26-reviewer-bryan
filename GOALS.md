# AI Proposal Review Board — Project Goals

## One-line summary

An advisory-only web tool that reviews a GovCon oral-proposal package (PowerPoint deck + planned narration script) against the actual solicitation, and produces grounded, citation-backed findings from three specialized AI reviewers — without ever editing the proposal itself.

## Problem

Government proposal teams run multiple internal review rounds (compliance, technical, red team) before submission. These reviews bottleneck on scarce experienced people and significant time. The mechanical/compliance layer of review — "is every Section L requirement addressed, is the deck within limits, do the numbers agree across volumes" — is checkable from documents alone, yet consumes hours of expert time better spent on judgment calls.

## Product stance (non-negotiable design decisions)

- **Advisory only.** The tool suggests, criticizes, and flags gaps. It never edits or generates proposal content. The human reviewer makes every judgment call and every edit.
- **Grounded or nothing.** Every finding carries a two-sided citation: where the requirement comes from in the solicitation (e.g., "Section L.3.2, page 8") and where it is or isn't addressed in the proposal (e.g., "Slide 14"). Unverifiable findings are worse than no findings — a hallucinated compliance citation erodes the trust the tool exists to build.
- **Zero setup.** Works from exactly the documents already produced for this pursuit: the solicitation and the current draft. No historical proposal library, no migration, no integration. (This is the differentiator vs. platforms like Vultron/GovDash, which get value from an indexed corpus of past proposals — at the cost of onboarding friction.)
- **Raise the floor, don't replace the ceiling.** The tool handles the mechanical/compliance layer so human reviewers spend their time on institutional knowledge and judgment the AI cannot have (customer hot buttons, debrief history, competitive positioning).

## Target use case

Oral-proposal task-order competitions (confirmed format for the target vehicle): the evaluated artifact is a PowerPoint deck, typically accompanied by written volumes (price, past performance) and — where the team's process produces one — a planned per-slide narration script.

**Honest ceiling, stated up front:** the tool critiques the *planned* materials (deck + script), not the live delivery. A presenter can still deviate or ad-lib. Framed positively, this makes it a **rehearsal-prep tool**: "does your planned narration actually cover what you'll be scored on."

## Anchor feature

**Two-sided compliance / traceability matrix.** Extract every "shall/must/will" requirement from Section L and every evaluation factor from Section M, then map each requirement to where (or whether) the deck/script addresses it. Automatic gap flagging. This is the single highest-value feature — well-defined, verifiable, and exactly what compliance reviewers spend hours doing by hand. Everything else builds on it.

## The three reviewers (MVP)

Each reviewer is grounded in **distinct data**, not just a distinct persona prompt. All three read from the shared traceability matrix but apply different lenses.

| Reviewer | Grounded in | Job |
|---|---|---|
| **Compliance Officer** | Extracted Section L requirements, slide/page limits and formatting rules, the FAR/DFARS clauses actually incorporated by reference in this solicitation | Mechanical completeness: every requirement addressed somewhere, limits respected, formatting compliant. Strictest, most checklist-like — the category with real ground truth. |
| **Technical/SME** | The SOW/PWS (actual technical scope) + the deck's technical content | Feasibility and internal consistency: approach addresses the scope, staffing matches claimed complexity, timelines plausible, claims backed rather than asserted. |
| **Government Evaluator** | Section M factors with their stated relative weighting; public adjectival rating definitions (Outstanding/Good/Acceptable/Marginal/Unacceptable) where available | Simulate scoring against the actual weighted factors; flag sections likely to land "Acceptable but not Good" and why. |

Every finding is structured output (enforced by schema, not prompt asks): severity, confidence, two-sided evidence citation, suggested improvement. An orchestrator dedupes (semantic clustering, not string matching), prioritizes by Section M weighting, and produces an executive summary. Findings retain their reviewer of origin so the user knows which lens each suggestion comes from. Cross-reviewer disagreement is surfaced as a signal, not silently resolved.

## Ingestion pipeline

1. **PPT → PDF at ingestion** (native "Save As PDF" path that preserves the text layer — verify on a real export; a rasterized export forces OCR everywhere). One slide = one page = one citation anchor, unified with the written volumes' pipeline.
2. **Native text extraction first** — fast, free, reliable where a text layer exists.
3. **Vision-LLM pass for diagram-heavy slides** (org charts, schedules, architecture diagrams) — a multimodal model interprets relationships ("who reports to whom"), which classical OCR cannot. No separate OCR engine. At deck scale (tens of slides), run every slide through the vision pass rather than building a routing heuristic.
4. **Narration script** (optional input): plain text with explicit per-slide markers (`Slide 1:`, `Slide 2:` …). Alignment is a formatting convention, not an NLP problem. The script is dense prose — it gives reviewers far richer material than sparse slide bullets, and closes most of the "can't see the presentation" gap.
5. **Both documents addressable**: the solicitation gets the same render-and-jump treatment as the deck, so two-sided citations resolve on both ends.

## Web app (thin shell around the pipeline)

Three screens, nothing more for MVP:

1. **Upload** — solicitation, deck, optional narration script.
2. **Processing/status** — analysis takes minutes; uploads kick off a background job, UI streams stage-level progress ("extracting requirements… 12/34 mapped… running Compliance review…"). The progress narration is itself demo material.
3. **Report** — traceability matrix + findings grouped by reviewer; the killer interaction is finding → click → rendered source page/slide. Slides are rendered to images at ingestion anyway (needed for the vision pass), so display is nearly free.

**Data handling:** uploaded proposals are private, short-lived (deleted after session or N days), never in a public bucket. Real drafts require the owner's explicit sign-off (including that content transits an LLM API), a check of distribution markings (Proprietary / Source Selection Sensitive / CUI / ITAR = stop and get info-security sign-off), and a sanitized or synthetic stand-in for any public demo.

## Evaluation plan (built in week 1, not week 6)

- Pick one real, unclassified solicitation from SAM.gov; hand-extract its Section L/M once to establish extraction ground truth.
- Author a plausible proposal deck (+ script) against it, seeding 8–10 known defects: an unaddressed requirement, a staffing number inconsistent between volumes, a slide-limit violation, a vague unsupported technical claim, etc.
- Run the system; report **precision/recall** of findings against the seeded defects. Track over iterations.
- Stretch: validate against a real draft + real color-team comments from the same round, if access is cleared — the only way to answer "does it catch what real reviewers caught."
- Supplementary grounding source: GAO bid-protest decisions (public, free) as a taxonomy of real adjudicated proposal weaknesses.

## Demo-day success criteria

- A live, auto-generated traceability matrix on a real solicitation, with actual gaps found.
- Quantified precision/recall against the labeled defect set — presented like an eval, not a vibe.
- Click-to-source citations that resolve to the right slide/page every time.
- A shown instance of reviewers disagreeing, surfaced as useful signal.
- Evidence it survives a real, messy government solicitation (amendments, cross-references), not a clean toy.

## Explicitly out of scope for MVP

- Reviewer debate/negotiation rounds (real value, v2)
- User-configurable reviewer panels
- Win-probability / score prediction (no outcome data to calibrate against; uncalibrated prediction is a credibility risk)
- Full FAR/DFARS knowledge base (scope to clauses cited in the target solicitation)
- Competitor Reviewer (generic filler without real competitive intel)
- Simulated review meetings / multi-turn deliberation UI
- Editing or generating proposal content, ever
- Proposal libraries, user accounts, history dashboards
- Auto-alignment of unmarked narration scripts to slides
- Live-delivery analysis (audio/video of actual orals)

## Open questions

- Is the leave-behind deck the official evaluated record, or is live narration also scored? (Determines how complete the tool's coverage claim can be.)
- Does the target team produce a written narration script as standard process, or is it an optional input in practice?
- Is a real draft + real reviewer feedback obtainable with proper clearance, or does validation stay fully on the synthetic path?
- Distribution markings on any real draft under consideration — checked and cleared?

## Key risks to keep honest about

- **Persona theater:** multiple reviewers only beat one good reviewer if grounding genuinely differs. If distinct grounding slips, collapse to one structured reviewer and spend the time on extraction quality.
- **Hallucinated compliance citations** are actively dangerous because people trust them — schema-enforced citations plus click-to-verify is the mitigation, and the eval measures it.
- **Document engineering is the unglamorous hard part.** Real solicitations are messy. Extraction quality, not orchestration cleverness, is where this succeeds or stalls.
- **Severity/confidence labels are uncalibrated by default** — treat them as reviewer opinion until measured against human agreement.
