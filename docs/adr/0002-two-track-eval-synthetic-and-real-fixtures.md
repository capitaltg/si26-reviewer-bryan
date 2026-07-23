# Two-track eval: synthetic seeded-defect fixture for precision/recall, real SA5/CTG pair for classification accuracy and plausibility

**Status:** accepted

The original eval plan (`GOALS.md` §Evaluation plan) assumes an authored,
synthetic deck+script with 8-10 deliberately seeded defects, so finding
precision/recall has a known ground truth. The real fixture pair actually in
the repo (`sa5_rfq.pdf`, `ctg_deck.pdf`) is a genuine live bid with no seeded
defects — applying the seeded-defect precision formula to it would count
every real, valid finding as a false positive, since none of them were
planted on purpose. We considered hand-labeling the real pair's actual known
gaps post-hoc as ground truth, and a three-bucket scheme (matched / clearly
wrong / unlabeled-unscored) applied directly to the real pair, but rejected
both: post-hoc labeling only tests one bid's specific failure modes and
requires real domain-judgment time; an unscored bucket on live data still
leaves precision/recall undefined for the tool's primary demo fixture. We
instead keep two separate tracks: an authored synthetic deck+script with
seeded defects, purpose-built for clean finding precision/recall numbers, and
the real SA5/CTG pair used only for what it's actually suited to —
classification-accuracy eval (does `applies_to`/`obligation_type`/
`obligation_side` match hand-labeled ground truth) and a qualitative,
human-reviewed plausibility check, not a precision score.

## Considered Options

- **Hand-label real findings post-hoc as ground truth.** Rejected: requires
  real reviewer time on this specific bid and only generalizes to that bid's
  failure modes, not a repeatable eval fixture.
- **Three-bucket scoring directly on the real pair** (true positive / false
  positive / unlabeled-unscored). Rejected: still leaves the tool's headline
  demo fixture without a numeric precision/recall claim, and blurs which
  bucket a borderline finding belongs in.

## Consequences

- Building the synthetic fixture (deck + script + seeded defects) is new
  Phase 6 work, not something the SA5/CTG pair already covers.
- Classification accuracy becomes a first-class eval dimension for the real
  pair, since it's the mechanism protecting the deck-specific critique's
  honesty (a silent misclassification is a hidden false negative).
- Demo day numbers on precision/recall come from the synthetic fixture; the
  real SA5/CTG run is presented as a live, qualitative walkthrough, not a
  scored eval.
