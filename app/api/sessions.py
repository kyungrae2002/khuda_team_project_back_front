from dataclasses import asdict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.slot import Slot, SlotField
from app.models.travel_session import TravelSession
from app.schemas.api import (
    ItineraryRequest,
    ItineraryResponse,
    SlotFillRequest,
    SlotSummaryOut,
    UploadResponse,
)
from app.services.itinerary_builder import ItineraryFixError
from app.services.narrator import NarrationError
from app.services.ingestion import ingest_conversation
from app.services.place_selector import PlaceSelectionError
from app.services.pipeline import PipelineError, generate_itinerary
from app.services.places_client import PlacesAPIError
from app.services.query_builder import QueryBuildError
from app.services.slot_extractor import SlotExtractionError
from app.services.slot_service import SlotService, build_slot_summary

router = APIRouter(prefix="/sessions", tags=["sessions"])

_PIPELINE_ERRORS = (QueryBuildError, PlacesAPIError, PlaceSelectionError, ItineraryFixError, NarrationError)


@router.post("/upload", response_model=UploadResponse)
async def upload_conversation(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> UploadResponse:
    content = (await file.read()).decode("utf-8")

    try:
        result = ingest_conversation(db, title=file.filename or "새 여행", file_content=content)
    except SlotExtractionError as exc:
        raise HTTPException(status_code=502, detail=f"슬롯 추출에 실패했습니다: {exc}") from exc

    return UploadResponse(
        session_id=result.session.id,
        slots=list(result.slots),
        raw_unparsed_count=result.raw_unparsed_count,
    )


@router.get("/{session_id}/slots", response_model=SlotSummaryOut)
def get_slot_summary(session_id: int, db: Session = Depends(get_db)) -> SlotSummaryOut:
    session = db.get(TravelSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    slots = db.query(Slot).filter_by(session_id=session_id).all()
    return SlotSummaryOut(**build_slot_summary(slots))


@router.post("/{session_id}/slots", response_model=SlotSummaryOut)
def fill_slots(
    session_id: int, request: SlotFillRequest, db: Session = Depends(get_db)
) -> SlotSummaryOut:
    session = db.get(TravelSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    slot_service = SlotService(db)
    fields = request.model_dump(exclude_none=True)
    for field_name, value in fields.items():
        field = SlotField(field_name)
        values = value if isinstance(value, list) else [value]
        for v in values:
            slot_service.create_user_provided_slot(session_id=session_id, field=field, value=v)
    db.commit()

    slots = db.query(Slot).filter_by(session_id=session_id).all()
    return SlotSummaryOut(**build_slot_summary(slots))


@router.post("/{session_id}/itinerary", response_model=ItineraryResponse)
def create_itinerary(
    session_id: int, request: ItineraryRequest, db: Session = Depends(get_db)
) -> ItineraryResponse:
    session = db.get(TravelSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    slots = db.query(Slot).filter_by(session_id=session_id).all()

    try:
        pipeline_result = generate_itinerary(db, session_id, slots, request.days)
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except _PIPELINE_ERRORS as exc:
        raise HTTPException(status_code=502, detail=f"일정 생성 파이프라인 실패: {exc}") from exc

    return ItineraryResponse(
        narrative=asdict(pipeline_result.narrative),
        iterations_used=pipeline_result.itinerary_result.iterations_used,
        violations=[asdict(v) for v in pipeline_result.itinerary_result.violations],
    )
