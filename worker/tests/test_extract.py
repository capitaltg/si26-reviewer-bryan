import pytest

from conftest import insert_analysis
from worker import extract


BASE_DOCUMENT_ID = "00000000-0000-0000-0000-000000000001"
AMENDMENT_DOCUMENT_ID = "00000000-0000-0000-0000-000000000002"


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, name, input):
        self.name = name
        self.input = input


class _FakeMessage:
    """Mimics the Anthropic message/tool-use objects used by test_vision."""

    def __init__(self, stop_reason, tool_input=None, tool_name=None):
        self.stop_reason = stop_reason
        self.content = (
            []
            if tool_input is None
            else [
                _FakeToolUseBlock(
                    tool_name or extract.EXTRACTION_TOOL["name"], tool_input
                )
            ]
        )


class _FakeMessagesClient:
    """Queues fake responses and records each Bedrock messages.create call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses[len(self.calls) - 1]


def _fake_client(monkeypatch, responses):
    fake_client = type("FakeClient", (), {})()
    fake_client.messages = _FakeMessagesClient(responses)
    monkeypatch.setattr(extract, "_get_client", lambda: fake_client)
    return fake_client.messages


def _insert_document(conn, analysis_id, *, document_id, kind, display_name):
    return str(
        conn.execute(
            """
            INSERT INTO documents
                (id, analysis_id, kind, display_name, blob_pathname, blob_url, content_type)
            VALUES (%s, %s, %s, %s, %s, %s, 'application/pdf')
            RETURNING id
            """,
            (
                document_id,
                analysis_id,
                kind,
                display_name,
                f"documents/{document_id}.pdf",
                f"https://example.test/{document_id}.pdf",
            ),
        ).fetchone()[0]
    )


def _insert_page(conn, document_id, page_no, text):
    conn.execute(
        """
        INSERT INTO pages
            (document_id, page_no, text, image_blob_pathname, image_blob_url)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            document_id,
            page_no,
            text,
            f"analyses/test/pages/{document_id}/{page_no}.png",
            f"https://example.test/pages/{document_id}/{page_no}.png",
        ),
    )


def _package(conn):
    analysis_id = insert_analysis(conn)
    base_id = _insert_document(
        conn,
        analysis_id,
        document_id=BASE_DOCUMENT_ID,
        kind="solicitation_base",
        display_name="base.pdf",
    )
    amendment_id = _insert_document(
        conn,
        analysis_id,
        document_id=AMENDMENT_DOCUMENT_ID,
        kind="solicitation_amendment",
        display_name="amendment.pdf",
    )
    _insert_page(conn, base_id, 1, "Section L.1: provide an approach.")
    _insert_page(conn, amendment_id, 1, "Amendment changes Section L.1.")
    return analysis_id, base_id, amendment_id


def _valid_input():
    return {
        "requirements": [
            {
                "key": "l-1",
                "source_document": 1,
                "source": "L",
                "ref": "L.1",
                "text": "Provide an approach.",
                "page_no": 1,
                "weight": None,
                "supersedes_key": None,
            },
            {
                "key": "l-1-amended",
                "source_document": 2,
                "source": "L",
                "ref": "L.1 revised",
                "text": "Provide the revised approach.",
                "page_no": 1,
                "weight": "high",
                "supersedes_key": "l-1",
            },
        ]
    }


def _requirement_rows(conn, analysis_id):
    return conn.execute(
        """
        SELECT id, source_document_id, source, ref, text, page_no, weight,
               supersedes_requirement_id
        FROM requirements
        WHERE analysis_id = %s
        ORDER BY ref
        """,
        (analysis_id,),
    ).fetchall()


def test_run_extraction_resolves_document_handles_and_supersession(conn, monkeypatch):
    analysis_id, base_id, amendment_id = _package(conn)
    deck_id = _insert_document(
        conn,
        analysis_id,
        document_id="00000000-0000-0000-0000-000000000003",
        kind="deck",
        display_name="deck.pptx",
    )
    _insert_page(conn, deck_id, 1, "Proposal slide text must not enter extraction.")
    messages = _fake_client(monkeypatch, [_FakeMessage("tool_use", _valid_input())])

    extract.run_extraction(conn, analysis_id)

    rows = _requirement_rows(conn, analysis_id)
    assert len(rows) == 2
    base_row, amendment_row = rows
    assert str(base_row[1]) == base_id
    assert str(amendment_row[1]) == amendment_id
    assert amendment_row[7] == base_row[0]
    assert len(messages.calls) == 1
    prompt = messages.calls[0]["messages"][0]["content"][0]["text"]
    assert "[doc 1] solicitation_base — base.pdf" in prompt
    assert "page 1: Section L.1: provide an approach." in prompt
    assert "[doc 2] solicitation_amendment — amendment.pdf" in prompt
    assert "page 1: Amendment changes Section L.1." in prompt
    assert "An amendment revision to any of" in prompt
    assert "deck.pptx" not in prompt
    assert "Proposal slide text" not in prompt
    assert messages.calls[0]["tool_choice"] == {
        "type": "tool",
        "name": extract.EXTRACTION_TOOL["name"],
    }


