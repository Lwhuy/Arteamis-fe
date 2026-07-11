from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from surreal_commands import registry

from api.command_service import CommandService
from api.deps import CtxDep, get_identity
from open_notebook.exceptions import NotFoundError

router = APIRouter()

# global (but no longer a job-status oracle): `command` is surreal-commands'
# own job-queue table (job_id/status/result/error_message), not a
# tenant-content table -- no migration ever adds a native `workspace` column
# to it (verified against migrations 1-23), and
# open_notebook/database/scoping.py's GLOBAL_TABLES/NATIVE_WORKSPACE_TABLES
# classification deliberately still does not list it (there is no native
# column for ScopedRepository's generic get/list to filter on). It remains a
# generic background-job runner shared by every feature that submits a
# command (note embedding, source processing, podcast generation, etc.).
#
# P6 rollout jobstatus fix: `command.result` DOES carry per-tenant job
# output for some producers (podcast generation's transcript/outline/
# audio_file_path) -- returning it to ANY authenticated caller who merely
# guessed/observed another workspace's job_id was a cross-tenant leak (the
# last one found in the rollout review). execute_command (submit) and
# get_command_job_status (read) below now require a full workspace context
# (CtxDep) instead of bare identity: submission stamps the caller's
# workspace_id into the command row's `context` field (see
# CommandService.submit_command_job's docstring for why `context` and not
# `args`), and the status read checks it via
# CommandService.get_command_status_for_workspace, 404ing (never 403 -- no
# existence oracle) on any mismatch or missing stamp. list_command_jobs,
# cancel_command_job and debug_registry are unaffected -- they don't return
# job `result` content, so remain identity-only per the original decision.


class CommandExecutionRequest(BaseModel):
    command: str = Field(
        ..., description="Command function name (e.g., 'process_text')"
    )
    app: str = Field(..., description="Application name (e.g., 'open_notebook')")
    input: Dict[str, Any] = Field(..., description="Arguments to pass to the command")


class CommandJobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class CommandJobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None


@router.post("/commands/jobs", response_model=CommandJobResponse)
async def execute_command(request: CommandExecutionRequest, repo: CtxDep):
    """
    Submit a command for background processing.
    Returns immediately with job ID for status tracking.

    Requires an active-workspace token (not just identity) -- the caller's
    workspace_id is stamped onto the job so get_command_job_status can later
    verify ownership on read (P6 rollout jobstatus fix).

    Example request:
    {
        "command": "process_text",
        "app": "open_notebook",
        "input": {
            "text": "Hello world",
            "operation": "uppercase"
        }
    }
    """
    try:
        # Submit command using app name (not module name)
        job_id = await CommandService.submit_command_job(
            module_name=request.app,  # This should be "open_notebook"
            command_name=request.command,
            command_args=request.input,
            workspace_id=repo.workspace_id,
        )

        return CommandJobResponse(
            job_id=job_id,
            status="submitted",
            message=f"Command '{request.command}' submitted successfully",
        )

    except Exception as e:
        logger.error(f"Error submitting command: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to submit command"
        )


@router.get("/commands/jobs/{job_id}", response_model=CommandJobStatusResponse)
async def get_command_job_status(job_id: str, repo: CtxDep):
    """Get the status of a specific command job, scoped to the caller's
    workspace (P6 rollout jobstatus fix -- see module comment above). 404s
    (never 403) if the job belongs to another workspace, doesn't exist, or
    has no stored workspace at all -- no existence oracle."""
    try:
        status_data = await CommandService.get_command_status_for_workspace(
            job_id, repo.workspace_id
        )
        return CommandJobStatusResponse(**status_data)

    except NotFoundError:
        raise HTTPException(status_code=404, detail="Job not found")
    except Exception as e:
        logger.error(f"Error fetching job status: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch job status"
        )


@router.get("/commands/jobs", response_model=List[Dict[str, Any]])
async def list_command_jobs(
    command_filter: Optional[str] = Query(None, description="Filter by command name"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, description="Maximum number of jobs to return"),
    _identity: str = Depends(get_identity),
):
    """List command jobs with optional filtering"""
    try:
        jobs = await CommandService.list_command_jobs(
            command_filter=command_filter, status_filter=status_filter, limit=limit
        )
        return jobs

    except Exception as e:
        logger.error(f"Error listing command jobs: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to list command jobs"
        )


@router.delete("/commands/jobs/{job_id}")
async def cancel_command_job(job_id: str, _identity: str = Depends(get_identity)):
    """Cancel a running command job"""
    try:
        success = await CommandService.cancel_command_job(job_id)
        return {"job_id": job_id, "cancelled": success}

    except Exception as e:
        logger.error(f"Error cancelling command job: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to cancel command job"
        )


@router.get("/commands/registry/debug")
async def debug_registry(_identity: str = Depends(get_identity)):
    """Debug endpoint to see what commands are registered"""
    try:
        # Get all registered commands
        all_items = registry.get_all_commands()

        # Create JSON-serializable data
        command_items = []
        for item in all_items:
            try:
                command_items.append(
                    {
                        "app_id": item.app_id,
                        "name": item.name,
                        "full_id": f"{item.app_id}.{item.name}",
                    }
                )
            except Exception as item_error:
                logger.error(f"Error processing item: {item_error}")

        # Get the basic command structure
        try:
            commands_dict: dict[str, list[str]] = {}
            for item in all_items:
                if item.app_id not in commands_dict:
                    commands_dict[item.app_id] = []
                commands_dict[item.app_id].append(item.name)
        except Exception:
            commands_dict = {}

        return {
            "total_commands": len(all_items),
            "commands_by_app": commands_dict,
            "command_items": command_items,
        }

    except Exception as e:
        logger.error(f"Error debugging registry: {str(e)}")
        return {
            "error": str(e),
            "total_commands": 0,
            "commands_by_app": {},
            "command_items": [],
        }
