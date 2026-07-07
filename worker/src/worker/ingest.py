"""Ingest stage: convert decks to PDF, render every page to a PNG, extract
native text, and write `pages` rows.

Entry points:
    ingest_analysis(conn, analysis_id) -- ingest every non-script `documents`
        row belonging to an analysis. Intended to be called by the pipeline
        (Task 8 wires this into worker.pipeline; not done here).
    ingest_document(conn, analysis_id, document) -- ingest a single document.

`script` documents are skipped entirely: script/deck alignment is a later
task (worker.script_align), not this stage's job.
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz
import psycopg

from . import blob

PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

# Vercel Blob's single-part upload cap is 4.5 MB; keep page PNGs comfortably
# under that.
MAX_PAGE_PNG_BYTES = 4 * 1024 * 1024


@dataclass
class Document:
    """A row from `documents`, trimmed to the columns ingest.py needs."""

    id: str
    kind: str
    blob_pathname: str
    blob_url: str
    content_type: str


def ingest_analysis(conn: psycopg.Connection, analysis_id: str) -> None:
    """Ingest every non-`script` document belonging to `analysis_id`.

    Fetches the relevant `documents` rows and calls `ingest_document` for
    each one, in `id` order.
    """
    rows = conn.execute(
        "SELECT id, kind, blob_pathname, blob_url, content_type "
        "FROM documents WHERE analysis_id = %s AND kind != 'script' "
        "ORDER BY id",
        (analysis_id,),
    ).fetchall()
    for row in rows:
        document = Document(
            id=str(row[0]),
            kind=row[1],
            blob_pathname=row[2],
            blob_url=row[3],
            content_type=row[4],
        )
        ingest_document(conn, analysis_id, document)


def ingest_document(
    conn: psycopg.Connection, analysis_id: str, document: Document
) -> None:
    """Ingest one non-`script` document.

    Steps:
      1. Download the original file via `blob.download(document.blob_url)`.
      2. If `document.content_type` is the PPTX MIME type, convert it to PDF
         with LibreOffice (`soffice --headless --convert-to pdf`); otherwise
         the downloaded file is already a PDF.
      3. Open the PDF with PyMuPDF. For every page, render a 150 DPI PNG and
         extract native text.
      4. Upload each page PNG to Blob and insert a `pages` row with the
         native text and the returned pathname/url.
      5. Upload the canonical PDF (the converted one if conversion happened,
         otherwise the original is already canonical) and update
         `documents.pdf_blob_pathname` / `pdf_blob_url` / `page_count`.

    Parameters:
        conn: an open psycopg.Connection (autocommit, per worker.db.connect()).
        analysis_id: id of the parent analysis; used to build Blob paths
            (`analyses/{analysis_id}/...`).
        document: a Document populated from the `documents` row being
            ingested.

    Raises:
        RuntimeError: if the PPTX->PDF conversion subprocess exits non-zero,
            or if a rendered page PNG exceeds MAX_PAGE_PNG_BYTES.

    Idempotent: safe to call again for the same document (e.g. after a
    worker crash + jobs.requeue_stuck requeues the analysis) — any `pages`
    rows from a prior attempt are deleted before this run's rows are
    inserted.
    """
    original_bytes = blob.download(document.blob_url)
    is_pptx = document.content_type == PPTX_CONTENT_TYPE

    # Clear any pages from a prior partial run before re-inserting: the
    # worker's own crash-recovery (jobs.requeue_stuck) can reset a stuck
    # `running` analysis back to `queued`, which re-runs this function from
    # scratch on retry. A plain INSERT would collide with
    # pages_document_id_page_no_unique on the pages a previous attempt
    # already wrote. Delete-then-reinsert (rather than an upsert) also
    # correctly drops stale rows if a retry ever produces a different page
    # count than a prior partial run.
    conn.execute("DELETE FROM pages WHERE document_id = %s", (document.id,))

    with tempfile.TemporaryDirectory() as tmpdir:
        original_path = os.path.join(
            tmpdir, "original.pptx" if is_pptx else "original.pdf"
        )
        with open(original_path, "wb") as f:
            f.write(original_bytes)

        pdf_path = (
            _convert_pptx_to_pdf(original_path, tmpdir) if is_pptx else original_path
        )

        pdf_doc = fitz.open(pdf_path)
        try:
            page_count = len(pdf_doc)
            for index in range(page_count):
                page_no = index + 1
                page = pdf_doc[index]

                pixmap = page.get_pixmap(dpi=150)
                png_bytes = pixmap.tobytes("png")
                _check_png_size(png_bytes, page_no)

                text = page.get_text()

                png_path = os.path.join(tmpdir, f"page-{page_no}.png")
                with open(png_path, "wb") as f:
                    f.write(png_bytes)

                image_result = blob.upload(
                    f"analyses/{analysis_id}/pages/{document.id}/{page_no}.png",
                    png_path,
                    "image/png",
                )

                conn.execute(
                    "INSERT INTO pages "
                    "(document_id, page_no, text, image_blob_pathname, image_blob_url) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        document.id,
                        page_no,
                        text,
                        image_result.pathname,
                        image_result.url,
                    ),
                )
        finally:
            pdf_doc.close()

        if is_pptx:
            pdf_result = blob.upload(
                f"analyses/{analysis_id}/converted/{document.id}.pdf",
                pdf_path,
                "application/pdf",
            )
            pdf_blob_pathname = pdf_result.pathname
            pdf_blob_url = pdf_result.url
        else:
            pdf_blob_pathname = document.blob_pathname
            pdf_blob_url = document.blob_url

        conn.execute(
            "UPDATE documents "
            "SET pdf_blob_pathname = %s, pdf_blob_url = %s, page_count = %s "
            "WHERE id = %s",
            (pdf_blob_pathname, pdf_blob_url, page_count, document.id),
        )


def _convert_pptx_to_pdf(pptx_path: str, outdir: str) -> str:
    """Convert a PPTX file to PDF via headless LibreOffice, returning the
    local path of the resulting PDF.

    Uses `soffice` (not `libreoffice`) as the subprocess command name: on
    Homebrew-installed LibreOffice (local dev, this Mac) only `soffice` is on
    PATH; the Docker image's `apt-get install libreoffice` provides both, and
    `soffice` is the underlying binary either way.
    """
    result = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", outdir, pptx_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"soffice conversion failed for {pptx_path!r} "
            f"(exit {result.returncode}): {result.stderr}"
        )
    stem = Path(pptx_path).stem
    return str(Path(outdir) / f"{stem}.pdf")


def _check_png_size(png_bytes: bytes, page_no: int) -> None:
    """Raise RuntimeError naming the offending page if `png_bytes` exceeds
    MAX_PAGE_PNG_BYTES."""
    if len(png_bytes) > MAX_PAGE_PNG_BYTES:
        raise RuntimeError(
            f"page {page_no} rendered PNG is {len(png_bytes)} bytes, "
            f"exceeding the {MAX_PAGE_PNG_BYTES}-byte per-page cap"
        )
