"""Vision pass: enrich `deck` document pages with a Claude-generated
description of what native text extraction misses (org charts, schedule
bars, diagrams, etc).

Entry points:
    run_vision_pass(conn, analysis_id) -- run the vision pass over every
        page belonging to a `deck`-kind document in the given analysis.
        Intended to be called by the pipeline (Task 8 wires this into
        worker.pipeline; not done here).
    vision_pass_page(conn, page) -- run the vision pass for a single page
        and write the result to `pages.vision_summary`.

Only `deck` pages get a vision call -- this is a hard product requirement,
not a routing heuristic: every page belonging to a `deck` document must be
described, and no other document kind's pages are touched by this module.
"""

import base64
from dataclasses import dataclass

import anthropic
import psycopg
from pydantic import BaseModel

from . import blob

MODEL = "claude-opus-4-8"
MAX_TOKENS = 1024

# Stop reasons that mean the parsed output must not be trusted: a refusal
# never produced a real summary, and a max_tokens cutoff may have produced a
# truncated/incomplete one. Both must fail the page rather than silently
# writing bad data to `pages.vision_summary`.
_UNTRUSTED_STOP_REASONS = {"refusal", "max_tokens"}

PROMPT_TEMPLATE = """This image is one page of a slide deck. Below is the \
native text already extracted from this page:

---
{native_text}
---

Write a short, dense description of what this page's IMAGE conveys that the \
native text extraction above misses or under-represents: org charts and \
reporting lines, schedule/timeline bars and their dates, diagrams, flow \
charts, tables laid out visually, icons, and any other structure or meaning \
carried by layout rather than by the text itself. Do not repeat the native \
text verbatim -- focus on what a reader would only get by looking at the \
image."""


class VisionSummary(BaseModel):
    summary: str


class VisionError(Exception):
    """Raised when a page's vision call cannot be trusted (refusal or
    max_tokens stop reason) rather than silently persisting a
    truncated/empty summary."""


@dataclass
class Page:
    """A row from `pages`, trimmed to the columns vision.py needs."""

    id: str
    text: str
    image_blob_url: str


def _get_client() -> anthropic.Anthropic:
    """Constructs the Anthropic client lazily so tests can monkeypatch this
    function instead of needing ANTHROPIC_API_KEY set at import time."""
    return anthropic.Anthropic()


def run_vision_pass(conn: psycopg.Connection, analysis_id: str) -> None:
    """Run the vision pass over every page belonging to a `deck`-kind
    document in `analysis_id`.

    Fetches the relevant `pages` rows (joined to `documents` on
    `document_id`, filtered to `documents.kind = 'deck'`) and calls
    `vision_pass_page` for each one, in `page_no` order. Pages belonging to
    non-`deck` documents are never selected and never receive a vision call.
    """
    rows = conn.execute(
        "SELECT pages.id, pages.text, pages.image_blob_url "
        "FROM pages "
        "JOIN documents ON documents.id = pages.document_id "
        "WHERE documents.analysis_id = %s AND documents.kind = 'deck' "
        "ORDER BY pages.document_id, pages.page_no",
        (analysis_id,),
    ).fetchall()
    for row in rows:
        page = Page(id=str(row[0]), text=row[1], image_blob_url=row[2])
        vision_pass_page(conn, page)


def vision_pass_page(conn: psycopg.Connection, page: Page) -> None:
    """Call Claude with `page`'s image and native text, and write the
    resulting enriched description to `pages.vision_summary`.

    Raises:
        VisionError: if the API response's stop reason is `refusal` or
            `max_tokens` -- in either case no summary is written, since the
            parsed output can't be trusted (empty or truncated).
    """
    image_bytes = blob.download(page.image_blob_url)
    image_b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    client = _get_client()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": PROMPT_TEMPLATE.format(native_text=page.text),
                    },
                ],
            }
        ],
        output_format=VisionSummary,
    )

    if response.stop_reason in _UNTRUSTED_STOP_REASONS:
        raise VisionError(
            f"vision call for page {page.id} stopped with "
            f"stop_reason={response.stop_reason!r}; refusing to store a "
            "possibly empty/truncated summary"
        )

    conn.execute(
        "UPDATE pages SET vision_summary = %s WHERE id = %s",
        (response.parsed_output.summary, page.id),
    )
