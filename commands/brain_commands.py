import time
from typing import List, Literal, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.brain import (
    relate_mention,
    relate_part_of,
    relate_sources,
    upsert_entity_dedup,
)
from open_notebook.domain.notebook import Source, vector_search
from open_notebook.exceptions import ConfigurationError, OpenNotebookError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


class ExtractSourceEntitiesInput(CommandInput):
    source_id: str
    workspace_id: str


class ExtractSourceEntitiesOutput(CommandOutput):
    success: bool
    source_id: str
    entities_created: int = 0
    processing_time: float = 0.0
    error_message: Optional[str] = None


class ExtractedEntity(BaseModel):
    kind: Literal["domain", "topic", "person", "decision"]
    name: str
    description: Optional[str] = None


class EntityExtraction(BaseModel):
    domain_path: str = Field(
        default="",
        description="Dot-delimited domain path from broad to narrow, e.g. 'engineering.ai'.",
    )
    entities: List[ExtractedEntity] = Field(default_factory=list)


async def _run_extraction_llm(title: str, content: str) -> EntityExtraction:
    """Provision a model, render the prompt, and parse the structured result."""
    try:
        parser = PydanticOutputParser(pydantic_object=EntityExtraction)
        prompt = Prompter(
            prompt_template="brain/extract_entities",
            parser=parser,  # type: ignore[arg-type]
        ).render(data={"source_title": title or "", "source_content": content})
        model = await provision_langchain_model(
            prompt, None, "tools", max_tokens=2000, structured=dict(type="json")
        )
        ai_message = await model.ainvoke(prompt)
        cleaned = clean_thinking_content(extract_text_content(ai_message.content))
        return parser.parse(cleaned)
    except OpenNotebookError:
        raise
    except Exception as e:
        exc_class, message = classify_error(e)
        raise exc_class(message) from e


@command(
    "extract_source_entities",
    app="open_notebook",
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 1,
        "wait_max": 60,
        "stop_on": [ValueError, ConfigurationError],
        "retry_log_level": "debug",
    },
)
async def extract_source_entities_command(
    input_data: ExtractSourceEntitiesInput,
) -> ExtractSourceEntitiesOutput:
    """
    Extract entities from a source, upsert with dedup, and build the graph.

    After extraction: upsert each entity (workspace-scoped dedup), RELATE
    source->mentions->entity, and build the part_of topic->domain hierarchy.
    Raises ValueError for permanent failures (missing source / empty text);
    ConfigurationError (missing model) also stops retries. Any other error
    retries. Callers never let this block ingest.
    """
    start_time = time.time()
    source_id = input_data.source_id
    workspace_id = input_data.workspace_id

    try:
        source = await Source.get(source_id)
        if not source:
            raise ValueError(f"Source '{source_id}' not found")
        if not source.full_text or not source.full_text.strip():
            raise ValueError(f"Source '{source_id}' has no text to extract")

        extraction = await _run_extraction_llm(source.title or "", source.full_text)

        # Domain root from the first path segment (if any).
        domain_id: Optional[str] = None
        domain_name = (
            extraction.domain_path.split(".")[0].strip()
            if extraction.domain_path
            else ""
        )
        if domain_name:
            domain_entity = await upsert_entity_dedup(
                workspace=workspace_id, kind="domain", name=domain_name
            )
            assert domain_entity.id is not None
            domain_id = domain_entity.id

        entities_created = 0
        for extracted in extraction.entities:
            entity = await upsert_entity_dedup(
                workspace=workspace_id,
                kind=extracted.kind,
                name=extracted.name,
                description=extracted.description,
            )
            assert entity.id is not None
            await relate_mention(
                source_id=source_id,
                entity_id=entity.id,
                workspace=workspace_id,
                confidence=1.0,
            )
            if extracted.kind == "topic" and domain_id is not None:
                await relate_part_of(
                    topic_id=entity.id,
                    domain_id=domain_id,
                    workspace=workspace_id,
                )
            entities_created += 1

        processing_time = time.time() - start_time
        logger.info(
            f"Extracted {entities_created} entities from {source_id} "
            f"(workspace={workspace_id}) in {processing_time:.2f}s"
        )
        return ExtractSourceEntitiesOutput(
            success=True,
            source_id=source_id,
            entities_created=entities_created,
            processing_time=processing_time,
        )
    except ValueError as e:
        # Validation errors are permanent failures - don't retry (stop_on
        # already prevents pointless retries). Log per-source so extraction
        # failures are visible without blocking ingest, then re-raise so
        # surreal-commands marks the job as `failed`.
        logger.error(f"Entity extraction failed for source {source_id} (permanent): {e}")
        raise
    except Exception as e:
        # Transient failure - will be retried (surreal-commands logs final failure)
        logger.debug(
            f"Transient error extracting entities for source {source_id}: {e}"
        )
        raise


class ClassifyRelationshipsInput(CommandInput):
    """Input for classifying a source against its top-K similar peers."""

    source_id: str
    workspace_id: str
    top_k: int = 5


class ClassifyRelationshipsOutput(CommandOutput):
    """Output from the classify_relationships command."""

    success: bool
    source_id: str
    edges_created: int = 0
    processing_time: float
    error_message: Optional[str] = None


