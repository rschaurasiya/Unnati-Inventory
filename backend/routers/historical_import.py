"""
Historical Sales Import & Normalization API Router
Endpoints for uploading tabular sales files, column detection, validation previews,
import confirmation, deduplication, batch auditing, and rollback.
"""
from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import HistoricalImportBatch
from backend.schemas import (
    ImportAnalyzeResponse,
    ConfirmImportRequest,
    ConfirmImportResponse,
    ImportBatchSummaryResponse,
    RollbackImportResponse
)
from backend.services.historical_import import (
    analyze_and_stage_file,
    execute_staged_import,
    rollback_import_batch,
    MAX_FILE_SIZE_BYTES,
    ALLOWED_EXTENSIONS
)

router = APIRouter(prefix="/api/v1/analytics/import", tags=["Historical Sales Import & Normalization"])


@router.post("/upload", response_model=ImportAnalyzeResponse, status_code=status.HTTP_200_OK)
async def upload_and_analyze_sales_file(
    file: UploadFile = File(..., description="Tabular historical sales file (CSV, XLSX, XLS)"),
    db: Session = Depends(get_db)
):
    """
    Securely uploads and analyzes a historical sales file.
    Performs column detection, alias mapping, date & value normalization,
    and validation. Stages valid rows in memory for preview without altering database state.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is missing."
        )

    # Check extension
    filename_lower = file.filename.lower()
    if not any(filename_lower.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format for '{file.filename}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty (0 bytes)."
        )

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file exceeds maximum limit of 10 MB (received {round(len(content)/(1024*1024), 2)} MB)."
        )

    try:
        analysis_result = analyze_and_stage_file(
            file_bytes=content,
            filename=file.filename,
            db=db
        )
        return analysis_result
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server error analyzing historical sales file: {str(e)}"
        )


@router.post("/confirm", response_model=ConfirmImportResponse, status_code=status.HTTP_201_CREATED)
def confirm_historical_import(
    req: ConfirmImportRequest,
    db: Session = Depends(get_db)
):
    """
    Confirms and commits a staged historical sales import into production database.
    Inserts canonical historical records, skips duplicate transactions,
    and recalculates daily product sales aggregates.
    """
    try:
        result = execute_staged_import(
            db=db,
            import_id=req.import_id,
            import_mode=req.import_mode,
            notes=req.notes
        )
        return result
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except RuntimeError as re:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(re)
        )


@router.post("/rollback/{import_id}", response_model=RollbackImportResponse, status_code=status.HTTP_200_OK)
def rollback_import(
    import_id: str,
    db: Session = Depends(get_db)
):
    """
    Rolls back an imported batch of historical sales.
    Deactivates associated historical records and reconciles affected daily summaries.
    """
    try:
        return rollback_import_batch(db=db, import_id=import_id)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(ve)
        )
    except RuntimeError as re:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(re)
        )


@router.get("/batches", response_model=List[ImportBatchSummaryResponse], status_code=status.HTTP_200_OK)
def list_import_batches(
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Retrieves audit log of past historical sales import batches.
    """
    batches = (
        db.query(HistoricalImportBatch)
        .order_by(HistoricalImportBatch.created_at.desc())
        .limit(limit)
        .all()
    )
    return batches


@router.get("/batches/{import_id}", response_model=ImportBatchSummaryResponse, status_code=status.HTTP_200_OK)
def get_batch_detail(
    import_id: str,
    db: Session = Depends(get_db)
):
    """
    Retrieves detailed audit record for a specific import batch.
    """
    batch = db.query(HistoricalImportBatch).filter(HistoricalImportBatch.import_id == import_id).first()
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import batch '{import_id}' not found."
        )
    return batch
