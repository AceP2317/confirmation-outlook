"""One process, one URL: REST + MCP + the React front.

Mount order matters: /api routes and /mcp first, static front last so it
never shadows them. The MCP session manager must run inside THIS lifespan —
Starlette does not run a mounted sub-app's lifespan.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .mcp_server import mcp
from .ratelimit import AskLimiter, client_ip
from .service import get_service

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
limiter = AskLimiter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_service()  # loads baked tables; sub-second
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Northpoint Confirmation Outlook", lifespan=lifespan)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=300)


@app.get("/api")
def index():
    return {
        "name": "Northpoint Confirmation Outlook (synthetic demo)",
        "endpoints": ["/api/health", "/api/headline", "/api/forecast", "/api/register",
                      "/api/worklist", "/api/root_cause", "/api/breakdown",
                      "POST /api/ask", "/mcp/ (MCP)", "/docs"],
    }


@app.get("/api/health")
def health():
    return get_service().health()


@app.get("/api/headline")
def headline():
    return get_service().headline()


@app.get("/api/forecast")
def forecast():
    return get_service().forecast()


@app.get("/api/register")
def register(category: str | None = None, plant: str | None = None,
             supplier: str | None = None, recoverable: bool | None = None,
             confidence: str | None = None, min_prob: float | None = None,
             limit: int = 400):
    return get_service().register(category=category, plant=plant, supplier=supplier,
                                  recoverable=recoverable, confidence=confidence,
                                  min_prob=min_prob, limit=limit)


@app.get("/api/worklist")
def worklist(n: int = 60):
    return get_service().worklist(n)


@app.get("/api/root_cause")
def root_cause(week: str | None = None):
    return get_service().root_cause(week)


@app.get("/api/breakdown")
def breakdown(week: str | None = None):
    return get_service().breakdown(week)


@app.post("/api/ask")
def ask(body: AskBody, request: Request):
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "Ask is offline: no API key configured on this deployment. "
                                 "Everything else on the demo works without one.")
    ip = client_ip(request)
    ok, scope, retry = limiter.check(ip)
    if not ok:
        return JSONResponse(status_code=429, content={
            "error": "Ask is rate-limited on this public demo.",
            "scope": scope, "retryAfter": retry,
        })
    from .agent import ask as run_ask
    try:
        out = run_ask(body.question)
    except Exception:
        # the slot stays consumed — reserved at check(), so failures aren't free
        raise HTTPException(502, "The language model call failed - try again shortly.")
    limiter.settle(out["usage"]["inputTokens"], out["usage"]["outputTokens"])
    return {"answer": out["answer"], "toolsUsed": out["toolsUsed"]}


@app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
def mcp_slash_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/mcp/", status_code=307)


app.mount("/mcp", mcp.streamable_http_app())

if WEB_DIST.exists():  # guarded: absent during API-only dev
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
