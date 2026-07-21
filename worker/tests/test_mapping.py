import pytest
from psycopg.types.json import Json

from conftest import insert_analysis
import worker.mapping as mapping


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
            else [
                _FakeToolUseBlock(
                    tool_name or mapping.MAPPING_TOOL["name"], tool_input
                )
            ]
        )


class _FakeMessagesClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses[len(self.calls) - 1]


def _fake_client(monkeypatch, responses):
    fake_client = type("FakeClient", (), {})()
    fake_client.messages = _FakeMessagesClient(responses)
    monkeypatch.setattr(mapping, "_get_client", lambda: fake_client)
    return fake_client.messages


def _insert_document(conn, analysis_id, *, kind, display_name):
    return str(
        conn.execute(
            """
            INSERT INTO documents
                (analysis_id, kind, display_name, blob_pathname, blob_url, content_type)
            VALUES (%s, %s, %s, %s, %s, 'application/pdf')
            RETURNING id
            """,
            (
                analysis_id,
                kind,
                display_name,
                f"documents/{display_name}",
                f"https://example.test/{display_name}",
            ),
        ).fetchone()[0]
    )


def _insert_page(
    conn,
    document_id,
    page_no,
    *,
    text="native text",
    vision_summary=None,
    script_text=None,
):
    return str(
        conn.execute(
            """
            INSERT INTO pages
                (document_id, page_no, text, image_blob_pathname, image_blob_url,
                 vision_summary, script_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                document_id,
                page_no,
                text,
                f"pages/{document_id}/{page_no}.png",
                f"https://example.test/pages/{document_id}/{page_no}.png",
                vision_summary,
                script_text,
            ),
        ).fetchone()[0]
    )


def _insert_requirement(
    conn,
    analysis_id,
    source_document_id,
    *,
    source,
    ref,
    applies_to="deck",
    obligation_type="content",
    obligation_side="quoter",
    classification_rationale="test classification",
    supersedes_requirement_id=None,
):
    return str(
        conn.execute(
            """
            INSERT INTO requirements
                (analysis_id, source_document_id, source, ref, text, page_no,
                 applies_to, obligation_type, obligation_side,
                 classification_rationale, supersedes_requirement_id)
            VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                analysis_id,
                source_document_id,
                source,
                ref,
                f"Requirement text for {ref}",
                applies_to,
                obligation_type,
                obligation_side,
                classification_rationale,
                supersedes_requirement_id,
            ),
        ).fetchone()[0]
    )


def _deck_package(conn):
    analysis_id = insert_analysis(conn)
    solicitation_id = _insert_document(
        conn, analysis_id, kind="solicitation_base", display_name="rfq.pdf"
    )
    deck_id = _insert_document(
        conn, analysis_id, kind="deck", display_name="deck.pdf"
    )
    _insert_page(conn, solicitation_id, 1, text="Solicitation requirements")
    _insert_page(
        conn,
        deck_id,
        1,
        text="Native slide text",
        vision_summary="Visual diagram summary",
        script_text="Aligned narration",
    )
    _insert_page(conn, deck_id, 2, text="Second native slide")
    return analysis_id, solicitation_id, deck_id


def _mapping_input(requirement_ids, *, slide_refs=None, status="covered"):
    return {
        "mappings": [
            {
                "requirement_id": requirement_id,
                "status": status,
                "slide_refs": list(slide_refs if slide_refs is not None else [1]),
                "rationale": f"Rationale for {requirement_id}",
            }
            for requirement_id in requirement_ids
        ]
    }


def _selected_requirement_ids(conn, analysis_id):
    return [
        str(row[0])
        for row in conn.execute(
            """
            SELECT requirements.id
            FROM requirements
            WHERE requirements.analysis_id = %s
              AND requirements.source IN ('L', 'SOW')
              AND requirements.applies_to = 'deck'
              AND requirements.obligation_type = 'content'
              AND requirements.obligation_side = 'quoter'
              AND NOT EXISTS (
                  SELECT 1
                  FROM requirements successor
                  WHERE successor.supersedes_requirement_id = requirements.id
              )
            ORDER BY requirements.id
            """,
            (analysis_id,),
        ).fetchall()
    ]


