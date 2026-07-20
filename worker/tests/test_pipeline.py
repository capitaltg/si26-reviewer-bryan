from pathlib import Path

import fitz
import pytest
from conftest import insert_analysis

from worker import blob, ingest, jobs, pipeline, vision

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeBlobStore:
    """Monkeypatches ingest.blob and vision.blob to share one in-memory
    store: `download` returns pre-seeded bytes for a given URL (no network),
    and every `upload` call both records itself and feeds its bytes back
    into the download map (so vision's later `blob.download` of a page PNG
    that ingest just "uploaded" resolves without a real network round-trip).
    """

    def __init__(self, monkeypatch, download_bytes: dict[str, bytes]):
        self.download_bytes = dict(download_bytes)
        self.uploads: list[dict] = []
        monkeypatch.setattr(ingest.blob, "download", self._download)
        monkeypatch.setattr(ingest.blob, "upload", self._upload)
        monkeypatch.setattr(vision.blob, "download", self._download)

    def _download(self, url: str) -> bytes:
        return self.download_bytes[url]

    def _upload(self, pathname: str, local_path: str, content_type: str) -> blob.BlobResult:
        data = Path(local_path).read_bytes()
        self.uploads.append(
            {"pathname": pathname, "content_type": content_type, "bytes": data}
        )
        url = f"https://blob.fake/{pathname}"
        self.download_bytes[url] = data
        return blob.BlobResult(url=url, pathname=pathname)


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, name, input):
        self.name = name
        self.input = input


class _FakeMessage:
    def __init__(self, stop_reason, summary=None):
        self.stop_reason = stop_reason
        self.content = (
            []
            if summary is None
            else [_FakeToolUseBlock(vision.VISION_TOOL["name"], {"summary": summary})]
        )


class _FakeMessagesClient:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _fake_vision_client(monkeypatch, response):
    fake_client = type("FakeClient", (), {})()
    fake_client.messages = _FakeMessagesClient(response)
    monkeypatch.setattr(vision, "_get_client", lambda: fake_client)
    return fake_client.messages


def test_run_pipeline_orders_review_after_mapping(
    conn, monkeypatch
):
    monkeypatch.setattr(pipeline, "STAGE_SLEEP_SECONDS", 0)
    analysis_id = insert_analysis(conn)
    for kind, display_name in (
        ("deck", "deck.pdf"),
        ("solicitation_base", "solicitation.pdf"),
        ("script", "script.txt"),
    ):
        _insert_document(
            conn,
            analysis_id,
            kind=kind,
            content_type="text/plain" if kind == "script" else "application/pdf",
            blob_pathname=f"orig/{display_name}",
            blob_url=f"https://blob.example/{display_name}",
            display_name=display_name,
        )

    events: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        pipeline.ingest,
        "ingest_document",
        lambda conn_, analysis_id_, document: events.append(
            ("ingest_work", document.kind)
        ),
    )
    monkeypatch.setattr(
        pipeline.vision,
        "run_vision_pass",
        lambda conn_, analysis_id_: events.append(("vision_work", None)),
    )
    monkeypatch.setattr(
        pipeline.script_align,
        "align_script",
        lambda conn_, analysis_id_: events.append(("script_align_work", None)),
    )
    monkeypatch.setattr(
        pipeline.extract,
        "run_extraction",
        lambda conn_, analysis_id_: events.append(("extract_work", None)),
    )
    monkeypatch.setattr(
        pipeline.mapping,
        "run_mapping",
        lambda conn_, analysis_id_: events.append(("map_work", None)),
    )
    monkeypatch.setattr(
        pipeline.reviewers,
        "run_review",
        lambda conn_, analysis_id_: events.append(("review_work", None)),
    )
    monkeypatch.setattr(
        pipeline.jobs,
        "update_stage",
        lambda conn_, analysis_id_, stage, detail=None: events.append((stage, detail)),
    )

    pipeline.run_pipeline(conn, analysis_id)

    stage_names = {
        "ingest",
        "vision",
        "script_align",
        "extract",
        "map",
        "review",
        "report",
    }
    stages = [event for event, _ in events if event in stage_names]
    assert list(dict.fromkeys(stages)) == [
        "ingest",
        "vision",
        "script_align",
        "extract",
        "map",
        "review",
        "report",
    ]

    assert [
        (event, detail)
        for event, detail in events
        if event in {"extract", "map", "review"}
    ] == [
        ("extract", "extracting solicitation requirements"),
        ("map", "mapping requirements to proposal content"),
        (
            "review",
            "running compliance / technical / evaluator reviewers",
        ),
    ]

    def assert_updates_precede_work(stage, work):
        update_indices = [
            index for index, (event, _) in enumerate(events) if event == stage
        ]
        work_indices = [
            index for index, (event, _) in enumerate(events) if event == work
        ]
        assert len(update_indices) == len(work_indices)
        assert all(
            update_index < work_index
            for update_index, work_index in zip(update_indices, work_indices)
        )

    assert_updates_precede_work("ingest", "ingest_work")
    assert_updates_precede_work("vision", "vision_work")
    assert_updates_precede_work("script_align", "script_align_work")
    assert_updates_precede_work("extract", "extract_work")
    assert_updates_precede_work("map", "map_work")
    assert_updates_precede_work("review", "review_work")

    work_events = [event for event, _ in events if event.endswith("_work")]
    assert work_events.index("extract_work") < work_events.index("map_work")
    assert work_events.index("map_work") < work_events.index("review_work")
    assert pipeline.STUB_STAGES == [("report", "assembling report (stub)")]


