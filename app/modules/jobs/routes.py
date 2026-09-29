from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.core.database import get_db
from app.modules.knowledge_bases.routes import get_tenant_and_user
from .service import JobService

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

@router.get("/{job_id}", response_model=dict)
async def get_job_status(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get the status and progress of a background job.
    """
    tenant_id, user_id = get_tenant_and_user(request)
    
    job_service = JobService(db, tenant_id)
    result = await job_service.get_job(job_id)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=result.get("meta", {}).get("status_code", 400),
            detail=result.get("error")
        )
        
    return result

@router.delete("/{job_id}", response_model=dict)
async def cancel_and_delete_job(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Cancel a running job and delete it from the database.
    """
    tenant_id, user_id = get_tenant_and_user(request)
    
    job_service = JobService(db, tenant_id)
    result = await job_service.cancel_and_delete_job(job_id)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=result.get("meta", {}).get("status_code", 400),
            detail=result.get("error")
        )
        
    return result