class RelationshipClassification(BaseModel):
    """LLM-parsed classification of one source pair."""

    type: Literal["supersedes", "disagrees", "complements", "agrees", "none"]
    confidence: float
    rationale: str


async def _workspace_source_ids(workspace_id: str) -> set:
    """All source ids that belong to `workspace_id`.

    A `source` row has no `workspace` field of its own (see commit 36a5775 /
    api/source_permissions.py) -- its workspace is derived via the
    `reference` edge to its notebook/project. `vector_search` is NOT
    workspace-scoped by itself, so its candidates MUST be filtered against
    this set before they can be classified or related: `relates` edges must
    never cross workspaces.
    """
    rows = await repo_query(
        "SELECT VALUE in FROM reference WHERE out.workspace = $workspace",
        {"workspace": ensure_record_id(workspace_id)},
    )
    return {str(rid) for rid in (rows or []) if rid is not None}


@command(
    "classify_relationships",
    app="open_notebook",
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 1,
        "wait_max": 60,
        "stop_on": [ValueError, ConfigurationError],
        "retry_log_level": "debug",
    },
)
async def classify_relationships_command(
    input_data: ClassifyRelationshipsInput,
) -> ClassifyRelationshipsOutput:
    """Classify semantic relationships between a source and its top-K peers.

    Uses vector_search to fetch similarity candidates, restricts them to the
    caller's own workspace (vector_search is NOT workspace-scoped, and a
    `relates` edge must never cross workspaces), then asks the LLM to
    classify each same-workspace pair. Non-'none' results are written as
    `relates` edges via relate_sources (which dedups + orients). Linear in
    source count (top-K per source), not O(n^2).

    A failure classifying one candidate is logged and skipped so it doesn't
    block the rest of the top-K peers or crash the whole command; only a
    failure resolving the source itself (missing/empty text) is a permanent,
    whole-command failure (ValueError, no retry).
    """
    start_time = time.time()
    source_id = input_data.source_id
    workspace_id = input_data.workspace_id

    try:
        source = await Source.get(source_id)
        if not source or not source.full_text or not source.full_text.strip():
            raise ValueError(f"Source '{source_id}' has no text to classify")

        candidates = await vector_search(
            keyword=source.full_text,
            results=input_data.top_k + 5,  # buffer for self + dupes + cross-workspace
            source=True,
            note=False,
        )

        # Tenant isolation guardrail: restrict candidates to the caller's own
        # workspace BEFORE any classification/relate work touches them.
        allowed_ids = await _workspace_source_ids(workspace_id)

        seen: set = set()
        top_candidates: List[str] = []
        for cand in candidates or []:
            cand_id = str(cand.get("parent_id") or cand.get("id") or "")
            if not cand_id or cand_id == source_id or cand_id in seen:
                continue
            seen.add(cand_id)
            if cand_id not in allowed_ids:
                continue  # never classify/relate across workspaces
            top_candidates.append(cand_id)
            if len(top_candidates) >= input_data.top_k:
                break

        parser = PydanticOutputParser(pydantic_object=RelationshipClassification)
        edges_created = 0

        for cand_id in top_candidates:
            try:
                other = await Source.get(cand_id)
                if not other or not other.full_text:
                    continue

                prompt = Prompter(
                    prompt_template="brain/classify_relationship",
                    parser=parser,  # type: ignore[arg-type]
                ).render(
                    data={
                        "source_a_title": source.title or "",
                        "source_a_text": source.full_text,
                        "source_b_title": other.title or "",
                        "source_b_text": other.full_text,
                    }
                )
                model = await provision_langchain_model(
                    prompt,
                    None,
                    "tools",
                    max_tokens=1000,
                    structured=dict(type="json"),
                )
                ai_message = await model.ainvoke(prompt)
                content = clean_thinking_content(
                    extract_text_content(ai_message.content)
                )
                classification = parser.parse(content)

                if classification.type == "none":
                    continue

                await relate_sources(
                    source_id,
                    cand_id,
                    classification.type,
                    classification.confidence,
                    classification.rationale,
                    workspace_id,
                )
                edges_created += 1
            except Exception as e:
                # Per-candidate failure (LLM error, parse failure, etc.) must
                # not sink classification of the remaining top-K peers.
                logger.error(
                    f"Failed to classify relationship {source_id} -> "
                    f"{cand_id}: {e}"
                )
                continue

        processing_time = time.time() - start_time
        logger.info(
            f"Classified relationships for {source_id}: {edges_created} edges "
            f"created in {processing_time:.2f}s"
        )
        return ClassifyRelationshipsOutput(
            success=True,
            source_id=source_id,
            edges_created=edges_created,
            processing_time=processing_time,
        )

    except ValueError as e:
        # Permanent failure - don't retry (stop_on already prevents pointless
        # retries). Log per-source so it's visible without blocking ingest.
        logger.error(
            f"classify_relationships failed for source {source_id} (permanent): {e}"
        )
        raise
    except Exception as e:
        # Transient failure - will be retried (surreal-commands logs final failure)
        logger.debug(
            f"Transient error classifying relationships for source {source_id}: {e}"
        )
        raise
