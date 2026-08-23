"""Tradingbot Control Center — read-only dashboard backend.

Hard rules enforced by construction, not by convention:
- No endpoint ever writes to .env, state/*.json, or open_orders/positions.
- No endpoint ever calls Coinbase or restarts any service.
- No endpoint ever calls `autonomous_parameter_governor.run_governor(apply=True)`.
- Every JSON response passes through RedactJSONMiddleware.
See dashboard/backend/security/ for the path and secret guards.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from dashboard.backend.routers import (
    full_proposals,
    health,
    learning,
    learning_intelligence,
    llm_cost,
    logs,
    opportunities,
    orders,
    parameter_proposal_funnel,
    positions,
    prompts,
    proposals,
    reports,
    risk,
    run_summary,
    shadow_outcomes,
    status,
    trace,
)
from dashboard.backend.security.redact_middleware import RedactJSONMiddleware

app = FastAPI(title="Tradingbot Control Center API", docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(RedactJSONMiddleware)

app.include_router(health.router)
app.include_router(status.router)
app.include_router(positions.router)
app.include_router(orders.router)
app.include_router(risk.router)
app.include_router(learning.router)
app.include_router(learning_intelligence.router)
app.include_router(proposals.router)
app.include_router(parameter_proposal_funnel.router)
app.include_router(opportunities.router)
app.include_router(trace.router)
app.include_router(prompts.router)
app.include_router(logs.router)
app.include_router(reports.router)
app.include_router(run_summary.router)
app.include_router(llm_cost.router)
app.include_router(shadow_outcomes.router)
app.include_router(full_proposals.router)


class SPAStaticFiles(StaticFiles):
    """Serve the built SPA, falling back to index.html for client-side routes
    (e.g. /positions) instead of 404ing on unknown paths."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not scope["path"].startswith("/api"):
                return await super().get_response("index.html", scope)
            raise


_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", SPAStaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
