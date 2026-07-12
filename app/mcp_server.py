"""The same data as MCP tools, for AI clients (Claude Desktop etc.).

streamable_http_path="/" because the sub-app is mounted at /mcp by api.py —
FastMCP otherwise serves at its own /mcp and the endpoint lands at /mcp/mcp.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .service import get_service

mcp = FastMCP("northpoint-confirmation-outlook", streamable_http_path="/")


@mcp.tool()
def get_headline() -> dict:
    """Weekly confirmation-rate trajectory, totals, and the forecast band."""
    return get_service().headline()


@mcp.tool()
def get_forecast() -> dict:
    """Predictive story: leading signal, risk table, horizon reach, held-out validation."""
    return get_service().forecast()


@mcp.tool()
def get_register(category: str | None = None, plant: str | None = None,
                 supplier: str | None = None, recoverable: bool | None = None,
                 min_prob: float | None = None, limit: int = 25) -> dict:
    """At-risk materials register, filterable, ranked by expected units."""
    return get_service().register(category=category, plant=plant, supplier=supplier,
                                  recoverable=recoverable, min_prob=min_prob,
                                  limit=min(int(limit), 100))


@mcp.tool()
def get_root_cause(week: str | None = None) -> dict:
    """Unconfirmed units by detailed cause for a week (default: latest)."""
    return get_service().root_cause(week)


@mcp.tool()
def get_breakdown(week: str | None = None) -> dict:
    """Unconfirmed units by plant / business field / supplier / category vs prior week."""
    return get_service().breakdown(week)
