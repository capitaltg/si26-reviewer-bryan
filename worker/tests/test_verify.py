from worker import verify
from worker.verify import (
    DeckPage,
    ResolvedFinding,
    SolicitationCitation,
    VerificationContext,
)

DOC = "11111111-1111-1111-1111-111111111111"
OTHER_DOC = "22222222-2222-2222-2222-222222222222"


def _ctx():
    return VerificationContext(
        solicitation_pages={(DOC, 2): "Section L.1: Provide the approach."},
        deck_pages={
            1: DeckPage(
                slide=1,
                native_text="Our approach is a phased rollout.",
                script_text="We narrate the phased rollout here.",
                vision_summary="Timeline bar chart of three phases.",
            )
        },
    )


def _observation(**overrides):
    base = dict(
        reviewer="compliance",
        finding_kind="observation",
        severity="high",
        confidence="medium",
        requirement_id=None,
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.1", 2, "Provide the approach."),
        proposal_slide=1,
        proposal_quote="phased rollout",
        description="Addressed.",
        suggestion="Keep.",
        searched_scope=None,
        requirement_citation=None,
    )
    base.update(overrides)
    return ResolvedFinding(**base)


def _gap(**overrides):
    base = dict(
        reviewer="compliance",
        finding_kind="gap",
        severity="high",
        confidence="medium",
        requirement_id="req-1",
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.1", 2, "Provide the approach."),
        proposal_slide=None,
        proposal_quote=None,
        description="Not addressed.",
        suggestion="Add it.",
        searched_scope="Searched all 1 deck slides.",
        requirement_citation=(DOC, "L.1", 2),
    )
    base.update(overrides)
    return ResolvedFinding(**base)


def _one(finding):
    return verify.verify_findings([finding], _ctx())[0]


def test_observation_verified_by_native_text():
    result = _one(_observation())
    assert result.verification == "verified"
    assert result.solicitation_verified is True
    assert result.proposal_verified is True
    assert result.evidence_provenance == "native_text"
    assert result.evidence["proposal"] == {"slide": 1, "quote": "phased rollout"}


def test_provenance_prefers_script_over_vision():
    result = _one(_observation(proposal_quote="narrate the phased"))
    assert result.evidence_provenance == "script"
    assert result.proposal_verified is True


def test_provenance_falls_back_to_vision_summary():
    result = _one(_observation(proposal_quote="Timeline bar chart"))
    assert result.evidence_provenance == "vision_summary"
    assert result.verification == "verified"


def test_observation_missing_solicitation_quote_is_unverified():
    result = _one(_observation(
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.1", 2, "text not on the page"),
    ))
    assert result.verification == "unverified"
    assert result.solicitation_verified is False
    assert result.proposal_verified is True


def test_observation_both_sides_fail_is_unverified():
    result = _one(_observation(
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.1", 2, "not present"),
        proposal_quote="also not present",
    ))
    assert result.verification == "unverified"
    assert result.solicitation_verified is False
    assert result.proposal_verified is False
    assert result.evidence_provenance is None


def test_observation_nonexistent_slide_is_dropped():
    result = _one(_observation(proposal_slide=99))
    assert result.verification == "dropped"
    assert result.solicitation_verified is True
    assert result.proposal_verified is False


def test_observation_nonexistent_page_is_dropped():
    result = _one(_observation(
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.1", 99, "Provide the approach."),
    ))
    assert result.verification == "dropped"
    assert result.solicitation_verified is False
    assert result.proposal_verified is True
    assert result.evidence_provenance == "native_text"


def test_same_page_number_in_another_document_does_not_verify():
    base_ctx = _ctx()
    ctx = VerificationContext(
        solicitation_pages={
            **base_ctx.solicitation_pages,
            (OTHER_DOC, 2): "This is unrelated attachment text.",
        },
        deck_pages=base_ctx.deck_pages,
    )
    finding = _observation(
        solicitation=SolicitationCitation(
            OTHER_DOC,
            "attachment.pdf",
            "L.1",
            2,
            "Provide the approach.",
        )
    )

    result = verify.verify_findings([finding], ctx)[0]

    assert result.verification == "unverified"
    assert result.solicitation_verified is False
    assert result.proposal_verified is True


def test_requirement_citation_contradiction_is_dropped():
    result = _one(_observation(
        requirement_id="req-1",
        requirement_citation=(DOC, "L.1", 2),
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.2", 2, "Provide the approach."),
    ))
    # Echoed ref "L.2" contradicts the requirement handle's actual ref "L.1".
    assert result.verification == "dropped"
    assert result.solicitation_verified is False
    assert result.proposal_verified is True


def test_gap_verified_by_solicitation_only():
    result = _one(_gap())
    assert result.verification == "verified"
    assert result.solicitation_verified is True
    assert result.proposal_verified is None
    assert result.evidence_provenance is None
    assert result.evidence["searched_scope"] == "Searched all 1 deck slides."
    assert "proposal" not in result.evidence


def test_gap_unverified_when_quote_absent():
    result = _one(_gap(
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.1", 2, "absent quote"),
    ))
    assert result.verification == "unverified"
    assert result.solicitation_verified is False


def test_gap_carrying_proposal_evidence_is_dropped():
    result = _one(_gap(proposal_slide=1, proposal_quote="phased rollout"))
    assert result.verification == "dropped"
    assert result.solicitation_verified is True
    assert result.proposal_verified is None
    assert "proposal" not in result.evidence


def test_observation_missing_proposal_fields_is_dropped():
    result = _one(_observation(proposal_slide=None, proposal_quote=None))
    assert result.verification == "dropped"
    assert result.solicitation_verified is True
    assert result.proposal_verified is False


def test_empty_normalized_quote_does_not_match():
    result = _one(_observation(
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.1", 2, "   "),
    ))
    assert result.solicitation_verified is False


def test_matching_is_whitespace_and_case_insensitive():
    result = _one(_observation(
        solicitation=SolicitationCitation(DOC, "base.pdf", "L.1", 2, "PROVIDE   THE approach"),
    ))
    assert result.solicitation_verified is True
