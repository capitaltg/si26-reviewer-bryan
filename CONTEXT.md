# AI Proposal Review Board

Advisory-only critique of a GovCon oral-proposal artifact against the actual
solicitation. See `GOALS.md` for full product framing and `docs/adr/` for the
decisions behind the terms below.

## Language

**Rehearsal-prep tool**:
The product's positioning as a deck-specific critique tool — does the
planned oral presentation (deck + narration script) cover what it'll
actually be scored on. Not a whole-submission compliance-matrix competitor.
_Avoid_: "proposal reviewer," "compliance matrix tool" (both imply
whole-submission scope, which this explicitly is not — see
[ADR-0001](docs/adr/0001-reposition-around-deck-specific-critique.md)).

**Deck-applicable requirement**:
A Section L/M or SOW/PWS record classified `applies_to=deck`,
`obligation_type=content`, `obligation_side=quoter` — the only kind that can
produce a traceability matrix row or ground a reviewer gap. Everything else
is a real requirement that this artifact set was never going to answer.
_Avoid_: "requirement" alone when the deck-applicability distinction matters.

**Not coverage-scored**:
The report section holding every effective requirement excluded from the
matrix (`other_component`, `administrative`, `deck_context`,
`unclassified`), shown with its classification rationale, never a fake
`missing` status. A trust feature under the rehearsal-prep positioning, not
a shortfall to downplay.
_Avoid_: "excluded" or "filtered out" — both read as an error rather than
correct triage.

**Classification**:
The three-axis judgment (`applies_to` / `obligation_type` / `obligation_side`)
extraction assigns to every requirement, deciding whether it can ever enter
the matrix. Distinct from *extraction* (did we find the requirement at all)
and *finding* accuracy (did a reviewer catch a real defect).

**Seeded defect**:
A deliberately authored, known flaw planted in a synthetic eval fixture
(deck + script), used to compute finding precision/recall. Distinct from a
real finding on a live bid (e.g. SA5/CTG), which has no seeded ground truth —
see [ADR-0002](docs/adr/0002-two-track-eval-synthetic-and-real-fixtures.md).
