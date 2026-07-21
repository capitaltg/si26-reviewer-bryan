import copy

import psycopg
import pytest

from conftest import insert_analysis
from worker import reviewers

BASE_DOC = "00000000-0000-0000-0000-0000000000a1"
DECK_DOC = "00000000-0000-0000-0000-0000000000a2"
OTHER_BASE_DOC = "00000000-0000-0000-0000-0000000000a3"


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, name, input):
        self.name = name
        self.input = input


class _FakeMessage:
    def __init__(self, stop_reason, tool_input=None, tool_name=None):
        self.stop_reason = stop_reason
        self.content = (
            []
            if tool_input is None
            else [_FakeToolUseBlock(tool_name or reviewers.FINDINGS_TOOL["name"], tool_input)]
        )


class _FakeMessagesClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def _fake_client(monkeypatch, responses):
    client = type("FakeClient", (), {})()
    client.messages = _FakeMessagesClient(responses)
    monkeypatch.setattr(reviewers, "_get_client", lambda: client)
    return client.messages


def _insert_document(conn, analysis_id, document_id, kind, display_name):
    conn.execute(
        """
        INSERT INTO documents
            (id, analysis_id, kind, display_name, blob_pathname, blob_url, content_type)
        VALUES (%s, %s, %s, %s, %s, %s, 'application/pdf')
        """,
        (document_id, analysis_id, kind, display_name,
         f"documents/{document_id}", f"https://example.test/{document_id}"),
    )


def _insert_page(conn, document_id, page_no, text, script_text=None, vision_summary=None):
    conn.execute(
        """
        INSERT INTO pages
            (document_id, page_no, text, image_blob_pathname, image_blob_url,
             script_text, vision_summary)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (document_id, page_no, text,
         f"img/{document_id}/{page_no}.png", f"https://example.test/{document_id}/{page_no}.png",
         script_text, vision_summary),
    )


def _insert_requirement(
    conn,
    analysis_id,
    source,
    ref,
    text,
    page_no,
    weight=None,
    *,
    applies_to="deck",
    obligation_type="content",
    obligation_side="quoter",
    classification_rationale="test classification",
):
    return str(conn.execute(
        """
        INSERT INTO requirements
            (analysis_id, source_document_id, source, ref, text, page_no, weight,
             applies_to, obligation_type, obligation_side,
             classification_rationale)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            analysis_id, BASE_DOC, source, ref, text, page_no, weight,
            applies_to, obligation_type, obligation_side,
            classification_rationale,
        ),
    ).fetchone()[0])


def _package(conn, *, with_m=True, with_sow=False):
    analysis_id = insert_analysis(conn)
    _insert_document(conn, analysis_id, BASE_DOC, "solicitation_base", "base.pdf")
    _insert_page(conn, BASE_DOC, 1, "Section L.1: Provide the technical approach.")
    _insert_page(conn, BASE_DOC, 2, "Section M.1: Technical approach is most important.")
    if with_sow:
        _insert_page(conn, BASE_DOC, 3, "SOW 2.1: Use a phased rollout.")
    _insert_document(conn, analysis_id, DECK_DOC, "deck", "deck.pptx")
    _insert_page(conn, DECK_DOC, 1, "Our technical approach is a phased rollout.",
                 script_text="We narrate the phased rollout.",
                 vision_summary="Timeline chart of phases.")
    l_id = _insert_requirement(conn, analysis_id, "L", "L.1", "Provide the technical approach.", 1)
    if with_m:
        _insert_requirement(
            conn, analysis_id, "M", "M.1", "Technical approach is most important.", 2,
            weight="most important", obligation_side="government",
        )
    if with_sow:
        _insert_requirement(conn, analysis_id, "SOW", "SOW 2.1", "Use a phased rollout.", 3)
    return analysis_id, l_id


