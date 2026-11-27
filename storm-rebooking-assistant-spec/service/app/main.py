"""FastAPI app: the brain behind the agent assistant."""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

import anyio
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request

from .config import Settings, get_settings, resolve_as_of
from .models import BatchRequest, SuggestRequest
from .picker import Picker
from .repo import build_repo
from .rules import RuleSet
from .service import RebookingService


def create_app(service: Optional[RebookingService] = None, settings: Optional[Settings] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service is None:
            s = settings or get_settings()
            app.state.service = RebookingService(s, build_repo(s), RuleSet.load(s.rules_path), Picker(s))
        else:
            app.state.service = service
        yield

    app = FastAPI(title="Storm Rebooking Service", version="0.1.0", lifespan=lifespan,
                  description="Suggests a rebooking for every cancelled booking. The agent and the customer decide.")

    def svc(request: Request) -> RebookingService:
        return request.app.state.service

    def require_key(request: Request, x_api_key: Optional[str] = Header(default=None)) -> None:
        expected = request.app.state.service.settings.service_api_key
        if expected and not secrets.compare_digest(x_api_key or "", expected):
            raise HTTPException(status_code=401, detail="missing or wrong X-API-Key")

    auth = [Depends(require_key)]

    @app.get("/health")
    async def health(s: RebookingService = Depends(svc)):
        return {
            "status": "ok",
            "backend": s.repo.name,
            "model_enabled": s.settings.use_model and s.picker.model_available,
            "model": s.settings.openrouter_model or None,
            "rule_set": {"name": s.rules.name, "version": s.rules.version, "requests_accepted_through": s.rules.requests_through.isoformat()},
            "as_of_default": resolve_as_of(None, s.settings).isoformat(),
            "auth_required": bool(s.settings.service_api_key),
        }

    @app.get("/bookings", dependencies=auth)
    async def list_bookings(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), s: RebookingService = Depends(svc)):
        rows = await anyio.to_thread.run_sync(s.repo.list_bookings, limit, offset)
        total = await anyio.to_thread.run_sync(s.repo.count_bookings)
        return {"total": total, "bookings": [r.model_dump(mode="json") for r in rows]}

    async def _booking(s: RebookingService, booking_id: str):
        b = await anyio.to_thread.run_sync(s.repo.get_booking, booking_id)
        if b is None:
            raise HTTPException(status_code=404, detail=f"booking {booking_id} not found")
        return b

    @app.get("/bookings/{booking_id}/candidates", dependencies=auth)
    async def candidates(booking_id: str, as_of: Optional[date] = None, s: RebookingService = Depends(svc)):
        """Deterministic result only: the flights this booking can use. No model call, nothing stored."""
        b = await _booking(s, booking_id)
        return await s.suggest(b, SuggestRequest(as_of=as_of, persist=False, use_model=False), with_pick=False)

    @app.post("/bookings/{booking_id}/suggest", dependencies=auth)
    async def suggest(booking_id: str, req: SuggestRequest, s: RebookingService = Depends(svc)):
        b = await _booking(s, booking_id)
        return await s.suggest(b, req)

    @app.post("/suggest/batch", dependencies=auth)
    async def suggest_batch(req: BatchRequest, s: RebookingService = Depends(svc)):
        return await s.batch(req)

    @app.get("/bookings/{booking_id}/suggestions/latest", dependencies=auth)
    async def latest(booking_id: str, s: RebookingService = Depends(svc)):
        row = await anyio.to_thread.run_sync(s.repo.latest_suggestion, booking_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no stored suggestion for this booking")
        return row

    return app


app = create_app()
