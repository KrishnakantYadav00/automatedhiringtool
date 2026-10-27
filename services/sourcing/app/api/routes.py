"""
AHP Sourcing Engine — REST API Endpoints.

Implements all endpoints for manual connector triggers, candidate listing,
observability metrics, connector health checks, and CEIPAL integrations.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_ceipal_client,
    get_connectors,
    get_db,
    get_pipeline,
    get_settings,
)
from app.config import Settings
from app.connectors.base import BaseConnector
from app.models.candidate import Candidate, CandidateSource, CandidateStatus, IngestionLog, SourceName
from app.models.schemas import (
    CandidateListResponse,
    CandidateResponse,
    CandidateSourceResponse,
    CeipalPushBatchRequest,
    CeipalWebhookPayload,
    ConnectorHealthResponse,
    IngestionLogResponse,
    SourceTriggerRequest,
    SourceTriggerResponse,
    StatsResponse,
    TriggerAllResponse,
)
from app.services.ceipal_client import CeipalClient
from app.services.pipeline import IngestionPipeline

router = APIRouter(prefix="/api/v1/sourcing", tags=["Sourcing Engine"])


@router.post(
    "/trigger/{source_name}",
    response_model=SourceTriggerResponse,
    summary="Trigger Ingestion for Source",
)
async def trigger_source(
    source_name: str,
    pipeline: Annotated[IngestionPipeline, Depends(get_pipeline)],
    connectors: Annotated[dict[str, BaseConnector], Depends(get_connectors)],
    request_body: SourceTriggerRequest | None = None,
) -> SourceTriggerResponse:
    """Manually invoke an ingestion run for a specific connector."""
    clean_source = source_name.lower().strip()
    connector = connectors.get(clean_source)
    if not connector:
        valid_sources = list(connectors.keys())
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_name}' not supported. Valid sources are: {valid_sources}",
        )

    push_to_ceipal = request_body.push_to_ceipal if request_body else True
    result = await pipeline.run(
        source_name=clean_source,
        connector=connector,
        push_to_ceipal=push_to_ceipal,
    )

    return SourceTriggerResponse(
        message=f"Ingestion run completed for {clean_source}.",
        source=clean_source,
        result=result,
    )


@router.post(
    "/trigger/all",
    response_model=TriggerAllResponse,
    summary="Trigger Ingestion for All Sources",
)
async def trigger_all_sources(
    pipeline: Annotated[IngestionPipeline, Depends(get_pipeline)],
    connectors: Annotated[dict[str, BaseConnector], Depends(get_connectors)],
) -> TriggerAllResponse:
    """Run sequential candidate ingestion across all active connectors."""
    results = {}
    for source_name, connector in connectors.items():
        res = await pipeline.run(source_name=source_name, connector=connector)
        results[source_name] = res

    return TriggerAllResponse(
        message="All connectors triggered successfully.",
        results=results,
    )


@router.get(
    "/candidates",
    response_model=CandidateListResponse,
    summary="List Candidates (Paginated)",
)
async def list_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(default=None, description="Search by name, email, or company"),
    source: str | None = Query(default=None, description="Filter by original source"),
    candidate_status: str | None = Query(default=None, alias="status", description="Filter by status"),
) -> CandidateListResponse:
    """Retrieve paginated candidates with optional filtering."""
    base_query = select(Candidate)

    if search:
        search_filter = f"%{search.strip()}%"
        base_query = base_query.where(
            (Candidate.first_name.ilike(search_filter))
            | (Candidate.last_name.ilike(search_filter))
            | (Candidate.email.ilike(search_filter))
            | (Candidate.current_company.ilike(search_filter))
        )

    if source:
        base_query = base_query.where(Candidate.source_first_seen == source.lower().strip())

    if candidate_status:
        try:
            status_enum = CandidateStatus(candidate_status.lower().strip())
            base_query = base_query.where(Candidate.status == status_enum)
        except ValueError:
            pass

    # Count total
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total_res = await db.execute(count_stmt)
    total = total_res.scalar_one() or 0

    # Paginate
    offset = (page - 1) * page_size
    query = base_query.order_by(Candidate.created_at.desc()).offset(offset).limit(page_size)
    items_res = await db.execute(query)
    candidates = items_res.scalars().all()

    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1

    candidate_items = []
    for cand in candidates:
        candidate_items.append(
            CandidateResponse(
                id=cand.id,
                first_name=cand.first_name,
                last_name=cand.last_name,
                email=cand.email,
                phone=cand.phone,
                phone_e164=cand.phone_e164,
                location=cand.location,
                current_company=cand.current_company,
                current_title=cand.current_title,
                experience_years=cand.experience_years,
                skills=cand.skills,
                resume_url=cand.resume_url,
                source_first_seen=cand.source_first_seen,
                status=cand.status.value,
                ceipal_candidate_id=cand.ceipal_candidate_id,
                created_at=cand.created_at,
                updated_at=cand.updated_at,
                sources=[
                    CandidateSourceResponse(
                        id=s.id,
                        source_name=s.source_name.value,
                        source_candidate_id=s.source_candidate_id,
                        fetched_at=s.fetched_at,
                        created_at=s.created_at,
                    )
                    for s in cand.sources
                ],
            )
        )

    return CandidateListResponse(
        items=candidate_items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/candidates/{candidate_id}",
    response_model=CandidateResponse,
    summary="Get Candidate Details",
)
async def get_candidate(
    candidate_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CandidateResponse:
    """Retrieve full candidate details including discovered source platforms."""
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    res = await db.execute(stmt)
    cand = res.scalar_one_or_none()

    if not cand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate with ID '{candidate_id}' not found.",
        )

    return CandidateResponse(
        id=cand.id,
        first_name=cand.first_name,
        last_name=cand.last_name,
        email=cand.email,
        phone=cand.phone,
        phone_e164=cand.phone_e164,
        location=cand.location,
        current_company=cand.current_company,
        current_title=cand.current_title,
        experience_years=cand.experience_years,
        skills=cand.skills,
        resume_url=cand.resume_url,
        source_first_seen=cand.source_first_seen,
        status=cand.status.value,
        ceipal_candidate_id=cand.ceipal_candidate_id,
        created_at=cand.created_at,
        updated_at=cand.updated_at,
        sources=[
            CandidateSourceResponse(
                id=s.id,
                source_name=s.source_name.value,
                source_candidate_id=s.source_candidate_id,
                fetched_at=s.fetched_at,
                created_at=s.created_at,
            )
            for s in cand.sources
        ],
    )


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Sourcing Engine Statistics",
)
async def get_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatsResponse:
    """Get aggregated metrics on candidates, deduplication, and ingestion."""
    # Total candidates
    total_cand = (await db.execute(select(func.count(Candidate.id)))).scalar_one() or 0

    # Counts by status
    status_query = select(Candidate.status, func.count(Candidate.id)).group_by(Candidate.status)
    status_res = await db.execute(status_query)
    by_status = {st.value if hasattr(st, "value") else str(st): count for st, count in status_res.all()}

    # Counts by source
    source_query = select(Candidate.source_first_seen, func.count(Candidate.id)).group_by(Candidate.source_first_seen)
    source_res = await db.execute(source_query)
    by_source = {src or "unknown": count for src, count in source_res.all()}

    # Total duplicates merged
    dup_query = select(func.sum(IngestionLog.candidates_duplicate))
    total_dups = (await db.execute(dup_query)).scalar_one() or 0

    # Total pushed to CEIPAL
    ceipal_count = (
        await db.execute(
            select(func.count(Candidate.id)).where(Candidate.ceipal_candidate_id.isnot(None))
        )
    ).scalar_one() or 0

    # Recent ingestion runs
    recent_logs_stmt = (
        select(IngestionLog)
        .order_by(IngestionLog.started_at.desc())
        .limit(10)
    )
    logs_res = await db.execute(recent_logs_stmt)
    logs = logs_res.scalars().all()

    return StatsResponse(
        total_candidates=total_cand,
        by_source=by_source,
        by_status=by_status,
        total_duplicates_merged=int(total_dups),
        total_pushed_to_ceipal=ceipal_count,
        recent_ingestion_runs=[
            IngestionLogResponse(
                id=log.id,
                source_name=log.source_name.value,
                status=log.status.value,
                candidates_fetched=log.candidates_fetched,
                candidates_new=log.candidates_new,
                candidates_duplicate=log.candidates_duplicate,
                candidates_pushed=log.candidates_pushed,
                error_message=log.error_message,
                started_at=log.started_at,
                completed_at=log.completed_at,
                duration_seconds=log.duration_seconds,
            )
            for log in logs
        ],
    )


@router.get(
    "/health",
    response_model=ConnectorHealthResponse,
    summary="Connectors & Dependencies Health Check",
)
async def health_check(
    db: Annotated[AsyncSession, Depends(get_db)],
    connectors: Annotated[dict[str, BaseConnector], Depends(get_connectors)],
    ceipal: Annotated[CeipalClient, Depends(get_ceipal_client)],
) -> ConnectorHealthResponse:
    """Verify operational health across connectors, database, and CEIPAL."""
    connector_statuses: dict[str, dict[str, Any]] = {}
    for name, conn in connectors.items():
        connector_statuses[name] = await conn.health_check()

    connector_statuses["ceipal"] = await ceipal.health_check()

    # Test Database
    db_status = {"status": "ok"}
    try:
        await db.execute(select(1))
    except Exception as exc:
        db_status = {"status": "error", "detail": str(exc)}

    # Overall status
    overall = "ok"
    if db_status["status"] != "ok":
        overall = "degraded"

    return ConnectorHealthResponse(
        status=overall,
        connectors=connector_statuses,
        database=db_status,
        redis={"status": "not_checked_or_optional"},
    )


@router.post(
    "/ceipal/push",
    summary="Force Push Candidates to CEIPAL",
)
async def push_to_ceipal(
    payload: CeipalPushBatchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    ceipal: Annotated[CeipalClient, Depends(get_ceipal_client)],
) -> dict[str, Any]:
    """Force push candidate records to CEIPAL."""
    stmt = select(Candidate)
    if payload.candidate_ids:
        stmt = stmt.where(Candidate.id.in_(payload.candidate_ids))
    else:
        stmt = stmt.where(Candidate.ceipal_candidate_id.is_(None)).limit(payload.limit)

    res = await db.execute(stmt)
    candidates = res.scalars().all()

    if not candidates:
        return {"pushed": 0, "message": "No candidate records pending push."}

    results = await ceipal.push_batch(candidates)
    await db.commit()

    success_count = sum(1 for r in results if r.success)
    return {
        "pushed": success_count,
        "failed": len(results) - success_count,
        "total_attempted": len(results),
    }


@router.post(
    "/webhook/ceipal",
    summary="CEIPAL Inbound Confirmation Webhook",
)
async def ceipal_webhook(
    payload: CeipalWebhookPayload,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Callback hook invoked by CEIPAL to confirm or update candidate status."""
    try:
        cand_uuid = uuid.UUID(payload.candidate_id)
        stmt = select(Candidate).where(Candidate.id == cand_uuid)
    except ValueError:
        stmt = select(Candidate).where(Candidate.ceipal_candidate_id == payload.ceipal_id)

    res = await db.execute(stmt)
    cand = res.scalar_one_or_none()

    if cand:
        cand.status = CandidateStatus.CONFIRMED
        cand.ceipal_candidate_id = payload.ceipal_id
        await db.commit()
        return {"status": "updated", "candidate_id": str(cand.id)}

    return {"status": "ignored", "reason": "Candidate not found"}
