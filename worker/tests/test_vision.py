from pathlib import Path

import pytest
from conftest import insert_analysis

from worker import blob, vision

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeBlobStore:
    """Stands in for worker.blob.download: returns pre-seeded bytes for a
    given URL (no network)."""

    def __init__(self, monkeypatch, download_bytes: dict[str, bytes]):
        self.download_bytes = download_bytes
        monkeypatch.setattr(vision.blob, "download", self._download)

    def _download(self, url: str) -> bytes:
        return self.download_bytes[url]


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, name, input):
        self.name = name
        self.input = input


class _FakeMessage:
    """Mimics an anthropic Message: a `stop_reason` plus a `content` list of
    blocks. `summary` is a convenience for the common case of a single forced
    `record_vision_summary` tool call (None means no tool call, e.g. a
    refusal)."""

    def __init__(self, stop_reason, summary=None):
        self.stop_reason = stop_reason
        self.content = (
            []
            if summary is None
            else [_FakeToolUseBlock(vision.VISION_TOOL["name"], {"summary": summary})]
        )


class _FakeMessagesClient:
    """Records every call to `.create(...)` and returns queued fake
    responses in order (or repeats the single queued response, if only one
    was given)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses[len(self.calls) - 1]


def _insert_document(
    conn,
    analysis_id,
    *,
    kind="deck",
    display_name="deck.pdf",
    blob_pathname="orig/deck.pdf",
    blob_url="https://blob.example/deck.pdf",
    content_type="application/pdf",
) -> str:
    return str(
        conn.execute(
            """
            INSERT INTO documents
                (analysis_id, kind, display_name, blob_pathname, blob_url, content_type)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (analysis_id, kind, display_name, blob_pathname, blob_url, content_type),
        ).fetchone()[0]
    )


def _insert_page(
    conn,
    document_id,
    page_no,
    *,
    text="native text",
    image_blob_pathname=None,
    image_blob_url=None,
) -> str:
    pathname = image_blob_pathname or f"analyses/x/pages/{document_id}/{page_no}.png"
    url = image_blob_url or f"https://blob.example/pages/{document_id}/{page_no}.png"
    return str(
        conn.execute(
            """
            INSERT INTO pages
                (document_id, page_no, text, image_blob_pathname, image_blob_url)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (document_id, page_no, text, pathname, url),
        ).fetchone()[0]
    )


def _fake_client(monkeypatch, responses):
    fake_client = type("FakeClient", (), {})()
    fake_client.messages = _FakeMessagesClient(responses)
    monkeypatch.setattr(vision, "_get_client", lambda: fake_client)
    return fake_client.messages


def test_run_vision_pass_calls_once_per_deck_page_and_skips_non_deck(
    conn, monkeypatch
):
    analysis_id = insert_analysis(conn)
    deck_id = _insert_document(conn, analysis_id, kind="deck")
    other_id = _insert_document(
        conn,
        analysis_id,
        kind="solicitation_base",
        display_name="rfq.pdf",
        blob_pathname="orig/rfq.pdf",
        blob_url="https://blob.example/rfq.pdf",
    )

    deck_page_1 = _insert_page(conn, deck_id, 1, text="Org chart slide")
    deck_page_2 = _insert_page(conn, deck_id, 2, text="Schedule bar slide")
    _insert_page(conn, other_id, 1, text="RFQ page one")

    png_bytes = b"\x89PNG fake bytes"
    store = _FakeBlobStore(
        monkeypatch,
        {
            f"https://blob.example/pages/{deck_id}/1.png": png_bytes,
            f"https://blob.example/pages/{deck_id}/2.png": png_bytes,
        },
    )

    messages_client = _fake_client(
        monkeypatch,
        [_FakeMessage("tool_use", "a summary")],
    )

    vision.run_vision_pass(conn, analysis_id)

    # Hard product requirement: exactly one vision call per deck page, no
    # routing heuristic that might skip some pages.
    assert len(messages_client.calls) == 2

    row1 = conn.execute(
        "SELECT vision_summary FROM pages WHERE id = %s", (deck_page_1,)
    ).fetchone()
    row2 = conn.execute(
        "SELECT vision_summary FROM pages WHERE id = %s", (deck_page_2,)
    ).fetchone()
    assert row1[0] == "a summary"
    assert row2[0] == "a summary"

    # Non-deck page must never get a vision call or a summary written.
    other_row = conn.execute(
        "SELECT vision_summary FROM pages WHERE document_id = %s", (other_id,)
    ).fetchone()
    assert other_row[0] is None
    assert not any(
        f"/{other_id}/" in str(call) for call in messages_client.calls
    )


def test_run_vision_pass_raises_on_refusal_and_does_not_write_summary(
    conn, monkeypatch
):
    analysis_id = insert_analysis(conn)
    deck_id = _insert_document(conn, analysis_id, kind="deck")
    page_id = _insert_page(conn, deck_id, 1, text="Org chart slide")

    _FakeBlobStore(
        monkeypatch,
        {f"https://blob.example/pages/{deck_id}/1.png": b"\x89PNG fake bytes"},
    )
    _fake_client(monkeypatch, [_FakeMessage("refusal")])

    with pytest.raises(vision.VisionError):
        vision.run_vision_pass(conn, analysis_id)

    row = conn.execute(
        "SELECT vision_summary FROM pages WHERE id = %s", (page_id,)
    ).fetchone()
    assert row[0] is None


def test_run_vision_pass_raises_on_max_tokens_and_does_not_write_summary(
    conn, monkeypatch
):
    analysis_id = insert_analysis(conn)
    deck_id = _insert_document(conn, analysis_id, kind="deck")
    page_id = _insert_page(conn, deck_id, 1, text="Schedule bar slide")

    _FakeBlobStore(
        monkeypatch,
        {f"https://blob.example/pages/{deck_id}/1.png": b"\x89PNG fake bytes"},
    )
    _fake_client(
        monkeypatch,
        [_FakeMessage("max_tokens", "truncated")],
    )

    with pytest.raises(vision.VisionError):
        vision.run_vision_pass(conn, analysis_id)

    row = conn.execute(
        "SELECT vision_summary FROM pages WHERE id = %s", (page_id,)
    ).fetchone()
    assert row[0] is None