def test_reviewer_primary_sets_exclude_non_deck_and_legacy_rows(conn):
    analysis_id, included_id = _package(conn, with_m=False)
    other_id = _insert_requirement(
        conn, analysis_id, "L", "L.other", "Written response.", 1,
        applies_to="other_component",
    )
    admin_id = _insert_requirement(
        conn, analysis_id, "L", "L.admin", "Portal deadline.", 1,
        applies_to="administrative",
    )
    legacy_id = str(conn.execute(
        """
        INSERT INTO requirements
            (analysis_id, source_document_id, source, ref, text, page_no)
        VALUES (%s, %s, 'L', 'L.legacy', 'Legacy row.', 1)
        RETURNING id
        """,
        (analysis_id, BASE_DOC),
    ).fetchone()[0])
    for requirement_id in (included_id, other_id, admin_id, legacy_id):
        conn.execute(
            """
            INSERT INTO mappings (requirement_id, status, slide_refs, rationale)
            VALUES (%s, 'covered', '[1]'::jsonb, 'Pre-classification mapping.')
            """,
            (requirement_id,),
        )

    primary = reviewers._load_primary(
        conn, analysis_id, reviewers.REVIEWER_SPECS[0]
    )
    matrix = reviewers._load_matrix(
        conn, analysis_id, reviewers.REVIEWER_SPECS[0]
    )

    assert [(req.id, req.ref) for req in primary] == [(included_id, "L.1")]
    assert [(row[0], row[1]) for row in matrix] == [("L.1", "L")]


def test_compliance_prompt_marks_constraints_observation_only(conn):
    analysis_id, _ = _package(conn, with_m=False)
    _insert_requirement(
        conn, analysis_id, "limit", "LIMIT.1", "Do not exceed 20 slides.", 1,
        obligation_type="constraint",
        classification_rationale="Deck slide-count constraint",
    )
    spec = reviewers.REVIEWER_SPECS[0]
    primary = reviewers._load_primary(conn, analysis_id, spec)
    req_by_handle, doc_by_handle, doc_handle_by_id = reviewers._assign_handles(primary)
    prompt = reviewers._build_prompt(
        spec, req_by_handle, doc_by_handle, doc_handle_by_id, [],
        reviewers._load_deck_pages(conn, analysis_id),
    )

    assert "LIMIT.1" in prompt
    assert "obligation_type=constraint" in prompt
    assert "never emit a gap for a constraint" in prompt.lower()


def _observation_input(
    *,
    ref="L.1",
    page=1,
    solicitation_quote="Provide the technical approach.",
):
    return {
        "findings": [
            {
                "requirement_handle": 1,
                "finding_kind": "observation",
                "severity": "high",
                "confidence": "medium",
                "solicitation_document_handle": 1,
                "solicitation_ref": ref,
                "solicitation_page": page,
                "solicitation_quote": solicitation_quote,
                "proposal_slide": 1,
                "proposal_quote": "phased rollout",
                "description": "The approach is addressed.",
                "suggestion": "Keep it explicit.",
            }
        ]
    }


def _findings_rows(conn, analysis_id):
    return conn.execute(
        """
        SELECT reviewer, finding_kind, requirement_id, verification,
               solicitation_verified, proposal_verified, evidence_provenance, evidence
        FROM findings WHERE analysis_id = %s ORDER BY reviewer, id
        """,
        (analysis_id,),
    ).fetchall()


def test_loaders_ignore_cross_analysis_requirements_and_supersession(conn):
    analysis_id, l_id = _package(conn, with_m=False)
    other_analysis_id = insert_analysis(conn)
    _insert_document(conn, other_analysis_id, OTHER_BASE_DOC, "solicitation_base", "other.pdf")
    _insert_page(conn, OTHER_BASE_DOC, 1, "Other analysis requirement.")

    conn.execute(
        """
        INSERT INTO requirements
            (analysis_id, source_document_id, source, ref, text, page_no,
             supersedes_requirement_id)
        VALUES (%s, %s, 'L', 'OTHER.1', 'Other superseding requirement.', 1, %s)
        """,
        (other_analysis_id, OTHER_BASE_DOC, l_id),
    )
    foreign_id = str(conn.execute(
        """
        INSERT INTO requirements
            (analysis_id, source_document_id, source, ref, text, page_no)
        VALUES (%s, %s, 'L', 'FOREIGN.1', 'Foreign document requirement.', 1)
        RETURNING id
        """,
        (analysis_id, OTHER_BASE_DOC),
    ).fetchone()[0])
    for requirement_id in (l_id, foreign_id):
        conn.execute(
            """
            INSERT INTO mappings (requirement_id, status, slide_refs, rationale)
            VALUES (%s, 'covered', '[1]'::jsonb, 'Covered on slide 1.')
            """,
            (requirement_id,),
        )

    primary = reviewers._load_primary(conn, analysis_id, reviewers.REVIEWER_SPECS[0])
    matrix = reviewers._load_matrix(conn, analysis_id, reviewers.REVIEWER_SPECS[0])

    assert [(req.id, req.ref) for req in primary] == [(l_id, "L.1")]
    assert [(row[0], row[1]) for row in matrix] == [("L.1", "L")]


