"""Phase 2 Knowledge Layer: Background Jobs

Provides ARQ background job functions and pipeline orchestrators:
- run_phase2_pipeline: Orchestrator executing Phase 2 stages
- stage_profile_stub
- stage_relationships_stub
- stage_value_index_stub
- stage_enrich_stub
- trigger_phase2_sync_job: Entry point to trigger Phase 2 processing
- JobRunRecord, StageExecutionRecord, JobStatus, StageStatus
"""

from .pipeline import (
    JobStatus,
    StageStatus,
    StageExecutionRecord,
    JobRunRecord,
    get_job_run,
    stage_profile_stub,
    stage_relationships_stub,
    stage_value_index_stub,
    stage_enrich_stub,
    run_phase2_pipeline,
    trigger_phase2_sync_job,
    run_pipeline_for_kb_local,
)
from .schema_indexer import build_and_index_schema_docs

__all__ = [
    "JobStatus",
    "StageStatus",
    "StageExecutionRecord",
    "JobRunRecord",
    "get_job_run",
    "stage_profile_stub",
    "stage_relationships_stub",
    "stage_value_index_stub",
    "stage_enrich_stub",
    "run_phase2_pipeline",
    "trigger_phase2_sync_job",
    "run_pipeline_for_kb_local",
    "build_and_index_schema_docs",
]

