"""Deterministic, LLM-free citation verification for reviewer findings.

Owns the finding data contract shared with reviewers.py. Pure functions only:
no database access, no network, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SolicitationCitation:
    document_id: str
    document_name: str
    ref: str
    page: int
    quote: str


@dataclass(frozen=True)
class DeckPage:
    slide: int
    native_text: str
    script_text: str
    vision_summary: str


@dataclass(frozen=True)
class VerificationContext:
    solicitation_pages: dict[tuple[str, int], str]
    deck_pages: dict[int, DeckPage]


@dataclass(frozen=True)
class ResolvedFinding:
    reviewer: str
    finding_kind: Literal["gap", "observation"]
    severity: str
    confidence: str
    requirement_id: str | None
    solicitation: SolicitationCitation
    proposal_slide: int | None
    proposal_quote: str | None
    description: str
    suggestion: str
    searched_scope: str | None
    requirement_citation: tuple[str, str, int] | None

    def __post_init__(self) -> None:
        if self.finding_kind not in ("gap", "observation"):
            raise ValueError("finding_kind must be 'gap' or 'observation'")


@dataclass(frozen=True)
class VerifiedFinding:
    finding: ResolvedFinding
    solicitation_verified: bool
    proposal_verified: bool | None
    evidence_provenance: str | None
    verification: str  # "verified" | "unverified" | "dropped"
    evidence: dict


# Proposal sources are checked in this order; the first match sets provenance.
# vision_summary is last because it is itself LLM output (weaker grounding).
_PROVENANCE_ORDER = ("native_text", "script", "vision_summary")


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _quote_matches(quote: str, haystack: str) -> bool:
    needle = _normalize(quote)
    if not needle:
        return False
    return needle in _normalize(haystack)


def verify_findings(
    findings: list[ResolvedFinding], ctx: VerificationContext
) -> list[VerifiedFinding]:
    return [_verify_one(finding, ctx) for finding in findings]


def _structural_failures(
    finding: ResolvedFinding, ctx: VerificationContext
) -> tuple[bool, bool]:
    is_observation = finding.finding_kind == "observation"

    solicitation_failure = (
        finding.solicitation.document_id,
        finding.solicitation.page,
    ) not in ctx.solicitation_pages

    # An echoed citation must not contradict a resolved requirement handle.
    if finding.requirement_id is not None and finding.requirement_citation is not None:
        echoed = (
            finding.solicitation.document_id,
            finding.solicitation.ref,
            finding.solicitation.page,
        )
        if echoed != finding.requirement_citation:
            solicitation_failure = True

    has_proposal_shape = (
        finding.proposal_slide is not None and finding.proposal_quote is not None
    )
    if is_observation:
        proposal_failure = (
            not has_proposal_shape or finding.proposal_slide not in ctx.deck_pages
        )
    else:
        proposal_failure = (
            finding.proposal_slide is not None or finding.proposal_quote is not None
        )

    return solicitation_failure, proposal_failure


def _match_provenance(finding: ResolvedFinding, ctx: VerificationContext) -> str | None:
    page = ctx.deck_pages[finding.proposal_slide]
    sources = {
        "native_text": page.native_text,
        "script": page.script_text,
        "vision_summary": page.vision_summary,
    }
    for name in _PROVENANCE_ORDER:
        if _quote_matches(finding.proposal_quote, sources[name]):
            return name
    return None


def _build_evidence(finding: ResolvedFinding) -> dict:
    solicitation = {
        "document_id": finding.solicitation.document_id,
        "document_name": finding.solicitation.document_name,
        "ref": finding.solicitation.ref,
        "page": finding.solicitation.page,
        "quote": finding.solicitation.quote,
    }
    if finding.finding_kind == "gap":
        return {"solicitation": solicitation, "searched_scope": finding.searched_scope}
    return {
        "solicitation": solicitation,
        "proposal": {"slide": finding.proposal_slide, "quote": finding.proposal_quote},
    }


def _verify_one(finding: ResolvedFinding, ctx: VerificationContext) -> VerifiedFinding:
    is_observation = finding.finding_kind == "observation"
    solicitation_structural, proposal_structural = _structural_failures(finding, ctx)

    if solicitation_structural:
        solicitation_verified = False
    else:
        page_text = ctx.solicitation_pages[
            (finding.solicitation.document_id, finding.solicitation.page)
        ]
        solicitation_verified = _quote_matches(finding.solicitation.quote, page_text)

    if is_observation:
        provenance = (
            None if proposal_structural else _match_provenance(finding, ctx)
        )
        proposal_verified: bool | None = provenance is not None
        applicable_pass = solicitation_verified and proposal_verified
    else:
        provenance = None
        proposal_verified = None
        applicable_pass = solicitation_verified

    structural_failure = solicitation_structural or proposal_structural

    return VerifiedFinding(
        finding=finding,
        solicitation_verified=solicitation_verified,
        proposal_verified=proposal_verified,
        evidence_provenance=provenance,
        verification=(
            "dropped"
            if structural_failure
            else "verified" if applicable_pass else "unverified"
        ),
        evidence=_build_evidence(finding),
    )
