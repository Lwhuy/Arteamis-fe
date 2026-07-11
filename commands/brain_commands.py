import time
from typing import List, Literal, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.brain import (
    relate_mention,
    relate_part_of,
    upsert_entity_dedup,
)
from open_notebook.domain.notebook import Source
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
