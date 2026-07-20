"""Extract and persist solicitation requirements in one Bedrock call."""

from __future__ import annotations

from enum import StrEnum

import psycopg
from anthropic import AnthropicBedrock
from pydantic import BaseModel, ConfigDict, Field, ValidationError


MODEL = "us.anthropic.claude-opus-4-8"
MAX_TOKENS = 16_384
# Keep the complete prompt well below the verified 200k-token context window;
# this character guardrail leaves room for the response and request envelope.
MAX_EXTRACTION_INPUT_CHARS = 400_000

SOLICITATION_KINDS = (
    "solicitation_base",
    "solicitation_amendment",
    "solicitation_q_and_a",
    "solicitation_attachment",
)


class ExtractionError(Exception):
    """Raised when extraction output cannot be trusted or persisted."""


class RequirementSource(StrEnum):
    L = "L"
    M = "M"
    SOW = "SOW"
    limit = "limit"
    FAR = "FAR"
    amendment = "amendment"


class ExtractedRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    source_document: int = Field(ge=1)
    source: RequirementSource
    ref: str
    text: str
    page_no: int = Field(ge=1)
    weight: str | None = None
    supersedes_key: str | None = None


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[ExtractedRequirement]


EXTRACTION_TOOL = {
    "name": "record_extraction",
    "description": (
        "Record every solicitation requirement, factor, limit, clause, "
        "or non-obligation amendment change with its source citation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Stable unique key for this extraction pass.",
                        },
                        "source_document": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "1-based [doc N] handle from the prompt.",
                        },
                        "source": {
                            "type": "string",
                            "enum": ["L", "M", "SOW", "limit", "FAR", "amendment"],
                        },
                        "ref": {"type": "string"},
                        "text": {"type": "string"},
                        "page_no": {"type": "integer", "minimum": 1},
                        "weight": {"type": ["string", "null"]},
                        "supersedes_key": {"type": ["string", "null"]},
                    },
                    "required": [
                        "key",
                        "source_document",
                        "source",
                        "ref",
                        "text",
                        "page_no",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["requirements"],
        "additionalProperties": False,
    },
}


def _get_client() -> AnthropicBedrock:
    """Construct the Bedrock client lazily so callers can replace it in tests."""

    return AnthropicBedrock()


def _load_solicitation_pages(conn: psycopg.Connection, analysis_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT documents.id, documents.kind, documents.display_name,
               pages.page_no, pages.text
        FROM documents
        JOIN pages ON pages.document_id = documents.id
        WHERE documents.analysis_id = %s
          AND documents.kind IN (%s, %s, %s, %s)
        ORDER BY documents.id, pages.page_no
        """,
        (analysis_id, *SOLICITATION_KINDS),
    ).fetchall()

    documents: list[dict] = []
    by_id: dict[str, dict] = {}
    for document_id, kind, display_name, page_no, text in rows:
        document_key = str(document_id)
        document = by_id.get(document_key)
        if document is None:
            document = {
                "id": document_id,
                "kind": kind,
                "display_name": display_name,
                "pages": [],
            }
            by_id[document_key] = document
            documents.append(document)
        document["pages"].append((page_no, text or ""))
    return documents


def _build_prompt(documents: list[dict]) -> str:
    sections = [
        """Extract all distinct solicitation records from the documents below.

For every obligation, use its functional source: L, M, SOW, limit, or FAR,
regardless of which document contains it. An amendment revision to any of
those functional categories remains in that category and should supersede the
earlier record. Use source amendment only for a change note that is not itself
a slide-mappable obligation. Cite source_document with the 1-based [doc N]
handle and page_no exactly as shown. Assign each record a unique key within
this response. Set supersedes_key only when a later record replaces an earlier
record's key.""",
        "Solicitation pages:",
    ]
    for index, document in enumerate(documents, start=1):
        sections.append(
            f"[doc {index}] {document['kind']} — {document['display_name']}"
        )
        for page_no, text in document["pages"]:
            sections.append(f"page {page_no}: {text}")
    return "\n\n".join(sections)


