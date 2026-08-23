from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from dashboard.backend.services.reports import get_report, list_reports

router = APIRouter()


@router.get("/api/reports")
def reports(category: str | None = Query(default=None, max_length=100)) -> dict:
    return {"reports": list_reports(category)}


@router.get("/api/reports/{report_id:path}")
def report_detail(report_id: str) -> dict:
    try:
        return get_report(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