def test_maps_only_effective_deck_content_for_the_quoter(conn, monkeypatch):
    analysis_id, solicitation_id, _ = _deck_package(conn)
    included = _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.included"
    )
    _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.other",
        applies_to="other_component",
    )
    _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.constraint",
        obligation_type="constraint",
    )
    _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.government",
        obligation_side="government",
    )
    conn.execute(
        """
        INSERT INTO requirements
            (analysis_id, source_document_id, source, ref, text, page_no)
        VALUES (%s, %s, 'L', 'L.legacy', 'Legacy row.', 1)
        """,
        (analysis_id, solicitation_id),
    )
    _fake_client(
        monkeypatch,
        [_FakeMessage("tool_use", _mapping_input([included]))],
    )

    mapping.run_mapping(conn, analysis_id)

    mapped = conn.execute("SELECT requirement_id FROM mappings").fetchall()
    assert {str(row[0]) for row in mapped} == {included}


@pytest.mark.parametrize("status", ["covered", "partial"])
def test_positive_mapping_requires_a_slide(conn, monkeypatch, status):
    analysis_id, solicitation_id, _ = _deck_package(conn)
    requirement_id = _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.1"
    )
    response = _mapping_input([requirement_id], slide_refs=[], status=status)
    _fake_client(monkeypatch, [_FakeMessage("tool_use", response)])

    with pytest.raises(mapping.MappingError, match="slide reference"):
        mapping.run_mapping(conn, analysis_id)


def test_mapping_normalizes_slide_refs_and_rejects_blank_rationale(
    conn, monkeypatch
):
    analysis_id, solicitation_id, _ = _deck_package(conn)
    requirement_id = _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.1"
    )
    normalized = _mapping_input([requirement_id], slide_refs=[2, 1, 2])
    _fake_client(monkeypatch, [_FakeMessage("tool_use", normalized)])
    mapping.run_mapping(conn, analysis_id)
    assert conn.execute(
        "SELECT slide_refs FROM mappings WHERE requirement_id = %s",
        (requirement_id,),
    ).fetchone()[0] == [1, 2]

    blank = _mapping_input([requirement_id])
    blank["mappings"][0]["rationale"] = "   "
    _fake_client(monkeypatch, [_FakeMessage("tool_use", blank)])
    with pytest.raises(mapping.MappingError, match="rationale"):
        mapping.run_mapping(conn, analysis_id)


def test_persists_only_effective_obligation_mappings_and_full_deck_context(
    conn, monkeypatch
):
    analysis_id, solicitation_id, _ = _deck_package(conn)
    l_id = _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.1"
    )
    sow_id = _insert_requirement(
        conn, analysis_id, solicitation_id, source="SOW", ref="SOW.1"
    )
    for source in ("M", "limit", "FAR"):
        _insert_requirement(
            conn, analysis_id, solicitation_id, source=source, ref=f"{source}.1"
        )
    old_id = _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.old"
    )
    successor_id = _insert_requirement(
        conn,
        analysis_id,
        solicitation_id,
        source="amendment",
        ref="A.1",
        supersedes_requirement_id=old_id,
    )
    selected_ids = _selected_requirement_ids(conn, analysis_id)
    assert set(selected_ids) == {l_id, sow_id}

    messages = _fake_client(
        monkeypatch,
        [_FakeMessage("tool_use", _mapping_input(selected_ids, slide_refs=[1, 2]))],
    )

    mapping.run_mapping(conn, analysis_id)

    rows = conn.execute(
        "SELECT requirement_id, status, slide_refs, rationale FROM mappings "
        "ORDER BY requirement_id"
    ).fetchall()
    assert {str(row[0]) for row in rows} == {l_id, sow_id}
    assert all(row[1] == "covered" for row in rows)
    assert all(row[2] == [1, 2] for row in rows)
    assert all(row[3].startswith("Rationale for ") for row in rows)
    assert len(messages.calls) == 1
    call = messages.calls[0]
    assert call["tool_choice"] == {
        "type": "tool",
        "name": mapping.MAPPING_TOOL["name"],
    }
    prompt = call["messages"][0]["content"][0]["text"]
    assert "Native slide text" in prompt
    assert "Visual diagram summary" in prompt
    assert "Aligned narration" in prompt
    assert all(
        requirement_id in prompt for requirement_id in selected_ids
    )
    assert successor_id not in {str(row[0]) for row in rows}


