"""Script alignment: attach a presenter's narration script to the deck pages
it accompanies.

An analysis may optionally include a `script` document -- a plain-text
narration script keyed to the deck by explicit `Slide N:` markers. This
module parses that text into per-slide prose and writes each slide's prose
to the matching deck page's `pages.script_text` column.

Entry points:
    align_script(conn, analysis_id) -- download and parse the analysis's
        `script` document, then update `pages.script_text` for every
        matching page of the analysis's `deck` document. Intended to be
        called by the pipeline when a script document exists (Task 8 wires
        this into worker.pipeline and decides whether to call it at all --
        not done here; this function assumes it is only called when exactly
        one `script` document exists for the analysis).
    parse_script(text) -- pure parser: splits raw script text on `Slide N:`
        markers, returning `{slide_no: prose}`.

There is no auto-alignment or fuzzy-matching fallback: a script with
missing/malformed markers, or one that references a slide number the deck
doesn't have, is a real product risk (script/deck mismatch) and must fail
loudly via `ScriptAlignmentError` rather than silently dropping or
misattributing narration.
"""

import re

import psycopg

from . import blob

# Matches a `Slide N:` marker at the start of a line, tolerating a little
# surrounding whitespace and either `:` or `.` as the closing punctuation
# (case-insensitive): "Slide 1:", "SLIDE 1 :", "slide 1." all match. Anything
# more exotic (missing punctuation, no space before the number, a marker
# embedded mid-line) is deliberately NOT matched -- this must fail loud on an
# ambiguous/malformed marker rather than guess at one.
_MARKER_RE = re.compile(r"^[ \t]*slide[ \t]+(\d+)[ \t]*[:.][ \t]*", re.IGNORECASE | re.MULTILINE)


class ScriptAlignmentError(Exception):
    """Raised when a script's `Slide N:` markers can't be trusted to align
    with the deck: no markers found, content precedes the first marker, a
    marker number is duplicated, a marker's prose section is empty, or a
    marker references a slide number the deck doesn't have. Auto-alignment
    and fuzzy fallback are explicitly out of scope -- every one of these
    cases must fail loudly rather than silently drop or misattribute
    narration."""


def parse_script(text: str) -> dict[int, str]:
    """Split `text` on `Slide N:` markers into `{slide_no: prose}`.

    Raises:
        ScriptAlignmentError: if there is non-whitespace content before the
            first marker, if zero markers are found, if the same slide
            number is marked more than once, or if any marker's prose
            section (the text between it and the next marker, or end of
            text) is empty once stripped of whitespace.
    """
    matches = list(_MARKER_RE.finditer(text))

    if not matches:
        raise ScriptAlignmentError(
            "script has no `Slide N:` markers -- cannot align narration to "
            "deck pages without explicit slide markers (auto-alignment is "
            "out of scope)"
        )

    preamble = text[: matches[0].start()]
    if preamble.strip():
        snippet = preamble.strip()[:80]
        raise ScriptAlignmentError(
            "script has non-whitespace content before its first `Slide N:` "
            f"marker: {snippet!r} -- every slide's prose must follow a "
            "marker, nothing may precede the first one"
        )

    result: dict[int, str] = {}
    for index, match in enumerate(matches):
        slide_no = int(match.group(1))
        if slide_no in result:
            raise ScriptAlignmentError(
                f"script marker for slide {slide_no} appears more than "
                "once -- duplicate `Slide N:` markers make it ambiguous "
                "which prose belongs to that slide"
            )

        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        prose = text[match.end() : end].strip()
        if not prose:
            raise ScriptAlignmentError(
                f"script marker for slide {slide_no} has no prose after it "
                "(empty slide section) -- every `Slide N:` marker must be "
                "followed by narration text"
            )

        result[slide_no] = prose

    return result


def align_script(conn: psycopg.Connection, analysis_id: str) -> None:
    """Download and parse the `script` document for `analysis_id`, then
    write each slide's prose to the matching page of the `deck` document's
    `pages.script_text`.

    Assumes exactly one `script` document exists for the analysis -- the
    caller (worker.pipeline, Task 8) is responsible for only invoking this
    when a script was actually uploaded.

    Raises:
        ScriptAlignmentError: any of parse_script's failure modes, or if a
            marker references a slide number with no corresponding
            `pages.page_no` on the deck (a script/deck mismatch). Page
            numbers are validated against the deck's pages before any
            `pages` row is written, so a mismatch never leaves a partial
            update behind.
    """
    script_row = conn.execute(
        "SELECT blob_url FROM documents "
        "WHERE analysis_id = %s AND kind = 'script'",
        (analysis_id,),
    ).fetchone()
    script_bytes = blob.download(script_row[0])
    script_text = script_bytes.decode("utf-8")

    slides = parse_script(script_text)

    page_rows = conn.execute(
        "SELECT pages.page_no, pages.id "
        "FROM pages "
        "JOIN documents ON documents.id = pages.document_id "
        "WHERE documents.analysis_id = %s AND documents.kind = 'deck'",
        (analysis_id,),
    ).fetchall()
    page_id_by_no = {page_no: str(page_id) for page_no, page_id in page_rows}

    missing = sorted(slide_no for slide_no in slides if slide_no not in page_id_by_no)
    if missing:
        raise ScriptAlignmentError(
            "script references slide number(s) with no corresponding deck "
            f"page: {missing} -- the deck has pages "
            f"{sorted(page_id_by_no)}, so this looks like a script/deck "
            "mismatch rather than a typo worth guessing at"
        )

    for slide_no, prose in slides.items():
        conn.execute(
            "UPDATE pages SET script_text = %s WHERE id = %s",
            (prose, page_id_by_no[slide_no]),
        )
