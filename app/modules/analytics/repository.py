"""
Analytics Repository - Database abstraction for analytics entities.
"""

from typing import List, Optional, Tuple
from uuid import UUID
from datetime import datetime
from sqlalchemy import select, func, update, delete, case
from sqlalchemy.ext.asyncio import AsyncSession
from .models import AnalyticsSummary, AnalyticsQueryLog, ResponseStatus
from ..knowledge_bases.models import DocumentIngestionRun, KnowledgeBase
from ..auth.models import User

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

    async def get_cost_governance_data(
        self,
        user_id: Optional[UUID] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> dict:
        # Category breakdown for Ingestions
        cat_stmt = select(
            DocumentIngestionRun.document_category,
            func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
            func.sum(DocumentIngestionRun.llm_output_tokens).label("out"),
            func.sum(DocumentIngestionRun.embedding_tokens).label("emb"),
            func.sum(DocumentIngestionRun.embedding_cost_usd).label("emb_cost")
        ).where(DocumentIngestionRun.tenant_id == self.tenant_id)
        
        if user_id:
            cat_stmt = cat_stmt.join(KnowledgeBase, DocumentIngestionRun.document_id == KnowledgeBase.id).where(KnowledgeBase.user_id == user_id)
        if start_date:
            cat_stmt = cat_stmt.where(DocumentIngestionRun.started_at >= start_date)
        if end_date:
            cat_stmt = cat_stmt.where(DocumentIngestionRun.started_at <= end_date)
            
        cat_stmt = cat_stmt.group_by(DocumentIngestionRun.document_category)
        cat_res = await self.db.execute(cat_stmt)
        
        categories = []
        for row in cat_res.all():
            inp = int(row.inp or 0)
            out = int(row.out or 0)
            emb = int(row.emb or 0)
            emb_cost = float(row.emb_cost or 0.0)
            categories.append({
                "document_category": row.document_category,
                "input_tokens": inp,
                "output_tokens": out,
                "embedding_tokens": emb,
                "embedding_cost_usd": emb_cost
            })

        # Fetch chat/RAG queries to aggregate conversational RAG tokens
        chat_stmt = select(
            func.sum(AnalyticsQueryLog.llm_input_tokens).label("inp"),
            func.sum(AnalyticsQueryLog.llm_output_tokens).label("out"),
            func.sum(AnalyticsQueryLog.embedding_tokens).label("emb"),
            func.sum(AnalyticsQueryLog.embedding_cost_usd).label("emb_cost")
        ).where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        
        if user_id:
            chat_stmt = chat_stmt.where(AnalyticsQueryLog.user_id == user_id)
        if start_date:
            chat_stmt = chat_stmt.where(AnalyticsQueryLog.created_at >= start_date)
        if end_date:
            chat_stmt = chat_stmt.where(AnalyticsQueryLog.created_at <= end_date)
            
        chat_res = await self.db.execute(chat_stmt)
        chat_row = chat_res.first()
        
        chat_inp = int(chat_row.inp or 0) if chat_row else 0
        chat_out = int(chat_row.out or 0) if chat_row else 0
        chat_emb = int(chat_row.emb or 0) if chat_row else 0
        chat_emb_cost = float(chat_row.emb_cost or 0.0) if chat_row else 0.0
        
        if chat_inp > 0 or chat_out > 0 or chat_emb > 0:
            categories.append({
                "document_category": "Conversational RAG",
                "input_tokens": chat_inp,
                "output_tokens": chat_out,
                "embedding_tokens": chat_emb,
                "embedding_cost_usd": chat_emb_cost
            })
            
        # Daily token trends from ingestion runs
        day_stmt = select(
            func.to_char(DocumentIngestionRun.started_at, 'YYYY-MM-DD').label("date"),
            func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
            func.sum(DocumentIngestionRun.llm_output_tokens).label("out"),
            func.sum(DocumentIngestionRun.embedding_tokens).label("emb"),
            func.sum(DocumentIngestionRun.embedding_cost_usd).label("emb_cost")
        ).where(DocumentIngestionRun.tenant_id == self.tenant_id)
        
        if user_id:
            day_stmt = day_stmt.join(KnowledgeBase, DocumentIngestionRun.document_id == KnowledgeBase.id).where(KnowledgeBase.user_id == user_id)
        if start_date:
            day_stmt = day_stmt.where(DocumentIngestionRun.started_at >= start_date)
        if end_date:
            day_stmt = day_stmt.where(DocumentIngestionRun.started_at <= end_date)
            
        day_stmt = day_stmt.group_by("date").order_by("date")
        day_res = await self.db.execute(day_stmt)
        
        daily_map = {}
        for row in day_res.all():
            dt = row.date
            daily_map[dt] = {
                "date": dt,
                "input_tokens": int(row.inp or 0),
                "output_tokens": int(row.out or 0),
                "embedding_tokens": int(row.emb or 0),
                "embedding_cost_usd": float(row.emb_cost or 0.0)
            }

        # Daily token trends from chat queries
        chat_day_stmt = select(
            func.to_char(AnalyticsQueryLog.created_at, 'YYYY-MM-DD').label("date"),
            func.sum(AnalyticsQueryLog.llm_input_tokens).label("inp"),
            func.sum(AnalyticsQueryLog.llm_output_tokens).label("out"),
            func.sum(AnalyticsQueryLog.embedding_tokens).label("emb"),
            func.sum(AnalyticsQueryLog.embedding_cost_usd).label("emb_cost")
        ).where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        
        if user_id:
            chat_day_stmt = chat_day_stmt.where(AnalyticsQueryLog.user_id == user_id)
        if start_date:
            chat_day_stmt = chat_day_stmt.where(AnalyticsQueryLog.created_at >= start_date)
        if end_date:
            chat_day_stmt = chat_day_stmt.where(AnalyticsQueryLog.created_at <= end_date)
            
        chat_day_stmt = chat_day_stmt.group_by("date").order_by("date")
        chat_day_res = await self.db.execute(chat_day_stmt)
        
        for row in chat_day_res.all():
            dt = row.date
            inp = int(row.inp or 0)
            out = int(row.out or 0)
            emb = int(row.emb or 0)
            emb_cost = float(row.emb_cost or 0.0)
            
            if dt in daily_map:
                daily_map[dt]["input_tokens"] += inp
                daily_map[dt]["output_tokens"] += out
                if "embedding_tokens" in daily_map[dt]:
                    daily_map[dt]["embedding_tokens"] += emb
                    daily_map[dt]["embedding_cost_usd"] += emb_cost
                else:
                    daily_map[dt]["embedding_tokens"] = emb
                    daily_map[dt]["embedding_cost_usd"] = emb_cost
            else:
                daily_map[dt] = {
                    "date": dt,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "embedding_tokens": emb,
                    "embedding_cost_usd": emb_cost
                }

        # Sort combined daily trends by date
        daily_tokens = sorted(daily_map.values(), key=lambda x: x["date"])
            
        return {
            "categories": categories,
            "daily_tokens": daily_tokens
        }

    async def get_user_cost_governance(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> list:
        # Ingestion costs per user
        ingest_stmt = select(
            User.id.label("user_id"),
            User.email.label("user_email"),
            func.sum(DocumentIngestionRun.llm_input_tokens).label("ingest_inp"),
            func.sum(DocumentIngestionRun.llm_output_tokens).label("ingest_out"),
            func.sum(DocumentIngestionRun.embedding_tokens).label("ingest_emb"),
            func.sum(DocumentIngestionRun.embedding_cost_usd).label("ingest_emb_cost")
        ).select_from(User).join(
            KnowledgeBase, KnowledgeBase.user_id == User.id
        ).join(
            DocumentIngestionRun, DocumentIngestionRun.document_id == KnowledgeBase.id
        ).where(
            User.tenant_id == self.tenant_id
        )
        if start_date:
            ingest_stmt = ingest_stmt.where(DocumentIngestionRun.started_at >= start_date)
        if end_date:
            ingest_stmt = ingest_stmt.where(DocumentIngestionRun.started_at <= end_date)
        ingest_stmt = ingest_stmt.group_by(User.id, User.email)
        
        ingest_res = await self.db.execute(ingest_stmt)

        # Chat/RAG costs per user
        chat_stmt = select(
            User.id.label("user_id"),
            User.email.label("user_email"),
            func.sum(AnalyticsQueryLog.llm_input_tokens).label("chat_inp"),
            func.sum(AnalyticsQueryLog.llm_output_tokens).label("chat_out"),
            func.sum(AnalyticsQueryLog.embedding_tokens).label("chat_emb"),
            func.sum(AnalyticsQueryLog.embedding_cost_usd).label("chat_emb_cost")
        ).select_from(User).join(
            AnalyticsQueryLog, AnalyticsQueryLog.user_id == User.id
        ).where(
            User.tenant_id == self.tenant_id
        )
        if start_date:
            chat_stmt = chat_stmt.where(AnalyticsQueryLog.created_at >= start_date)
        if end_date:
            chat_stmt = chat_stmt.where(AnalyticsQueryLog.created_at <= end_date)
        chat_stmt = chat_stmt.group_by(User.id, User.email)
        
        chat_res = await self.db.execute(chat_stmt)

        user_costs = {}
        def get_user_entry(uid, email):
            if uid not in user_costs:
                user_costs[uid] = {
                    "user_id": uid,
                    "user_email": email,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0
                }
            return user_costs[uid]
            
        inp_price_per_m = 0.10
        out_price_per_m = 0.15
        
        for row in ingest_res.all():
            uid = row.user_id
            email = row.user_email
            inp = int(row.ingest_inp or 0)
            out = int(row.ingest_out or 0)
            emb = int(row.ingest_emb or 0)
            emb_cost = float(row.ingest_emb_cost or 0.0)
            
            entry = get_user_entry(uid, email)
            entry["total_tokens"] += inp + out + emb
            entry["total_cost_usd"] += (inp / 1_000_000 * inp_price_per_m) + \
                                       (out / 1_000_000 * out_price_per_m) + \
                                       emb_cost
                                       
        for row in chat_res.all():
            uid = row.user_id
            email = row.user_email
            inp = int(row.chat_inp or 0)
            out = int(row.chat_out or 0)
            emb = int(row.chat_emb or 0)
            emb_cost = float(row.chat_emb_cost or 0.0)
            
            entry = get_user_entry(uid, email)
            entry["total_tokens"] += inp + out + emb
            entry["total_cost_usd"] += (inp / 1_000_000 * inp_price_per_m) + \
                                       (out / 1_000_000 * out_price_per_m) + \
                                       emb_cost
                                       
        for entry in user_costs.values():
            entry["total_cost_usd"] = round(entry["total_cost_usd"], 4)
            
        return list(user_costs.values())

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
