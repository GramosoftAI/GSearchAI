"""
Analytics Repository - Database abstraction for analytics entities.
"""

from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy import select, func, update, delete, case
from sqlalchemy.ext.asyncio import AsyncSession
from .models import AnalyticsSummary, AnalyticsQueryLog, ResponseStatus
from ..knowledge_bases.models import DocumentIngestionRun

class AnalyticsRepository:
    def __init__(self, db: AsyncSession, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id

    async def create_summary(self, summary_data: dict) -> AnalyticsSummary:
        summary = AnalyticsSummary(**summary_data, tenant_id=self.tenant_id)
        self.db.add(summary)
        await self.db.flush()
        return summary

    async def get_summary_by_id(self, summary_id: UUID) -> Optional[AnalyticsSummary]:
        stmt = select(AnalyticsSummary).where(
            AnalyticsSummary.id == summary_id,
            AnalyticsSummary.tenant_id == self.tenant_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_summaries(self, skip: int = 0, limit: int = 100) -> List[AnalyticsSummary]:
        stmt = select(AnalyticsSummary).where(
            AnalyticsSummary.tenant_id == self.tenant_id
        ).offset(skip).limit(limit).order_by(AnalyticsSummary.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_summary(self, summary_id: UUID, update_data: dict) -> Optional[AnalyticsSummary]:
        stmt = update(AnalyticsSummary).where(
            AnalyticsSummary.id == summary_id,
            AnalyticsSummary.tenant_id == self.tenant_id
        ).values(**update_data).returning(AnalyticsSummary)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_summary(self, summary_id: UUID) -> bool:
        stmt = delete(AnalyticsSummary).where(
            AnalyticsSummary.id == summary_id,
            AnalyticsSummary.tenant_id == self.tenant_id
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def create_query_log(self, log_data: dict) -> AnalyticsQueryLog:
        log = AnalyticsQueryLog(**log_data, tenant_id=self.tenant_id)
        self.db.add(log)
        await self.db.flush()
        return log

    async def get_query_logs(self, skip: int = 0, limit: int = 100) -> List[AnalyticsQueryLog]:
        stmt = select(AnalyticsQueryLog).where(
            AnalyticsQueryLog.tenant_id == self.tenant_id
        ).offset(skip).limit(limit).order_by(AnalyticsQueryLog.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_aggregated_metrics(self) -> dict:
        """Fetch high-level metrics for dashboard directly from logs."""
        stmt = select(
            func.count(AnalyticsQueryLog.id).label("total"),
            func.count(AnalyticsQueryLog.id).filter(
                AnalyticsQueryLog.response_status == ResponseStatus.SUCCESS
            ).label("answered"),
            func.count(AnalyticsQueryLog.id).filter(
                AnalyticsQueryLog.response_status == ResponseStatus.UNANSWERED
            ).label("unanswered"),
            func.avg(AnalyticsQueryLog.confidence_score).label("avg_conf")
        ).where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        
        result = await self.db.execute(stmt)
        row = result.first()
        
        return {
            "total_queries": row.total or 0,
            "answered_queries": int(row.answered or 0),
            "unanswered_queries": int(row.unanswered or 0),
            "avg_confidence": float(row.avg_conf or 0.0)
        }

    async def get_query_trends(self) -> List[Tuple[str, int]]:
        """Get daily query volume trends."""
        stmt = select(
            func.to_char(AnalyticsQueryLog.created_at, 'YYYY-MM-DD').label("date"),
            func.count(AnalyticsQueryLog.id).label("count")
        ).where(
            AnalyticsQueryLog.tenant_id == self.tenant_id
        ).group_by("date").order_by("date").limit(30)
        
        result = await self.db.execute(stmt)
        return result.all()

    async def get_unanswered_logs(self, limit: int = 50) -> List[AnalyticsQueryLog]:
        stmt = select(AnalyticsQueryLog).where(
            AnalyticsQueryLog.tenant_id == self.tenant_id,
            AnalyticsQueryLog.response_status == ResponseStatus.UNANSWERED
        ).limit(limit).order_by(AnalyticsQueryLog.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_confidence_distribution(self) -> List[dict]:
        """Get distribution of confidence scores in 0.2 buckets."""
        bucket = func.floor(AnalyticsQueryLog.confidence_score * 5) / 5.0
        stmt = select(
            bucket,
            func.count(AnalyticsQueryLog.id)
        ).where(
            AnalyticsQueryLog.tenant_id == self.tenant_id
        ).group_by(bucket).order_by(bucket)
        
        result = await self.db.execute(stmt)
        rows = result.all()
        
        # Initialize buckets
        distribution = {
            "0.0-0.2": 0,
            "0.2-0.4": 0,
            "0.4-0.6": 0,
            "0.6-0.8": 0,
            "0.8-1.0": 0
        }
        
        for floor_val, count in rows:
            if floor_val < 0.2: distribution["0.0-0.2"] += count
            elif floor_val < 0.4: distribution["0.2-0.4"] += count
            elif floor_val < 0.6: distribution["0.4-0.6"] += count
            elif floor_val < 0.8: distribution["0.6-0.8"] += count
            else: distribution["0.8-1.0"] += count
            
        return [{"bucket": k, "count": v} for k, v in distribution.items()]

    async def get_operational_dashboard_metrics(self) -> dict:
        stmt = select(
            func.count(DocumentIngestionRun.id).label("processed"),
            func.count(DocumentIngestionRun.id).filter(DocumentIngestionRun.status == "FAILED").label("failures"),
            func.sum(DocumentIngestionRun.retry_count).label("retries"),
            func.sum(DocumentIngestionRun.fallback_count).label("fallbacks"),
            func.sum(DocumentIngestionRun.repair_count).label("repairs"),
            func.sum(DocumentIngestionRun.chunk_count).label("chunks"),
            func.avg(DocumentIngestionRun.total_duration_ms).label("avg_latency"),
            func.percentile_cont(0.95).within_group(DocumentIngestionRun.total_duration_ms.asc()).label("p95_latency"),
            func.count(DocumentIngestionRun.id).filter(DocumentIngestionRun.total_duration_ms <= 60000).label("slo_met")
        ).where(DocumentIngestionRun.tenant_id == self.tenant_id)
        
        result = await self.db.execute(stmt)
        row = result.first()
        
        chunks = int(row.chunks or 1)
        if chunks == 0: chunks = 1
        
        processed = int(row.processed or 0)
        slo_met = int(row.slo_met or 0)
        slo_percent = (slo_met / processed * 100) if processed > 0 else 100.0
        
        return {
            "documents_processed": processed,
            "failures": int(row.failures or 0),
            "retries": int(row.retries or 0),
            "fallbacks": int(row.fallbacks or 0),
            "repair_rate": float(row.repairs or 0) / chunks,
            "avg_latency_ms": float(row.avg_latency or 0.0),
            "p95_latency_ms": float(row.p95_latency or 0.0),
            "slo_compliance_percent": slo_percent
        }

    async def get_operational_trends(self) -> List[dict]:
        stmt = select(
            func.to_char(DocumentIngestionRun.created_at, 'YYYY-MM-DD').label("date"),
            func.sum(DocumentIngestionRun.entity_count).label("entities"),
            func.sum(DocumentIngestionRun.triplet_count).label("triplets"),
            func.sum(DocumentIngestionRun.chunk_count).label("chunks"),
            func.sum(DocumentIngestionRun.fallback_count).label("fallbacks"),
            func.sum(DocumentIngestionRun.nodes_created).label("nodes"),
            func.sum(DocumentIngestionRun.relationships_created).label("rels")
        ).where(
            DocumentIngestionRun.tenant_id == self.tenant_id
        ).group_by("date").order_by("date").limit(30)
        
        result = await self.db.execute(stmt)
        rows = result.all()
        
        trends = []
        for row in rows:
            c = int(row.chunks or 1)
            if c == 0: c = 1
            trends.append({
                "date": row.date,
                "entities_per_chunk": float(row.entities or 0) / c,
                "triplets_per_chunk": float(row.triplets or 0) / c,
                "fallback_rate": float(row.fallbacks or 0) / c,
                "nodes_created": int(row.nodes or 0),
                "relationships_created": int(row.rels or 0)
            })
        return trends

    async def get_cost_governance_data(self) -> dict:
        from ..chats.models import ChatMessage

        # Category breakdown
        cat_stmt = select(
            DocumentIngestionRun.document_category,
            func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
            func.sum(DocumentIngestionRun.llm_output_tokens).label("out")
        ).where(DocumentIngestionRun.tenant_id == self.tenant_id).group_by(DocumentIngestionRun.document_category)
        
        cat_res = await self.db.execute(cat_stmt)
        categories = []
        for row in cat_res.all():
            inp = int(row.inp or 0)
            out = int(row.out or 0)
            categories.append({
                "document_category": row.document_category,
                "input_tokens": inp,
                "output_tokens": out
            })

        # Fetch assistant messages to aggregate conversational RAG tokens
        chat_stmt = select(
            ChatMessage.created_at,
            ChatMessage.message_metadata
        ).where(
            ChatMessage.tenant_id == self.tenant_id,
            ChatMessage.role == "assistant"
        )
        
        chat_res = await self.db.execute(chat_stmt)
        
        chat_inp = 0
        chat_out = 0
        chat_daily = {}
        
        for created_at, metadata in chat_res.all():
            if not metadata or "stats" not in metadata:
                continue
            stats = metadata["stats"]
            inp = int(stats.get("llm_input_tokens") or 0)
            out = int(stats.get("llm_output_tokens") or 0)
            
            chat_inp += inp
            chat_out += out
            
            if created_at:
                # If created_at is a datetime, format it. Otherwise if it's a string, use it directly or format.
                if isinstance(created_at, str):
                    dt = created_at[:10]
                else:
                    dt = created_at.strftime("%Y-%m-%d")
                if dt not in chat_daily:
                    chat_daily[dt] = {"inp": 0, "out": 0}
                chat_daily[dt]["inp"] += inp
                chat_daily[dt]["out"] += out

        if chat_inp > 0 or chat_out > 0:
            categories.append({
                "document_category": "Conversational RAG",
                "input_tokens": chat_inp,
                "output_tokens": chat_out
            })
            
        # Daily token trends from ingestion runs
        day_stmt = select(
            func.to_char(DocumentIngestionRun.started_at, 'YYYY-MM-DD').label("date"),
            func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
            func.sum(DocumentIngestionRun.llm_output_tokens).label("out")
        ).where(DocumentIngestionRun.tenant_id == self.tenant_id).group_by("date").order_by("date").limit(30)
        
        day_res = await self.db.execute(day_stmt)
        
        daily_map = {}
        for row in day_res.all():
            dt = row.date
            daily_map[dt] = {
                "date": dt,
                "input_tokens": int(row.inp or 0),
                "output_tokens": int(row.out or 0)
            }

        # Merge daily trends from chat messages
        for dt, tokens in chat_daily.items():
            if dt in daily_map:
                daily_map[dt]["input_tokens"] += tokens["inp"]
                daily_map[dt]["output_tokens"] += tokens["out"]
            else:
                daily_map[dt] = {
                    "date": dt,
                    "input_tokens": tokens["inp"],
                    "output_tokens": tokens["out"]
                }

        # Sort combined daily trends by date
        daily_tokens = sorted(daily_map.values(), key=lambda x: x["date"])[-30:]
            
        return {
            "categories": categories,
            "daily_tokens": daily_tokens
        }

    async def get_capacity_planning_data(self) -> dict:
        stmt = select(
            func.to_char(DocumentIngestionRun.created_at, 'YYYY-MM-DD').label("date"),
            func.sum(DocumentIngestionRun.chunk_count).label("chunks"),
            func.count(DocumentIngestionRun.id).label("docs")
        ).where(DocumentIngestionRun.tenant_id == self.tenant_id).group_by("date").order_by("date").limit(30)
        
        res = await self.db.execute(stmt)
        daily_stats = []
        for row in res.all():
            daily_stats.append({
                "date": row.date,
                "chunks": int(row.chunks or 0),
                "docs": int(row.docs or 0)
            })
            
        return {"daily_stats": daily_stats}