def test_run_review_resolves_handles_and_persists_verified(conn, monkeypatch):
    analysis_id, l_id = _package(conn, with_m=False)
    messages = _fake_client(monkeypatch, [_FakeMessage("tool_use", _observation_input())])

    reviewers.run_review(conn, analysis_id)

    rows = _findings_rows(conn, analysis_id)
    assert len(rows) == 1
    reviewer, kind, requirement_id, verification, sol_ok, prop_ok, provenance, evidence = rows[0]
    assert reviewer == "compliance"
    assert kind == "observation"
    assert str(requirement_id) == l_id
    assert verification == "verified"
    assert sol_ok is True and prop_ok is True
    assert provenance == "native_text"
    assert evidence["proposal"] == {"slide": 1, "quote": "phased rollout"}
    request = messages.calls[0]
    assert request["max_tokens"] == 16_384
    assert request["tool_choice"] == {
        "type": "tool",
        "name": "record_findings",
        "disable_parallel_tool_use": True,
    }
    assert request["tools"][0]["input_schema"]["properties"]["findings"]["maxItems"] == 25
    prompt = request["messages"][0]["content"][0]["text"]
    assert "[req 1]" in prompt and "[doc 1]" in prompt and "slide 1" in prompt
    # The reviewer must receive the raw cited page, not only extraction output.
    assert "Section L.1: Provide the technical approach." in prompt


def test_all_applicable_reviewers_run_in_order_with_distinct_grounding(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=True, with_sow=True)
    mapped_requirements = conn.execute(
        """
        SELECT id FROM requirements
        WHERE analysis_id = %s AND source IN ('L', 'SOW')
        """,
        (analysis_id,),
    ).fetchall()
    for (requirement_id,) in mapped_requirements:
        conn.execute(
            """
            INSERT INTO mappings (requirement_id, status, slide_refs, rationale)
            VALUES (%s, 'covered', '[1]'::jsonb, 'Covered on slide 1.')
            """,
            (requirement_id,),
        )
    messages = _fake_client(
        monkeypatch,
        [
            _FakeMessage("tool_use", _observation_input()),
            _FakeMessage(
                "tool_use",
                _observation_input(
                    ref="SOW 2.1",
                    page=3,
                    solicitation_quote="Use a phased rollout.",
                ),
            ),
            _FakeMessage(
                "tool_use",
                _observation_input(
                    ref="M.1",
                    page=2,
                    solicitation_quote="Technical approach is most important.",
                ),
            ),
        ],
    )

    reviewers.run_review(conn, analysis_id)

    assert len(messages.calls) == 3
    prompts = [call["messages"][0]["content"][0]["text"] for call in messages.calls]
    assert "L L.1" in prompts[0] and "SOW SOW 2.1" not in prompts[0]
    assert "SOW SOW 2.1" in prompts[1] and "M M.1" not in prompts[1]
    assert "M M.1" in prompts[2] and "L L.1" not in prompts[2]
    assert "L.1 (L): covered" in prompts[0] and "SOW 2.1 (SOW): covered" not in prompts[0]
    assert "SOW 2.1 (SOW): covered" in prompts[1] and "L.1 (L): covered" not in prompts[1]
    assert "L.1 (L): covered" in prompts[2] and "SOW 2.1 (SOW): covered" in prompts[2]
    assert {row[0] for row in _findings_rows(conn, analysis_id)} == {
        "compliance",
        "technical",
        "evaluator",
    }


