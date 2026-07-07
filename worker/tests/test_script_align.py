from pathlib import Path

import pytest
from conftest import insert_analysis

from worker import script_align

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeBlobStore:
    """Stands in for worker.script_align.blob.download: returns pre-seeded
    bytes for a given URL (no network)."""

    def __init__(self, monkeypatch, download_bytes: dict[str, bytes]):
        self.download_bytes = download_bytes
        monkeypatch.setattr(script_align.blob, "download", self._download)

    def _download(self, url: str) -> bytes:
        return self.download_bytes[url]


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


# ---------------------------------------------------------------------------
# parse_script
# ---------------------------------------------------------------------------


def test_parse_script_marked_returns_correct_dict():
    text = (FIXTURES / "script_marked.txt").read_text()
    result = script_align.parse_script(text)

    assert set(result.keys()) == {1, 2, 3}
    assert "Q3 pipeline review" in result[1]
    assert "regional breakdown" in result[2]
    assert "roadmap" in result[3]
    # Marker text itself must not leak into the prose.
    assert "Slide" not in result[1]
    assert "Slide" not in result[2]
    assert "Slide" not in result[3]


def test_parse_script_tolerates_marker_punctuation_and_case_variance():
    text = (
        "SLIDE 1 :\n"
        "First slide prose.\n\n"
        "slide 2.\n"
        "Second slide prose.\n"
    )
    result = script_align.parse_script(text)
    assert result[1].strip() == "First slide prose."
    assert result[2].strip() == "Second slide prose."


def test_parse_script_unmarked_raises_with_actionable_message():
    text = (FIXTURES / "script_unmarked.txt").read_text()

    with pytest.raises(script_align.ScriptAlignmentError) as exc:
        script_align.parse_script(text)

    message = str(exc.value)
    assert "marker" in message.lower()
    assert "Slide" not in message or "no" in message.lower()


def test_parse_script_raises_on_content_before_first_marker():
    text = "Some preamble that isn't part of any slide.\n\nSlide 1:\nProse.\n"

    with pytest.raises(script_align.ScriptAlignmentError) as exc:
        script_align.parse_script(text)

    assert "before" in str(exc.value).lower()


def test_parse_script_raises_on_duplicate_marker():
    text = (
        "Slide 1:\n"
        "First slide prose.\n\n"
        "Slide 2:\n"
        "Second slide prose.\n\n"
        "Slide 2:\n"
        "A second, conflicting take on slide two.\n"
    )

    with pytest.raises(script_align.ScriptAlignmentError) as exc:
        script_align.parse_script(text)

    assert "2" in str(exc.value)
    assert "duplicate" in str(exc.value).lower()


def test_parse_script_raises_on_empty_prose_section_between_markers():
    text = "Slide 1:\nSlide 2:\nSecond slide prose.\n"

    with pytest.raises(script_align.ScriptAlignmentError) as exc:
        script_align.parse_script(text)

    assert "1" in str(exc.value)
    assert "empty" in str(exc.value).lower()


def test_parse_script_raises_on_empty_prose_section_at_end():
    text = "Slide 1:\nFirst slide prose.\n\nSlide 2:\n"

    with pytest.raises(script_align.ScriptAlignmentError) as exc:
        script_align.parse_script(text)

    assert "2" in str(exc.value)
    assert "empty" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# align_script
# ---------------------------------------------------------------------------


def test_align_script_attaches_script_text_to_matching_pages(conn, monkeypatch):
    analysis_id = insert_analysis(conn)
    deck_id = _insert_document(conn, analysis_id, kind="deck")
    page1 = _insert_page(conn, deck_id, 1)
    page2 = _insert_page(conn, deck_id, 2)
    page3 = _insert_page(conn, deck_id, 3)

    script_id = _insert_document(
        conn,
        analysis_id,
        kind="script",
        display_name="script.txt",
        blob_pathname="orig/script.txt",
        blob_url="https://blob.example/script.txt",
        content_type="text/plain",
    )
    script_bytes = (FIXTURES / "script_marked.txt").read_bytes()
    _FakeBlobStore(monkeypatch, {"https://blob.example/script.txt": script_bytes})

    script_align.align_script(conn, analysis_id)

    rows = {
        page_no: text
        for page_no, text in conn.execute(
            "SELECT page_no, script_text FROM pages WHERE document_id = %s "
            "ORDER BY page_no",
            (deck_id,),
        ).fetchall()
    }
    assert "Q3 pipeline review" in rows[1]
    assert "regional breakdown" in rows[2]
    assert "roadmap" in rows[3]

    # Sanity: ids we inserted really are the ones that got updated.
    for page_id in (page1, page2, page3):
        row = conn.execute(
            "SELECT script_text FROM pages WHERE id = %s", (page_id,)
        ).fetchone()
        assert row[0] is not None


def test_align_script_out_of_range_marker_raises(conn, monkeypatch):
    analysis_id = insert_analysis(conn)
    deck_id = _insert_document(conn, analysis_id, kind="deck")
    _insert_page(conn, deck_id, 1)
    _insert_page(conn, deck_id, 2)
    _insert_page(conn, deck_id, 3)

    script_id = _insert_document(
        conn,
        analysis_id,
        kind="script",
        display_name="script.txt",
        blob_pathname="orig/script.txt",
        blob_url="https://blob.example/script.txt",
        content_type="text/plain",
    )
    script_text = "Slide 1:\nFirst.\n\nSlide 99:\nWay out of range.\n"
    _FakeBlobStore(
        monkeypatch, {"https://blob.example/script.txt": script_text.encode("utf-8")}
    )

    with pytest.raises(script_align.ScriptAlignmentError) as exc:
        script_align.align_script(conn, analysis_id)

    assert "99" in str(exc.value)

    # No partial writes: page 1's script_text must not have been left set
    # from before the failure surfaced on slide 99.
    row = conn.execute(
        "SELECT script_text FROM pages WHERE document_id = %s AND page_no = 1",
        (deck_id,),
    ).fetchone()
    assert row[0] is None
