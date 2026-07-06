import uuid
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from app.models.base import Base

class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    
    job_type = Column(String, nullable=False, index=True)  # e.g., 'pdf_ingestion'
    kb_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String, nullable=False, default="queued")  # queued, processing, completed, failed
    progress = Column(Integer, default=0)
    current_step = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    file_name = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
