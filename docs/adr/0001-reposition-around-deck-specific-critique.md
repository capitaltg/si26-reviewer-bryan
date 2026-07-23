# Reposition around deck-specific critique; keep MVP scoped to the oral-deck artifact

**Status:** accepted

The deck-applicability classifier (shipped 2026-07-21) correctly excludes most
Section L/M requirements from the traceability matrix on a real bid (SA5/CTG),
because most requirements genuinely belong to written volumes, price, or
admin process — not the oral deck. Testing against that real pair surfaced
only 2 truly deck-applicable requirements, which read as an underwhelming
result if the product's headline claim is "traceability matrix across the
proposal." We considered expanding intake to the full submission package
(all volumes) so the matrix has real breadth, but that reverses `GOALS.md`'s
locked "Zero setup" stance and was rejected — the original goal was always to
critique the oral-presentation artifact specifically, not the whole
submission. Instead we keep MVP scoped to the deck (+ script) and reposition
the headline pitch: "the only review tool built for the oral-proposal
artifact itself — rehearsal-prep for what you'll actually be scored on."
Zero-setup and grounded-or-nothing citations remain real advantages but move
to supporting claims, since a compliance/traceability matrix alone is not
novel against mature incumbents (Vultron/GovDash) who already build one,
often from an indexed proposal corpus that makes them more accurate over
time. The "Not coverage-scored" report section (already built) becomes a
first-class trust feature under this framing — visible proof the tool knows
what it isn't answering — rather than a leftover to downplay.

## Considered Options

- **Expand intake to the full submission** (written volumes, price, past
  performance) so the matrix covers the whole proposal. Rejected: reverses a
  locked product stance, and was never the actual original goal once
  re-examined — left as a possible post-demo expansion, not an MVP change.
- **Keep the three-part pitch as-is** (guardrails / harness / traceability,
  co-equal). Rejected: the traceability-matrix claim alone doesn't
  differentiate from incumbents who already ship compliance matrices; keeping
  it as the headline invites an unfavorable comparison the product doesn't
  need to invite.

## Consequences

- `GOALS.md`'s "Anchor feature" and problem framing need to foreground
  deck-specific critique, not the traceability matrix in isolation.
- Phase 6 demo prep should showcase the "Not coverage-scored" section
  deliberately, not treat it as a shortfall to hide.
- Future multi-artifact expansion (if pursued) is a distinct, later decision —
  not assumed by this one.
