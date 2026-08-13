#!/usr/bin/env python3
"""Streamable HTTP MCP server for CI-Lite job history and logs."""

import os
from pathlib import Path

from mcp.server import MCPServer

from mcp_server.store import JobStore


store = JobStore(Path(os.environ.get("CI_LITE_DB", "/data/runs.db")))
mcp = MCPServer(
    "ci-lite",
    instructions=(
        "Inspect CI-Lite jobs. Find job IDs with list_jobs using an owner/repo "
        "and commit SHA, then retrieve stored output with read_job_logs."
    ),
)


@mcp.tool()
def list_jobs(repository: str, commit_sha: str) -> list[dict]:
    """List CI jobs for repository (owner/repo) and commit SHA, newest first."""
    return store.list_jobs(repository, commit_sha)


@mcp.tool()
def read_job_logs(job_id: int, offset: int = 0, limit: int = 20_000) -> dict:
    """Read a chunk of stored logs for a job ID returned by list_jobs."""
    return store.read_job_logs(job_id, offset=offset, limit=limit)


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("CI_LITE_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("CI_LITE_MCP_PORT", "8090")),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