def test_run_extraction_replaces_previous_rows(conn, monkeypatch):
    analysis_id, _, _ = _package(conn)
    messages = _fake_client(monkeypatch, [_FakeMessage("tool_use", _valid_input())])
    extract.run_extraction(conn, analysis_id)
    first_ids = {str(row[0]) for row in _requirement_rows(conn, analysis_id)}

    changed = {
        "requirements": [
            {
                "key": "sow-1",
                "source_document": 1,
                "source": "SOW",
                "ref": "PWS.1",
                "text": "Perform the service.",
                "page_no": 1,
                "weight": None,
                "supersedes_key": None,
            }
        ]
    }
    messages.responses = [_FakeMessage("tool_use", changed)]
    extract.run_extraction(conn, analysis_id)

    rows = _requirement_rows(conn, analysis_id)
    assert len(rows) == 1
    assert rows[0][2] == "SOW"
    assert str(rows[0][0]) not in first_ids
    assert len(messages.calls) == 2


@pytest.mark.parametrize(
    "input_value",
    [
        {
            **_valid_input(),
            "requirements": [{**_valid_input()["requirements"][0], "page_no": 99}],
        },
        {
            **_valid_input(),
            "requirements": [
                {**_valid_input()["requirements"][0], "source_document": 3}
            ],
        },
        {
            **_valid_input(),
            "requirements": [
                {
                    **_valid_input()["requirements"][0],
                    "supersedes_key": "does-not-exist",
                }
            ],
        },
        {
            **_valid_input(),
            "requirements": [
                _valid_input()["requirements"][0],
                {**_valid_input()["requirements"][1], "key": "l-1"},
            ],
        },
    ],
)
def test_run_extraction_rejects_invalid_records(conn, monkeypatch, input_value):
    analysis_id, _, _ = _package(conn)
    _fake_client(monkeypatch, [_FakeMessage("tool_use", input_value)])

    with pytest.raises(extract.ExtractionError):
        extract.run_extraction(conn, analysis_id)

    assert _requirement_rows(conn, analysis_id) == []


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_run_extraction_rejects_untrusted_stop_reasons(conn, monkeypatch, stop_reason):
    analysis_id, _, _ = _package(conn)
    _fake_client(monkeypatch, [_FakeMessage(stop_reason)])

    with pytest.raises(extract.ExtractionError):
        extract.run_extraction(conn, analysis_id)

    assert _requirement_rows(conn, analysis_id) == []


@pytest.mark.parametrize(
    ("tool_input", "tool_name"),
    [
        (None, None),
        ({"not_requirements": []}, extract.EXTRACTION_TOOL["name"]),
        (_valid_input(), "wrong_tool"),
    ],
)
def test_run_extraction_rejects_missing_or_misnamed_tool_input(
    conn, monkeypatch, tool_input, tool_name
):
    analysis_id, _, _ = _package(conn)
    _fake_client(
        monkeypatch,
        [_FakeMessage("tool_use", tool_input, tool_name=tool_name)],
    )

    with pytest.raises(extract.ExtractionError):
        extract.run_extraction(conn, analysis_id)

    assert _requirement_rows(conn, analysis_id) == []


def test_run_extraction_rejects_oversized_prompt_without_splitting(
    conn, monkeypatch
):
    analysis_id, _, _ = _package(conn)
    monkeypatch.setattr(extract, "MAX_EXTRACTION_INPUT_CHARS", 10)
    messages = _fake_client(monkeypatch, [_FakeMessage("tool_use", _valid_input())])

    with pytest.raises(extract.ExtractionError, match="input"):
        extract.run_extraction(conn, analysis_id)

    assert messages.calls == []
    assert _requirement_rows(conn, analysis_id) == []