def test_evaluator_skipped_when_no_m_records(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    messages = _fake_client(monkeypatch, [_FakeMessage("tool_use", _observation_input())])

    reviewers.run_review(conn, analysis_id)

    assert len(messages.calls) == 1
    assert all(row[0] != "evaluator" for row in _findings_rows(conn, analysis_id))


def test_no_primary_records_skip_client_construction(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    conn.execute("DELETE FROM requirements WHERE analysis_id = %s", (analysis_id,))

    def fail_client_construction():
        raise AssertionError("client must stay lazy")

    monkeypatch.setattr(reviewers, "_get_client", fail_client_construction)

    reviewers.run_review(conn, analysis_id)

    assert _findings_rows(conn, analysis_id) == []


def test_run_review_replaces_previous_findings(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    _fake_client(monkeypatch, [_FakeMessage("tool_use", _observation_input())])
    reviewers.run_review(conn, analysis_id)
    first = _findings_rows(conn, analysis_id)
    assert len(first) == 1

    reviewers.run_review(conn, analysis_id)
    second = _findings_rows(conn, analysis_id)
    assert len(second) == 1


def test_failure_preserves_previous_complete_findings(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=True)
    evaluator_input = _observation_input(
        ref="M.1",
        page=2,
        solicitation_quote="Technical approach is most important.",
    )
    messages = _fake_client(
        monkeypatch,
        [
            _FakeMessage("tool_use", _observation_input()),
            _FakeMessage("tool_use", evaluator_input),
        ],
    )
    reviewers.run_review(conn, analysis_id)
    before = _findings_rows(conn, analysis_id)

    # Both reviewer calls complete, but persistence receives an invalid row.
    messages = _fake_client(
        monkeypatch,
        [
            _FakeMessage("tool_use", _observation_input()),
            _FakeMessage("tool_use", evaluator_input),
        ],
    )

    real_verify_findings = reviewers.verify.verify_findings

    def invalid_verified_finding(findings, ctx):
        verified = real_verify_findings(findings, ctx)
        assert len(verified) == 2
        first = verified[0]
        return [
            reviewers.verify.VerifiedFinding(
                finding=first.finding,
                solicitation_verified=first.solicitation_verified,
                proposal_verified=False,
                evidence_provenance=first.evidence_provenance,
                verification=first.verification,
                evidence=first.evidence,
            )
        ]

    monkeypatch.setattr(reviewers.verify, "verify_findings", invalid_verified_finding)
    with pytest.raises(psycopg.errors.CheckViolation):
        reviewers.run_review(conn, analysis_id)

    assert len(messages.calls) == 2
    assert _findings_rows(conn, analysis_id) == before


@pytest.mark.parametrize("stop_reason", ["end_turn", "refusal", "max_tokens"])
def test_untrusted_stop_reason_fails_stage(conn, monkeypatch, stop_reason):
    analysis_id, _ = _package(conn, with_m=False)
    _fake_client(monkeypatch, [_FakeMessage(stop_reason)])

    with pytest.raises(reviewers.ReviewError):
        reviewers.run_review(conn, analysis_id)

    assert _findings_rows(conn, analysis_id) == []


def test_out_of_range_requirement_handle_fails_stage(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    bad = copy.deepcopy(_observation_input())
    bad["findings"][0]["requirement_handle"] = 99
    _fake_client(monkeypatch, [_FakeMessage("tool_use", bad)])

    with pytest.raises(reviewers.ReviewError):
        reviewers.run_review(conn, analysis_id)

    assert _findings_rows(conn, analysis_id) == []


def test_out_of_range_document_handle_fails_stage(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    bad = copy.deepcopy(_observation_input())
    bad["findings"][0]["solicitation_document_handle"] = 99
    _fake_client(monkeypatch, [_FakeMessage("tool_use", bad)])

    with pytest.raises(reviewers.ReviewError):
        reviewers.run_review(conn, analysis_id)

    assert _findings_rows(conn, analysis_id) == []


def test_too_many_findings_fails_stage(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    one = _observation_input()["findings"][0]
    over = {"findings": [copy.deepcopy(one) for _ in range(26)]}
    _fake_client(monkeypatch, [_FakeMessage("tool_use", over)])

    with pytest.raises(reviewers.ReviewError):
        reviewers.run_review(conn, analysis_id)

    assert _findings_rows(conn, analysis_id) == []


def test_wrong_tool_name_fails_stage(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    _fake_client(monkeypatch, [_FakeMessage("tool_use", _observation_input(), tool_name="wrong")])

    with pytest.raises(reviewers.ReviewError):
        reviewers.run_review(conn, analysis_id)

    assert _findings_rows(conn, analysis_id) == []


def test_multiple_tool_blocks_fail_stage(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    response = _FakeMessage("tool_use", _observation_input())
    response.content.append(
        _FakeToolUseBlock(reviewers.FINDINGS_TOOL["name"], _observation_input())
    )
    _fake_client(monkeypatch, [response])

    with pytest.raises(reviewers.ReviewError):
        reviewers.run_review(conn, analysis_id)

    assert _findings_rows(conn, analysis_id) == []


def test_oversized_input_fails_before_call(conn, monkeypatch):
    analysis_id, _ = _package(conn, with_m=False)
    monkeypatch.setattr(reviewers, "MAX_REVIEW_INPUT_CHARS", 10)
    messages = _fake_client(monkeypatch, [_FakeMessage("tool_use", _observation_input())])

    with pytest.raises(reviewers.ReviewError):
        reviewers.run_review(conn, analysis_id)

    assert messages.calls == []
    assert _findings_rows(conn, analysis_id) == []