def _validate_result(
    result: ExtractionResult, documents: list[dict]
) -> dict[str, str | None]:
    keys = [requirement.key for requirement in result.requirements]
    if len(keys) != len(set(keys)):
        raise ExtractionError("extraction returned duplicate requirement keys")

    pages_by_document = {
        index: {page_no for page_no, _ in document["pages"]}
        for index, document in enumerate(documents, start=1)
    }
    for requirement in result.requirements:
        if requirement.source_document not in pages_by_document:
            raise ExtractionError(
                f"requirement {requirement.key!r} cites out-of-range "
                f"document handle {requirement.source_document}"
            )
        if requirement.page_no not in pages_by_document[requirement.source_document]:
            raise ExtractionError(
                f"requirement {requirement.key!r} cites missing page "
                f"{requirement.page_no} for document handle "
                f"{requirement.source_document}"
            )
        if (
            requirement.supersedes_key is not None
            and requirement.supersedes_key not in set(keys)
        ):
            raise ExtractionError(
                f"requirement {requirement.key!r} supersedes unknown key "
                f"{requirement.supersedes_key!r}"
            )

    return {
        requirement.key: requirement.supersedes_key
        for requirement in result.requirements
    }


def _read_tool_result(response) -> ExtractionResult:
    if response.stop_reason in {"refusal", "max_tokens"}:
        raise ExtractionError(
            f"extraction call stopped with untrusted stop_reason="
            f"{response.stop_reason!r}"
        )

    tool_blocks = [
        block for block in response.content if getattr(block, "type", None) == "tool_use"
    ]
    if (
        len(tool_blocks) != 1
        or getattr(tool_blocks[0], "name", None) != EXTRACTION_TOOL["name"]
    ):
        raise ExtractionError(
            f"extraction response did not contain exactly one "
            f"{EXTRACTION_TOOL['name']!r} tool use"
        )
    tool_input = getattr(tool_blocks[0], "input", None)
    try:
        return ExtractionResult.model_validate(tool_input)
    except ValidationError as exc:
        raise ExtractionError(f"invalid extraction tool input: {exc}") from exc


def run_extraction(conn: psycopg.Connection, analysis_id: str) -> None:
    """Extract all solicitation requirements for an analysis atomically."""

    documents = _load_solicitation_pages(conn, analysis_id)
    prompt = _build_prompt(documents)
    if len(prompt) > MAX_EXTRACTION_INPUT_CHARS:
        raise ExtractionError(
            "extraction input exceeds the single-pass context guardrail; "
            "document splitting is not supported"
        )

    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": EXTRACTION_TOOL["name"]},
        messages=[
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    )
    result = _read_tool_result(response)
    supersedes_by_key = _validate_result(result, documents)

    document_ids = {
        index: document["id"] for index, document in enumerate(documents, start=1)
    }
    with conn.transaction():
        conn.execute("DELETE FROM requirements WHERE analysis_id = %s", (analysis_id,))
        ids_by_key: dict[str, str] = {}
        for requirement in result.requirements:
            row = conn.execute(
                """
                INSERT INTO requirements
                    (analysis_id, source_document_id, source, ref, text, page_no,
                     weight, supersedes_requirement_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)
                RETURNING id
                """,
                (
                    analysis_id,
                    document_ids[requirement.source_document],
                    requirement.source.value,
                    requirement.ref,
                    requirement.text,
                    requirement.page_no,
                    requirement.weight,
                ),
            ).fetchone()
            ids_by_key[requirement.key] = str(row[0])

        for key, supersedes_key in supersedes_by_key.items():
            if supersedes_key is not None:
                conn.execute(
                    """
                    UPDATE requirements
                    SET supersedes_requirement_id = %s
                    WHERE id = %s
                    """,
                    (ids_by_key[supersedes_key], ids_by_key[key]),
                )
