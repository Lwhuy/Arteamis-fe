from typing import Any, Dict, List, Optional

from loguru import logger
from surreal_commands import get_command_status, submit_command

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exceptions import NotFoundError


class CommandService:
    """Generic service layer for command operations"""

    @staticmethod
    async def submit_command_job(
        module_name: str,  # Actually app_name for surreal-commands
        command_name: str,
        command_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[str] = None,
    ) -> str:
        """Submit a generic command job for background processing.

        `workspace_id` (P6 rollout jobstatus fix) is stamped into the
        command's `context` field, NOT `args`. `args` is validated against
        the target command's own Pydantic input schema
        (surreal_commands.core.service.CommandService.submit_command /
        submit_command_sync), which silently *drops* any key that schema
        doesn't declare -- so a generic `workspace_id` stamp in `args` would
        vanish for every command except the few (e.g. podcast generation's
        PodcastGenerationInput) that explicitly declare that field. `context`
        bypasses that validation entirely and is stored verbatim on the
        `command` row, so it's the one place a workspace stamp survives for
        ANY command. get_command_status_for_workspace() below reads it back
        from there to enforce the read-side ownership check that closes the
        cross-tenant job-status leak (see api/routers/commands.py's module
        comment).
        """
        try:
            # Ensure command modules are imported before submitting
            # This is needed because submit_command validates against local registry
            try:
                import commands.podcast_commands  # noqa: F401
            except ImportError as import_err:
                logger.error(f"Failed to import command modules: {import_err}")
                raise ValueError("Command modules not available")

            merged_context = dict(context) if context else {}
            if workspace_id is not None:
                merged_context["workspace_id"] = workspace_id

            # surreal-commands expects: submit_command(app_name, command_name, args, context)
            cmd_id = submit_command(
                module_name,  # This is actually the app name (e.g., "open_notebook")
                command_name,  # Command name (e.g., "process_text")
                command_args,  # Input data
                merged_context or None,
            )
            # Convert RecordID to string if needed
            if not cmd_id:
                raise ValueError("Failed to get cmd_id from submit_command")
            cmd_id_str = str(cmd_id)
            logger.info(
                f"Submitted command job: {cmd_id_str} for {module_name}.{command_name}"
            )
            return cmd_id_str

        except Exception as e:
            logger.error(f"Failed to submit command job: {e}")
            raise

    @staticmethod
    async def get_command_status(job_id: str) -> Dict[str, Any]:
        """Get status of any command job -- UNSCOPED (no workspace check).

        Kept for internal callers that already established ownership another
        way (e.g. open_notebook/podcasts/models.py's PodcastEpisode reads its
        *own* `command` field after the episode itself was fetched through a
        workspace-scoped repo). Do NOT wire this directly to a client-facing
        job-id-driven endpoint -- use get_command_status_for_workspace for
        that (see api/routers/commands.py and api/routers/podcasts.py).
        """
        try:
            status = await get_command_status(job_id)
            return {
                "job_id": job_id,
                "status": status.status if status else "unknown",
                "result": status.result if status else None,
                "error_message": getattr(status, "error_message", None)
                if status
                else None,
                "created": str(status.created)
                if status and hasattr(status, "created") and status.created
                else None,
                "updated": str(status.updated)
                if status and hasattr(status, "updated") and status.updated
                else None,
                "progress": getattr(status, "progress", None) if status else None,
            }
        except Exception as e:
            logger.error(f"Failed to get command status: {e}")
            raise

    @staticmethod
    async def get_command_status_for_workspace(
        job_id: str, workspace_id: str
    ) -> Dict[str, Any]:
        """Workspace-scoped job status read (P6 rollout jobstatus fix).

        `command` (surreal-commands' own job-queue table) carries no native
        `workspace` column -- see the module comment in
        api/routers/commands.py and the classification note in
        open_notebook/database/scoping.py. The submitting workspace is
        instead persisted in the row's `context` field at submission time
        (submit_command_job above). We fetch the raw row ourselves here --
        surreal_commands' own get_command_status() only returns
        status/result/error/timestamps, it does not expose `context` -- and
        raise NotFoundError (-> 404, never 403) on a missing job, a job with
        no stored workspace (e.g. one submitted before this fix, or a
        generic /commands/jobs submission with no active workspace), or a
        workspace mismatch. This is deliberately indistinguishable from
        "job doesn't exist" -- no existence oracle for a cross-workspace id.
        """
        try:
            job_record_id = ensure_record_id(job_id)
        except Exception:
            # Malformed job_id -- fail the same way an unknown-but-well-formed
            # id would (404), not a 500 from the parse error.
            raise NotFoundError("Job not found")

        try:
            rows = await repo_query(
                "SELECT * FROM $job_id", {"job_id": job_record_id}
            )
        except Exception as e:
            logger.error(f"Failed to get command status: {e}")
            raise

        if not rows:
            raise NotFoundError("Job not found")

        row = rows[0]
        stored_workspace = (row.get("context") or {}).get("workspace_id")
        if stored_workspace is None or str(stored_workspace) != str(workspace_id):
            raise NotFoundError("Job not found")

        return {
            "job_id": job_id,
            "status": row.get("status", "unknown"),
            "result": row.get("result"),
            "error_message": row.get("error_message"),
            "created": str(row["created"]) if row.get("created") else None,
            "updated": str(row["updated"]) if row.get("updated") else None,
            "progress": row.get("progress"),
        }

    @staticmethod
    async def list_command_jobs(
        module_filter: Optional[str] = None,
        command_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List command jobs with optional filtering"""
        # This will be implemented with proper SurrealDB queries
        # For now, return empty list as this is foundation phase
        return []

    @staticmethod
    async def cancel_command_job(job_id: str) -> bool:
        """Cancel a running command job"""
        try:
            # Implementation depends on surreal-commands cancellation support
            # For now, just log the attempt
            logger.info(f"Attempting to cancel job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel command job: {e}")
            raise
