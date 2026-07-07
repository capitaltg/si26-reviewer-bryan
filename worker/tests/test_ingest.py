from pathlib import Path

import fitz
import pytest
from conftest import insert_analysis

from worker import blob, ingest

FIXTURES = Path(__file__).parent / "fixtures"
PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


class _FakeBlobStore:
    """Stands in for worker.blob: `download` returns pre-seeded bytes for a
    given URL (no network), `upload` records every call (pathname,
    content_type, and the bytes at local_path) and returns a fake BlobResult
    (no subprocess/network)."""

    def __init__(self, monkeypatch, download_bytes: dict[str, bytes]):
        self.download_bytes = download_bytes
        self.uploads: list[dict] = []
        monkeypatch.setattr(ingest.blob, "download", self._download)
        monkeypatch.setattr(ingest.blob, "upload", self._upload)

    def _download(self, url: str) -> bytes:
        return self.download_bytes[url]

    def _upload(self, pathname: str, local_path: str, content_type: str) -> blob.BlobResult:
        data = Path(local_path).read_bytes()
        self.uploads.append(
            {"pathname": pathname, "content_type": content_type, "bytes": data}
        )
        return blob.BlobResult(url=f"https://blob.fake/{pathname}", pathname=pathname)


def _insert_document(
    conn,
    analysis_id,
    *,
    kind="deck",
    content_type="application/pdf",
    blob_pathname="orig/doc.pdf",
    blob_url="https://blob.example/doc.pdf",
    display_name="doc.pdf",
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


def _load_document(conn, document_id: str) -> ingest.Document:
    row = conn.execute(
        "SELECT id, kind, blob_pathname, blob_url, content_type "
        "FROM documents WHERE id = %s",
        (document_id,),
    ).fetchone()
    return ingest.Document(
        id=str(row[0]),
        kind=row[1],
        blob_pathname=row[2],
        blob_url=row[3],
        content_type=row[4],
    )


def _pages(conn, document_id: str):
    return conn.execute(
        "SELECT page_no, text, image_blob_pathname, image_blob_url "
        "FROM pages WHERE document_id = %s ORDER BY page_no",
        (document_id,),
    ).fetchall()


def test_ingest_pdf_document_creates_pages_and_updates_document(conn, monkeypatch):
    analysis_id = insert_analysis(conn)
    document_id = _insert_document(
        conn, analysis_id, blob_url="https://blob.example/ctg_deck.pdf"
    )
    fixture_bytes = (FIXTURES / "ctg_deck.pdf").read_bytes()
    store = _FakeBlobStore(
        monkeypatch, {"https://blob.example/ctg_deck.pdf": fixture_bytes}
    )

    document = _load_document(conn, document_id)
    ingest.ingest_document(conn, analysis_id, document)

    expected_pages = fitz.open(stream=fixture_bytes, filetype="pdf").page_count

    pages = _pages(conn, document_id)
    assert [p[0] for p in pages] == list(range(1, expected_pages + 1))
    for page_no, text, pathname, url in pages:
        assert text.strip() != ""
        assert pathname == f"analyses/{analysis_id}/pages/{document_id}/{page_no}.png"
        assert url == f"https://blob.fake/{pathname}"

    doc_row = conn.execute(
        "SELECT pdf_blob_pathname, pdf_blob_url, page_count FROM documents WHERE id = %s",
        (document_id,),
    ).fetchone()
    # Original was already a PDF -> pdf_blob_* just mirrors the original blob.
    assert doc_row == ("orig/doc.pdf", "https://blob.example/ctg_deck.pdf", expected_pages)

    png_uploads = [u for u in store.uploads if u["pathname"].endswith(".png")]
    assert len(png_uploads) == expected_pages
    for upload in png_uploads:
        assert upload["content_type"] == "image/png"
        assert len(upload["bytes"]) < 4 * 1024 * 1024
    # No PPTX conversion happened, so no PDF should have been uploaded.
    assert not any(u["pathname"].endswith(".pdf") for u in store.uploads)


def test_ingest_pptx_document_converts_and_extracts_per_slide(conn, monkeypatch):
    analysis_id = insert_analysis(conn)
    document_id = _insert_document(
        conn,
        analysis_id,
        content_type=PPTX_CONTENT_TYPE,
        blob_pathname="orig/deck.pptx",
        blob_url="https://blob.example/deck.pptx",
        display_name="deck.pptx",
    )
    fixture_bytes = (FIXTURES / "sample_deck.pptx").read_bytes()
    store = _FakeBlobStore(
        monkeypatch, {"https://blob.example/deck.pptx": fixture_bytes}
    )

    document = _load_document(conn, document_id)
    ingest.ingest_document(conn, analysis_id, document)

    pages = _pages(conn, document_id)
    assert len(pages) == 3
    assert "Ingest Test Deck" in pages[0][1]
    assert "ZEBRA-42" in pages[1][1]
    assert "OKAPI-99" in pages[2][1]

    pdf_uploads = [u for u in store.uploads if u["pathname"].endswith(".pdf")]
    assert len(pdf_uploads) == 1
    expected_pdf_pathname = f"analyses/{analysis_id}/converted/{document_id}.pdf"
    assert pdf_uploads[0]["pathname"] == expected_pdf_pathname

    converted = fitz.open(stream=pdf_uploads[0]["bytes"], filetype="pdf")
    assert converted.page_count == 3
    for page in converted:
        assert page.get_text().strip() != ""

    doc_row = conn.execute(
        "SELECT pdf_blob_pathname, pdf_blob_url, page_count FROM documents WHERE id = %s",
        (document_id,),
    ).fetchone()
    assert doc_row[0] == expected_pdf_pathname
    assert doc_row[1] == f"https://blob.fake/{expected_pdf_pathname}"
    assert doc_row[2] == 3


def test_redline_text_extraction_preserves_requirement_numbering_order(conn, monkeypatch):
    """Amendment 4's tracked-changes redlines must not interleave strikethrough
    and inserted text such that requirement numbering references get garbled."""
    analysis_id = insert_analysis(conn)
    document_id = _insert_document(
        conn,
        analysis_id,
        kind="solicitation_amendment",
        blob_pathname="orig/sa5_rfq.pdf",
        blob_url="https://blob.example/sa5_rfq.pdf",
        display_name="sa5_rfq.pdf",
    )
    fixture_bytes = (FIXTURES / "sa5_rfq.pdf").read_bytes()
    _FakeBlobStore(monkeypatch, {"https://blob.example/sa5_rfq.pdf": fixture_bytes})

    document = _load_document(conn, document_id)
    ingest.ingest_document(conn, analysis_id, document)

    text = conn.execute(
        "SELECT text FROM pages WHERE document_id = %s AND page_no = %s",
        (document_id, 9),
    ).fetchone()[0]
    normalized = text.replace("​", "")

    assert "Section 3.3 above will be used for Factor 3" in normalized
    assert "overall technical factors confidence" in normalized
    assert "rating" in normalized
    idx_section = normalized.find("Section 3.3")
    idx_overall = normalized.find("overall technical factors confidence")
    idx_rating = normalized.find("rating", idx_overall)
    assert idx_section < idx_overall < idx_rating


def test_reading_order_preserves_multi_column_card_adjacency(conn, monkeypatch):
    """The 'Tooling & Access' / 'GATE 3-4' card pair on the deployment-readiness
    slide must extract adjacent to each other, not interleaved with the
    neighboring card's text (multi-column layout regression)."""
    analysis_id = insert_analysis(conn)
    document_id = _insert_document(
        conn,
        analysis_id,
        blob_pathname="orig/ctg_deck.pdf",
        blob_url="https://blob.example/ctg_deck.pdf",
        display_name="ctg_deck.pdf",
    )
    fixture_bytes = (FIXTURES / "ctg_deck.pdf").read_bytes()
    _FakeBlobStore(monkeypatch, {"https://blob.example/ctg_deck.pdf": fixture_bytes})

    document = _load_document(conn, document_id)
    ingest.ingest_document(conn, analysis_id, document)

    text = conn.execute(
        "SELECT text FROM pages WHERE document_id = %s AND page_no = %s",
        (document_id, 6),
    ).fetchone()[0]

    idx_governance = text.find("Data & Governance")
    idx_tooling = text.find("Tooling & Access")
    idx_gate34 = text.find("GATE 3-4")
    idx_ownership = text.find("Ownership & Support")

    assert -1 not in (idx_governance, idx_tooling, idx_gate34, idx_ownership)
    assert idx_governance < idx_tooling < idx_gate34 < idx_ownership

    between = text[idx_tooling : idx_gate34 + len("GATE 3-4")]
    assert "Ownership" not in between
    assert "Data & Governance" not in between


def test_ingest_document_is_idempotent_on_retry(conn, monkeypatch):
    """Simulates jobs.requeue_stuck resetting a stuck analysis back to
    'queued' and the job being retried from scratch: ingest_document must
    not crash on pages_document_id_page_no_unique when re-run for the same
    document."""
    analysis_id = insert_analysis(conn)
    document_id = _insert_document(
        conn, analysis_id, blob_url="https://blob.example/ctg_deck.pdf"
    )
    fixture_bytes = (FIXTURES / "ctg_deck.pdf").read_bytes()
    _FakeBlobStore(monkeypatch, {"https://blob.example/ctg_deck.pdf": fixture_bytes})

    document = _load_document(conn, document_id)
    ingest.ingest_document(conn, analysis_id, document)
    # Retry: must not raise on the pages unique constraint.
    ingest.ingest_document(conn, analysis_id, document)

    expected_pages = fitz.open(stream=fixture_bytes, filetype="pdf").page_count
    count = conn.execute(
        "SELECT count(*) FROM pages WHERE document_id = %s", (document_id,)
    ).fetchone()[0]
    assert count == expected_pages

    doc_row = conn.execute(
        "SELECT page_count FROM documents WHERE id = %s", (document_id,)
    ).fetchone()
    assert doc_row[0] == expected_pages


def test_ingest_analysis_ingests_non_script_documents_and_skips_script(
    conn, monkeypatch
):
    analysis_id = insert_analysis(conn)
    non_script_id = _insert_document(
        conn, analysis_id, blob_url="https://blob.example/ctg_deck.pdf"
    )
    script_id = _insert_document(
        conn,
        analysis_id,
        kind="script",
        content_type="application/pdf",
        blob_pathname="orig/script.pdf",
        blob_url="https://blob.example/script.pdf",
        display_name="script.pdf",
    )
    fixture_bytes = (FIXTURES / "ctg_deck.pdf").read_bytes()
    # Deliberately do NOT seed https://blob.example/script.pdf: if
    # ingest_analysis ever tried to download it, the test would fail with a
    # KeyError instead of silently succeeding, proving the script document
    # was never touched.
    store = _FakeBlobStore(
        monkeypatch, {"https://blob.example/ctg_deck.pdf": fixture_bytes}
    )

    ingest.ingest_analysis(conn, analysis_id)

    expected_pages = fitz.open(stream=fixture_bytes, filetype="pdf").page_count

    non_script_pages = _pages(conn, non_script_id)
    assert len(non_script_pages) == expected_pages

    non_script_doc = conn.execute(
        "SELECT pdf_blob_pathname, pdf_blob_url, page_count FROM documents WHERE id = %s",
        (non_script_id,),
    ).fetchone()
    assert non_script_doc == (
        "orig/doc.pdf",
        "https://blob.example/ctg_deck.pdf",
        expected_pages,
    )

    script_pages = _pages(conn, script_id)
    assert script_pages == []

    script_doc = conn.execute(
        "SELECT pdf_blob_pathname, pdf_blob_url, page_count FROM documents WHERE id = %s",
        (script_id,),
    ).fetchone()
    assert script_doc == (None, None, None)

    assert not any(
        "script" in u["pathname"] for u in store.uploads
    ), "script document should never reach blob.upload"


def test_check_png_size_raises_naming_offending_page(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_PAGE_PNG_BYTES", 10)
    with pytest.raises(RuntimeError) as exc:
        ingest._check_png_size(b"x" * 20, page_no=3)
    assert "3" in str(exc.value)


def test_convert_pptx_to_pdf_raises_with_stderr_on_nonzero_exit(monkeypatch, tmp_path):
    class _FakeResult:
        returncode = 1
        stderr = "soffice exploded: unreadable file"

    def fake_run(cmd, capture_output=None, text=None):
        return _FakeResult()

    monkeypatch.setattr(ingest.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc:
        ingest._convert_pptx_to_pdf(str(tmp_path / "deck.pptx"), str(tmp_path))

    assert "soffice exploded: unreadable file" in str(exc.value)