def test_replaces_existing_mappings_only_for_selected_requirements(conn, monkeypatch):
    analysis_id, solicitation_id, _ = _deck_package(conn)
    selected_id = _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.1"
    )
    excluded_id = _insert_requirement(
        conn, analysis_id, solicitation_id, source="M", ref="M.1"
    )
    conn.execute(
        "INSERT INTO mappings (requirement_id, status, slide_refs, rationale) "
        "VALUES (%s, 'partial', %s, 'old selected'), "
        "(%s, 'covered', %s, 'old excluded')",
        (selected_id, Json([2]), excluded_id, Json([1])),
    )
    _fake_client(
        monkeypatch,
        [_FakeMessage("tool_use", _mapping_input([selected_id], slide_refs=[1]))],
    )

    mapping.run_mapping(conn, analysis_id)

    rows = conn.execute(
        "SELECT requirement_id, status, slide_refs, rationale FROM mappings "
        "ORDER BY requirement_id"
    ).fetchall()
    selected_row = next(row for row in rows if str(row[0]) == selected_id)
    assert selected_row[1:] == ("covered", [1], f"Rationale for {selected_id}")
    excluded_row = next(row for row in rows if str(row[0]) == excluded_id)
    assert excluded_row[1:] == ("covered", [1], "old excluded")


@pytest.mark.parametrize(
    ("tool_input", "tool_name", "stop_reason", "message"),
    [
        (
            lambda ids: _mapping_input([ids[0], ids[0]]),
            None,
            "tool_use",
            "duplicate requirement IDs",
        ),
        (
            lambda ids: _mapping_input([ids[0], "00000000-0000-0000-0000-000000000099"]),
            None,
            "tool_use",
            "requirement IDs",
        ),
        (
            lambda ids: _mapping_input(ids, slide_refs=[99]),
            None,
            "tool_use",
            "slide reference",
        ),
        (
            lambda ids: _mapping_input(ids, slide_refs=[1], status="missing"),
            None,
            "tool_use",
            "missing mapping",
        ),
        (
            lambda ids: None,
            None,
            "refusal",
            "stop_reason",
        ),
        (
            lambda ids: None,
            None,
            "max_tokens",
            "stop_reason",
        ),
        (
            lambda ids: _mapping_input(ids),
            "wrong_tool",
            "tool_use",
            "record_mappings",
        ),
        (
            lambda ids: None,
            None,
            "tool_use",
            "record_mappings",
        ),
    ],
)
def test_rejects_untrusted_or_invalid_mapping_response(
    conn, monkeypatch, tool_input, tool_name, stop_reason, message
):
    analysis_id, solicitation_id, _ = _deck_package(conn)
    selected_id = _insert_requirement(
        conn, analysis_id, solicitation_id, source="L", ref="L.1"
    )
    response = _FakeMessage(
        stop_reason,
        None if tool_input is None else tool_input([selected_id]),
        tool_name,
    )
    _fake_client(monkeypatch, [response])

    with pytest.raises(mapping.MappingError, match=message):
        mapping.run_mapping(conn, analysis_id)

    assert conn.execute("SELECT count(*) FROM mappings").fetchone()[0] == 0


def test_does_not_call_model_when_no_effective_obligations(conn, monkeypatch):
    analysis_id, solicitation_id, _ = _deck_package(conn)
    _insert_requirement(
        conn, analysis_id, solicitation_id, source="M", ref="M.1"
    )
    messages = _fake_client(monkeypatch, [])

    mapping.run_mapping(conn, analysis_id)

    assert messages.calls == []


def test_batches_effective_obligations_in_order_and_covers_each_once(
    conn, monkeypatch
):
    analysis_id, solicitation_id, _ = _deck_package(conn)
    for index in range(201):
        _insert_requirement(
            conn,
            analysis_id,
            solicitation_id,
            source="L",
            ref=f"L.{index:03d}",
        )
    selected_ids = _selected_requirement_ids(conn, analysis_id)
    assert len(selected_ids) == 201
    messages = _fake_client(
        monkeypatch,
        [
            _FakeMessage("tool_use", _mapping_input(selected_ids[:200])),
            _FakeMessage("tool_use", _mapping_input(selected_ids[200:])),
        ],
    )
    monkeypatch.setattr(mapping, "MAX_MAPPING_OUTPUT_REQUIREMENTS", 200)

    mapping.run_mapping(conn, analysis_id)

    mapped_ids = {
        str(row[0])
        for row in conn.execute("SELECT requirement_id FROM mappings").fetchall()
    }
    assert len(messages.calls) == 2
    assert mapped_ids == set(selected_ids)
    assert len(mapped_ids) == 201
    prompts = [call["messages"][0]["content"][0]["text"] for call in messages.calls]
    assert selected_ids[0] in prompts[0]
    assert selected_ids[199] in prompts[0]
    assert selected_ids[200] not in prompts[0]
    assert selected_ids[200] in prompts[1]
    assert selected_ids[0] not in prompts[1]
