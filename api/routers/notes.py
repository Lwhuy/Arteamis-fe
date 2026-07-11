from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from api.deps import CtxDep
from api.models import NoteCreate, NoteResponse, NoteUpdate
from open_notebook.database.repository import ensure_record_id
from open_notebook.domain.notebook import Note
from open_notebook.exceptions import InvalidInputError, NotFoundError

router = APIRouter()


async def _get_owned_note(repo: CtxDep, note_id: str) -> dict:
    """`note` has no native `workspace` column (like `source` — see
    `_get_owned_source` in api/routers/projects.py) — it only belongs to a
    workspace transitively via the `artifact` edge to some notebook in that
    workspace. 404 (not 403) hides cross-workspace existence, matching
    ScopedRepository.get()'s no-oracle behavior for natively-scoped tables.
    """
    rows = await repo.raw(
        # scoped-raw: note has no native workspace column; ownership is
        # verified via the artifact edge to a notebook in the caller's workspace
        "SELECT * FROM $nid WHERE id IN "
        "(SELECT VALUE in FROM artifact WHERE out.workspace = $workspace_id)",
        {"nid": ensure_record_id(note_id)},
    )
    if not rows:
        raise NotFoundError(f"note {note_id} not found")
    return rows[0]


def _note_response(row: dict) -> NoteResponse:
    return NoteResponse(
        id=str(row.get("id", "")),
        title=row.get("title"),
        content=row.get("content"),
        note_type=row.get("note_type"),
        created=str(row.get("created", "")),
        updated=str(row.get("updated", "")),
    )


@router.get("/notes", response_model=List[NoteResponse])
async def get_notes(
    repo: CtxDep,
    notebook_id: Optional[str] = Query(None, description="Filter by notebook ID"),
):
    """List notes in the caller's active workspace. If `notebook_id` is given,
    it's workspace-checked first (404 on cross-workspace/missing) and only that
    notebook's notes are returned; otherwise every note reachable via the
    `artifact` edge to a notebook in the caller's workspace is returned. `note`
    is workspace-inherited (no native `workspace` column — see
    open_notebook/database/scoping.py), so both branches go through the
    ScopedRepository raw escape hatch with an explicit parent-join filter."""
    try:
        if notebook_id:
            await repo.get(notebook_id)  # workspace-checked; 404 on miss/cross-workspace
            rows = await repo.raw(
                # scoped-raw: note has no native workspace column; notebook_id is
                # already workspace-verified via repo.get() above, so filtering
                # the artifact edge by that exact id inherits the check
                "SELECT * FROM note WHERE id IN "
                "(SELECT VALUE in FROM artifact WHERE out = $notebook_id) "
                "ORDER BY updated DESC",
                {"notebook_id": ensure_record_id(notebook_id)},
            )
        else:
            rows = await repo.raw(
                # scoped-raw: note has no native workspace column; scoped via the
                # artifact edge to a notebook in the caller's workspace
                "SELECT * FROM note WHERE id IN "
                "(SELECT VALUE in FROM artifact WHERE out.workspace = $workspace_id) "
                "ORDER BY updated DESC",
            )
        return [_note_response(row) for row in rows]
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error fetching notes: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching notes: {str(e)}")


@router.post("/notes", response_model=NoteResponse)
async def create_note(note_data: NoteCreate, repo: CtxDep):
    """Create a new note. `notebook_id` is REQUIRED (422 if missing, enforced
    by `NoteCreate`) and is workspace-checked first (404 on cross-workspace/
    missing) before the note is attached to it — a caller cannot "adopt" a
    note into another workspace's notebook by guessing its id.

    `note` has no native `workspace` column (see
    open_notebook/database/scoping.py's INHERITED_WORKSPACE_TABLES) — it only
    belongs to a workspace transitively via the `artifact` edge to a notebook.
    A note created with no `notebook_id` would therefore have no such edge and
    would be permanently unreachable through any workspace-scoped read,
    including by its own creator (fail-closed, not fail-safe). The frontend
    never creates a note without a notebookId (NoteEditorDialog,
    MessageActions, SaveToNotebooksDialog all guard on it before calling this
    endpoint), so requiring it here closes off a dead-end state rather than
    removing a used capability."""
    try:
        await repo.get(note_data.notebook_id)  # workspace-checked; 404 on miss/cross-workspace

        # Auto-generate title if not provided and it's an AI note
        title = note_data.title
        if not title and note_data.note_type == "ai" and note_data.content:
            from open_notebook.graphs.prompt import graph as prompt_graph

            prompt = "Based on the Note below, please provide a Title for this content, with max 15 words"
            result = await prompt_graph.ainvoke(
                {  # type: ignore[arg-type]
                    "input_text": note_data.content,
                    "prompt": prompt,
                }
            )
            title = result.get("output", "Untitled Note")

        # Validate note_type
        note_type: Optional[Literal["human", "ai"]] = None
        if note_data.note_type in ("human", "ai"):
            note_type = note_data.note_type  # type: ignore[assignment]
        elif note_data.note_type is not None:
            raise HTTPException(
                status_code=400, detail="note_type must be 'human' or 'ai'"
            )

        new_note = Note(
            title=title,
            content=note_data.content,
            note_type=note_type,
        )
        command_id = await new_note.save()

        # notebook_id is required and already workspace-verified above
        await new_note.add_to_notebook(note_data.notebook_id)

        return NoteResponse(
            id=new_note.id or "",
            title=new_note.title,
            content=new_note.content,
            note_type=new_note.note_type,
            created=str(new_note.created),
            updated=str(new_note.updated),
            command_id=str(command_id) if command_id else None,
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating note: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating note: {str(e)}")


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note(note_id: str, repo: CtxDep):
    """Get a specific note by ID. 404 if not in the caller's workspace (no
    cross-workspace oracle)."""
    try:
        row = await _get_owned_note(repo, note_id)
        return _note_response(row)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except Exception as e:
        logger.error(f"Error fetching note {note_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching note: {str(e)}")


@router.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: str, note_update: NoteUpdate, repo: CtxDep):
    """Update a note. 404 on cross-workspace id (ownership-checked first)."""
    try:
        await _get_owned_note(repo, note_id)  # ownership-checked → 404 on cross-workspace
        note = await Note.get(note_id)

        # Update only provided fields
        if note_update.title is not None:
            note.title = note_update.title
        if note_update.content is not None:
            note.content = note_update.content
        if note_update.note_type is not None:
            if note_update.note_type in ("human", "ai"):
                note.note_type = note_update.note_type  # type: ignore[assignment]
            else:
                raise HTTPException(
                    status_code=400, detail="note_type must be 'human' or 'ai'"
                )

        command_id = await note.save()

        return NoteResponse(
            id=note.id or "",
            title=note.title,
            content=note.content,
            note_type=note.note_type,
            created=str(note.created),
            updated=str(note.updated),
            command_id=str(command_id) if command_id else None,
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating note {note_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating note: {str(e)}")


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, repo: CtxDep):
    """Delete a note. 404 on cross-workspace id (ownership-checked first)."""
    try:
        await _get_owned_note(repo, note_id)  # ownership-checked → 404 on cross-workspace
        note = await Note.get(note_id)
        await note.delete()

        return {"message": "Note deleted successfully"}
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except Exception as e:
        logger.error(f"Error deleting note {note_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting note: {str(e)}")