def _insert_document(
    conn,
    analysis_id,
    *,
    kind,
    content_type="application/pdf",
    blob_pathname,
    blob_url,
    display_name,
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


def test_run_pipeline_ingests_and_vision_enriches_only_deck_pages(conn, monkeypatch):
    """End-to-end: real ctg_deck.pdf (deck) + real sa5_rfq.pdf
    (solicitation_base) fixtures through the real ingest + vision stages,
    with blob I/O and the Anthropic vision call faked out."""
    monkeypatch.setattr(pipeline, "STAGE_SLEEP_SECONDS", 0)
    monkeypatch.setattr(
        pipeline.extract, "run_extraction", lambda conn_, analysis_id_: None
    )
    monkeypatch.setattr(
        pipeline.mapping, "run_mapping", lambda conn_, analysis_id_: None
    )
    analysis_id = insert_analysis(conn)

    deck_bytes = (FIXTURES / "ctg_deck.pdf").read_bytes()
    rfq_bytes = (FIXTURES / "sa5_rfq.pdf").read_bytes()

    deck_id = _insert_document(
        conn,
        analysis_id,
        kind="deck",
        blob_pathname="orig/ctg_deck.pdf",
        blob_url="https://blob.example/ctg_deck.pdf",
        display_name="ctg_deck.pdf",
    )
    rfq_id = _insert_document(
        conn,
        analysis_id,
        kind="solicitation_base",
        blob_pathname="orig/sa5_rfq.pdf",
        blob_url="https://blob.example/sa5_rfq.pdf",
        display_name="sa5_rfq.pdf",
    )

    _FakeBlobStore(
        monkeypatch,
        {
            "https://blob.example/ctg_deck.pdf": deck_bytes,
            "https://blob.example/sa5_rfq.pdf": rfq_bytes,
        },
    )
    _fake_vision_client(
        monkeypatch,
        _FakeMessage("tool_use", "a vision summary"),
    )

    pipeline.run_pipeline(conn, analysis_id)

    deck_pages = conn.execute(
        "SELECT text, image_blob_pathname, vision_summary "
        "FROM pages WHERE document_id = %s ORDER BY page_no",
        (deck_id,),
    ).fetchall()
    rfq_pages = conn.execute(
        "SELECT text, image_blob_pathname, vision_summary "
        "FROM pages WHERE document_id = %s ORDER BY page_no",
        (rfq_id,),
    ).fetchall()

    expected_deck_pages = fitz.open(stream=deck_bytes, filetype="pdf").page_count
    expected_rfq_pages = fitz.open(stream=rfq_bytes, filetype="pdf").page_count
    assert len(deck_pages) == expected_deck_pages
    assert len(rfq_pages) == expected_rfq_pages

    for text, image_blob_pathname, vision_summary in deck_pages:
        assert text.strip() != ""
        assert image_blob_pathname is not None
        assert vision_summary == "a vision summary"

    for text, image_blob_pathname, vision_summary in rfq_pages:
        assert text.strip() != ""
        assert image_blob_pathname is not None
        assert vision_summary is None


def test_run_pipeline_skips_script_align_stage_when_no_script_document(
    conn, monkeypatch
):
    """Per the brief: script is optional, and when none was uploaded the
    'script_align' stage must never even be emitted via jobs.update_stage
    (not merely a no-op call)."""
    monkeypatch.setattr(pipeline, "STAGE_SLEEP_SECONDS", 0)
    extract_calls: list[tuple] = []
    mapping_calls: list[tuple] = []
    monkeypatch.setattr(
        pipeline.extract,
        "run_extraction",
        lambda conn_, analysis_id_: extract_calls.append((conn_, analysis_id_)),
    )
    monkeypatch.setattr(
        pipeline.mapping,
        "run_mapping",
        lambda conn_, analysis_id_: mapping_calls.append((conn_, analysis_id_)),
    )
    analysis_id = insert_analysis(conn)

    recorded: list[tuple] = []
    real_update_stage = jobs.update_stage

    def spy_update_stage(conn_, analysis_id_, stage, detail=None):
        recorded.append((analysis_id_, stage, detail))
        return real_update_stage(conn_, analysis_id_, stage, detail)

    monkeypatch.setattr(jobs, "update_stage", spy_update_stage)

    pipeline.run_pipeline(conn, analysis_id)

    stages_seen = [stage for _, stage, _ in recorded]
    assert "script_align" not in stages_seen
    # Sanity check the spy actually observed the real stages, so an empty
    # `recorded` list (e.g. from a broken monkeypatch) can't pass vacuously.
    assert "vision" in stages_seen
    assert "review" not in stages_seen
    assert "report" in stages_seen
    assert extract_calls == []
    assert mapping_calls == []


def test_run_pipeline_ingest_progress_details_use_document_loop_index(
    conn, monkeypatch
):
    """Verifies the exact 'page {i}/{n} — {display_name}' progress string
    and its document-loop (not per-page) semantics, without needing a real
    LibreOffice/PyMuPDF conversion: ingest.ingest_document is stubbed out."""
    monkeypatch.setattr(pipeline, "STAGE_SLEEP_SECONDS", 0)
    monkeypatch.setattr(
        pipeline.extract, "run_extraction", lambda conn_, analysis_id_: None
    )
    monkeypatch.setattr(
        pipeline.mapping, "run_mapping", lambda conn_, analysis_id_: None
    )
    analysis_id = insert_analysis(conn)

    doc_a = _insert_document(
        conn,
        analysis_id,
        kind="deck",
        blob_pathname="orig/a.pdf",
        blob_url="https://blob.example/a.pdf",
        display_name="a.pdf",
    )
    doc_b = _insert_document(
        conn,
        analysis_id,
        kind="solicitation_base",
        blob_pathname="orig/b.pdf",
        blob_url="https://blob.example/b.pdf",
        display_name="b.pdf",
    )
    # documents.id is a random UUID, not an autoincrement -- the pipeline's
    # `ORDER BY id` is deterministic but not insertion order, so compute the
    # expected order the same way the implementation does rather than
    # assuming doc_a comes first.
    display_name_by_id = {doc_a: "a.pdf", doc_b: "b.pdf"}
    expected_order = sorted([doc_a, doc_b])

    ingested_ids: list[str] = []
    monkeypatch.setattr(
        pipeline.ingest,
        "ingest_document",
        lambda conn_, analysis_id_, document: ingested_ids.append(document.id),
    )
    monkeypatch.setattr(pipeline.vision, "run_vision_pass", lambda conn_, analysis_id_: None)

    recorded: list[tuple] = []
    real_update_stage = jobs.update_stage

    def spy_update_stage(conn_, analysis_id_, stage, detail=None):
        recorded.append((analysis_id_, stage, detail))
        return real_update_stage(conn_, analysis_id_, stage, detail)

    monkeypatch.setattr(jobs, "update_stage", spy_update_stage)

    pipeline.run_pipeline(conn, analysis_id)

    ingest_details = [detail for _, stage, detail in recorded if stage == "ingest"]
    expected_details = [
        f"page {i}/2 — {display_name_by_id[doc_id]}"
        for i, doc_id in enumerate(expected_order, start=1)
    ]
    assert ingest_details == expected_details
    assert ingested_ids == expected_order
