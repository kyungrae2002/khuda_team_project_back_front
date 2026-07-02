from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.evaluator import evaluate_extraction, evaluate_recent_violations

router = APIRouter(tags=["evaluation"])


@router.get("/evaluation")
def get_evaluation(db: Session = Depends(get_db)) -> dict:
    extraction = evaluate_extraction()

    metrics: dict[str, float | int | str] = {}
    if extraction.error is not None:
        metrics["extraction_f1"] = "N/A"
        metrics["extraction_error"] = extraction.error
    else:
        metrics["extraction_precision"] = round(extraction.precision, 2)
        metrics["extraction_recall"] = round(extraction.recall, 2)
        metrics["extraction_f1"] = round(extraction.f1, 2)

    metrics.update(evaluate_recent_violations(db))
    return metrics
