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
from app.core.llm.pricing import calculate_token_cost

def get_configured_models_catalog() -> list[dict]:
    """
    Returns the complete catalog of models used across GraphMind,
    including primary stage models, budget fallback models, embedding models,
    and routing/memory/reranker models.
    """
    from app.core.config import get_settings
    from app.core.llm.pricing import get_model_pricing

    settings = get_settings()

    catalog = [
        {
            "stage": "answer",
            "model_name": settings.model_answer,
            "purpose": "Conversational Answer Generation",
            "model_type": "primary",
            "default_status": "active"
        },
        {
            "stage": "answer_fallback",
            "model_name": settings.model_answer_fallback,
            "purpose": "Conversational Answer Generation (Fallback)",
            "model_type": "fallback",
            "default_status": "fallback_ready"
        },
        {
            "stage": "extraction",
            "model_name": settings.model_extraction,
            "purpose": "Entity & Triplet Extraction",
            "model_type": "primary",
            "default_status": "active"
        },
        {
            "stage": "extraction_fallback",
            "model_name": settings.model_extraction_fallback,
            "purpose": "Entity & Triplet Extraction (Fallback)",
            "model_type": "fallback",
            "default_status": "fallback_ready"
        },
        {
            "stage": "nl_to_cypher",
            "model_name": settings.model_nl_to_cypher,
            "purpose": "Natural Language to Cypher",
            "model_type": "primary",
            "default_status": "configured"
        },
        {
            "stage": "nl_to_cypher_fallback",
            "model_name": settings.model_nl_to_cypher_fallback,
            "purpose": "Natural Language to Cypher (Fallback)",
            "model_type": "fallback",
            "default_status": "fallback_ready"
        },
        {
            "stage": "memory",
            "model_name": settings.model_memory,
            "purpose": "Episodic & Preference Memory",
            "model_type": "primary",
            "default_status": "configured"
        },
        {
            "stage": "intent",
            "model_name": settings.model_intent,
            "purpose": "User Intent Classification & Routing",
            "model_type": "primary",
            "default_status": "configured"
        },
        {
            "stage": "reranker",
            "model_name": settings.model_reranker,
            "purpose": "Document Chunk Reranking",
            "model_type": "primary",
            "default_status": "configured"
        },
        {
            "stage": "reranker_fallback",
            "model_name": settings.model_reranker_fallback,
            "purpose": "Document Chunk Reranking (Fallback)",
            "model_type": "fallback",
            "default_status": "fallback_ready"
        },
        {
            "stage": "embedding",
            "model_name": settings.model_embedding,
            "purpose": "Vector Embeddings (Document Chunks & Queries)",
            "model_type": "primary",
            "default_status": "active"
        },
        {
            "stage": "vision",
            "model_name": settings.model_vision,
            "purpose": "Vision & Multimodal Processing",
            "model_type": "primary",
            "default_status": "configured"
        },
    ]

    for item in catalog:
        p_info = get_model_pricing(item["model_name"])
        item["provider"] = getattr(p_info, "provider", "deepinfra") or "deepinfra"

    return catalog

class AnalyticsRepository:
    def __init__(self, db: AsyncSession, tenant_id: Optional[UUID] = None):
        self.db = db
        self.tenant_id = tenant_id

    async def create_summary(self, summary_data: dict) -> AnalyticsSummary:
        summary = AnalyticsSummary(**summary_data, tenant_id=self.tenant_id)
        self.db.add(summary)
        await self.db.flush()
        return summary

    async def get_summary_by_id(self, summary_id: UUID) -> Optional[AnalyticsSummary]:
        stmt = select(AnalyticsSummary).where(AnalyticsSummary.id == summary_id)
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsSummary.tenant_id == self.tenant_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_summaries(self, skip: int = 0, limit: int = 100) -> List[AnalyticsSummary]:
        stmt = select(AnalyticsSummary)
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsSummary.tenant_id == self.tenant_id)
        stmt = stmt.offset(skip).limit(limit).order_by(AnalyticsSummary.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_summary(self, summary_id: UUID, update_data: dict) -> Optional[AnalyticsSummary]:
        stmt = update(AnalyticsSummary).where(AnalyticsSummary.id == summary_id)
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsSummary.tenant_id == self.tenant_id)
        stmt = stmt.values(**update_data).returning(AnalyticsSummary)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_summary(self, summary_id: UUID) -> bool:
        stmt = delete(AnalyticsSummary).where(AnalyticsSummary.id == summary_id)
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsSummary.tenant_id == self.tenant_id)
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def create_query_log(self, log_data: dict) -> AnalyticsQueryLog:
        log = AnalyticsQueryLog(**log_data, tenant_id=self.tenant_id)
        self.db.add(log)
        await self.db.flush()
        return log

    async def get_query_logs(self, skip: int = 0, limit: int = 100) -> List[AnalyticsQueryLog]:
        stmt = select(AnalyticsQueryLog)
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        stmt = stmt.offset(skip).limit(limit).order_by(AnalyticsQueryLog.created_at.desc())
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
        )
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        
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
        )
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        stmt = stmt.group_by("date").order_by("date").limit(30)
        
        result = await self.db.execute(stmt)
        return result.all()

    async def get_unanswered_logs(self, limit: int = 50) -> List[AnalyticsQueryLog]:
        stmt = select(AnalyticsQueryLog).where(
            AnalyticsQueryLog.response_status == ResponseStatus.UNANSWERED
        )
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        stmt = stmt.limit(limit).order_by(AnalyticsQueryLog.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_confidence_distribution(self) -> List[dict]:
        """Get distribution of confidence scores in 0.2 buckets."""
        bucket = func.floor(AnalyticsQueryLog.confidence_score * 5) / 5.0
        stmt = select(
            bucket,
            func.count(AnalyticsQueryLog.id)
        )
        if self.tenant_id is not None:
            stmt = stmt.where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        stmt = stmt.group_by(bucket).order_by(bucket)
        
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
        )
        if self.tenant_id is not None:
            stmt = stmt.where(DocumentIngestionRun.tenant_id == self.tenant_id)
        
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
        )
        if self.tenant_id is not None:
            stmt = stmt.where(DocumentIngestionRun.tenant_id == self.tenant_id)
        stmt = stmt.group_by("date").order_by("date").limit(30)
        
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
        )
        if self.tenant_id is not None:
            cat_stmt = cat_stmt.where(DocumentIngestionRun.tenant_id == self.tenant_id)
        
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
        )
        if self.tenant_id is not None:
            chat_stmt = chat_stmt.where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        
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
        )
        if self.tenant_id is not None:
            day_stmt = day_stmt.where(DocumentIngestionRun.tenant_id == self.tenant_id)
        
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
        )
        if self.tenant_id is not None:
            chat_day_stmt = chat_day_stmt.where(AnalyticsQueryLog.tenant_id == self.tenant_id)
        
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
        )
        if self.tenant_id is not None:
            ingest_stmt = ingest_stmt.where(User.tenant_id == self.tenant_id)
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
            func.sum(AnalyticsQueryLog.embedding_cost_usd).label("chat_emb_cost"),
            func.sum(AnalyticsQueryLog.total_tokens).label("chat_tot_tok"),
            func.sum(AnalyticsQueryLog.total_cost_usd).label("chat_tot_cost"),
        ).select_from(User).join(
            AnalyticsQueryLog, AnalyticsQueryLog.user_id == User.id
        )
        if self.tenant_id is not None:
            chat_stmt = chat_stmt.where(User.tenant_id == self.tenant_id)
        if start_date:
            chat_stmt = chat_stmt.where(AnalyticsQueryLog.created_at >= start_date)
        if end_date:
            chat_stmt = chat_stmt.where(AnalyticsQueryLog.created_at <= end_date)
        chat_stmt = chat_stmt.group_by(User.id, User.email)
        
        chat_res = await self.db.execute(chat_stmt)

        from app.core.llm.pricing import get_model_pricing
        default_inp_p, default_out_p = get_model_pricing(None)

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
        
        for row in ingest_res.all():
            uid = row.user_id
            email = row.user_email
            inp = int(row.ingest_inp or 0)
            out = int(row.ingest_out or 0)
            emb = int(row.ingest_emb or 0)
            emb_cost = float(row.ingest_emb_cost or 0.0)
            
            entry = get_user_entry(uid, email)
            entry["total_tokens"] += inp + out + emb
            entry["total_cost_usd"] += (inp / 1_000_000 * default_inp_p) + (out / 1_000_000 * default_out_p) + emb_cost
                                       
        for row in chat_res.all():
            uid = row.user_id
            email = row.user_email
            inp = int(row.chat_inp or 0)
            out = int(row.chat_out or 0)
            emb = int(row.chat_emb or 0)
            
            raw_emb_cost = getattr(row, "chat_emb_cost", 0.0)
            emb_cost = float(raw_emb_cost) if isinstance(raw_emb_cost, (int, float)) and not isinstance(raw_emb_cost, bool) else 0.0
            
            raw_tot_cost = getattr(row, "chat_tot_cost", None)
            tot_cost = float(raw_tot_cost) if isinstance(raw_tot_cost, (int, float)) and not isinstance(raw_tot_cost, bool) else None
            
            entry = get_user_entry(uid, email)
            entry["total_tokens"] += inp + out + emb
            if tot_cost is not None and tot_cost > 0:
                entry["total_cost_usd"] += tot_cost
            else:
                entry["total_cost_usd"] += (inp / 1_000_000 * default_inp_p) + (out / 1_000_000 * default_out_p) + emb_cost
                                       
        for entry in user_costs.values():
            entry["total_cost_usd"] = round(entry["total_cost_usd"], 4)
            
        return list(user_costs.values())

    async def get_capacity_planning_data(self) -> dict:
        stmt = select(
            func.to_char(DocumentIngestionRun.created_at, 'YYYY-MM-DD').label("date"),
            func.sum(DocumentIngestionRun.chunk_count).label("chunks"),
            func.count(DocumentIngestionRun.id).label("docs")
        )
        if self.tenant_id is not None:
            stmt = stmt.where(DocumentIngestionRun.tenant_id == self.tenant_id)
        stmt = stmt.group_by("date").order_by("date").limit(30)
        
        res = await self.db.execute(stmt)
        daily_stats = []
        for row in res.all():
            daily_stats.append({
                "date": row.date,
                "chunks": int(row.chunks or 0),
                "docs": int(row.docs or 0)
            })
            
        return {"daily_stats": daily_stats}

    async def get_token_consumption(
        self,
        user_id: Optional[UUID] = None,
        model_name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        session_id: Optional[UUID] = None,
        request_id: Optional[str] = None,
        include_records: bool = False,
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        """Fetch aggregated and detailed token consumption metrics with multi-dimensional filtering."""
        conditions = []
        if self.tenant_id is not None:
            conditions.append(AnalyticsQueryLog.tenant_id == self.tenant_id)
        if user_id:
            conditions.append(AnalyticsQueryLog.user_id == user_id)
        if model_name and model_name.strip():
            conditions.append(AnalyticsQueryLog.model_name == model_name.strip())
        if start_date:
            conditions.append(AnalyticsQueryLog.created_at >= start_date)
        if end_date:
            conditions.append(AnalyticsQueryLog.created_at <= end_date)
        if session_id:
            conditions.append(AnalyticsQueryLog.session_id == session_id)
        if request_id and request_id.strip():
            conditions.append(AnalyticsQueryLog.request_id == request_id.strip())

        from app.core.config import get_settings
        from app.core.llm.pricing import get_model_pricing
        settings = get_settings()

        # 1. Summary Totals (Chat Logs)
        summary_stmt = select(
            func.sum(AnalyticsQueryLog.llm_input_tokens).label("tot_inp"),
            func.sum(AnalyticsQueryLog.llm_output_tokens).label("tot_out"),
            func.sum(AnalyticsQueryLog.embedding_tokens).label("tot_emb"),
            func.sum(AnalyticsQueryLog.total_tokens).label("tot_tok"),
            func.sum(AnalyticsQueryLog.total_cost_usd).label("tot_cost"),
            func.count(AnalyticsQueryLog.id).label("tot_queries"),
        ).where(*conditions)
        summary_res = await self.db.execute(summary_stmt)
        s_row = summary_res.first()

        tot_inp = int(s_row.tot_inp or 0)
        tot_out = int(s_row.tot_out or 0)
        tot_emb = int(s_row.tot_emb or 0)
        tot_cost = float(s_row.tot_cost or 0.0)
        tot_queries = int(s_row.tot_queries or 0)

        # Ingestion Totals (Document Ingestion Runs)
        include_ingestion = not (session_id or request_id)
        ingest_conditions = []
        if include_ingestion:
            if self.tenant_id is not None:
                ingest_conditions.append(DocumentIngestionRun.tenant_id == self.tenant_id)
            if start_date:
                ingest_conditions.append(DocumentIngestionRun.started_at >= start_date)
            if end_date:
                ingest_conditions.append(DocumentIngestionRun.started_at <= end_date)

            if user_id:
                ingest_sum_stmt = select(
                    func.sum(DocumentIngestionRun.llm_input_tokens).label("tot_inp"),
                    func.sum(DocumentIngestionRun.llm_output_tokens).label("tot_out"),
                    func.sum(DocumentIngestionRun.embedding_tokens).label("tot_emb"),
                    func.sum(DocumentIngestionRun.embedding_cost_usd).label("tot_emb_cost"),
                    func.count(DocumentIngestionRun.id).label("tot_runs"),
                ).select_from(DocumentIngestionRun).join(
                    KnowledgeBase, DocumentIngestionRun.document_id == KnowledgeBase.id
                ).where(KnowledgeBase.user_id == user_id, *ingest_conditions)
            else:
                ingest_sum_stmt = select(
                    func.sum(DocumentIngestionRun.llm_input_tokens).label("tot_inp"),
                    func.sum(DocumentIngestionRun.llm_output_tokens).label("tot_out"),
                    func.sum(DocumentIngestionRun.embedding_tokens).label("tot_emb"),
                    func.sum(DocumentIngestionRun.embedding_cost_usd).label("tot_emb_cost"),
                    func.count(DocumentIngestionRun.id).label("tot_runs"),
                ).where(*ingest_conditions)

            ingest_res = await self.db.execute(ingest_sum_stmt)
            i_row = ingest_res.first()
            if i_row:
                i_inp = int(i_row.tot_inp or 0)
                i_out = int(i_row.tot_out or 0)
                i_emb = int(i_row.tot_emb or 0)
                i_emb_cost = float(i_row.tot_emb_cost or 0.0)
                i_runs = int(i_row.tot_runs or 0)

                p_inp, p_out = get_model_pricing(settings.model_extraction)
                i_llm_cost = ((i_inp / 1_000_000.0) * p_inp) + ((i_out / 1_000_000.0) * p_out)

                tot_inp += i_inp
                tot_out += i_out
                tot_emb += i_emb
                tot_cost += (i_llm_cost + i_emb_cost)
                tot_queries += i_runs

        tot_tok = tot_inp + tot_out + tot_emb
        tot_cost = round(tot_cost, 6)

        summary = {
            "total_input_tokens": tot_inp,
            "total_output_tokens": tot_out,
            "total_embedding_tokens": tot_emb,
            "total_tokens": tot_tok,
            "total_cost_usd": tot_cost,
            "total_queries": tot_queries,
        }

        # 2. Breakdown By Model
        model_stmt = select(
            AnalyticsQueryLog.model_name,
            func.sum(AnalyticsQueryLog.llm_input_tokens).label("inp"),
            func.sum(AnalyticsQueryLog.llm_output_tokens).label("out"),
            func.sum(AnalyticsQueryLog.total_tokens).label("tok"),
            func.sum(AnalyticsQueryLog.total_cost_usd).label("cost"),
            func.count(AnalyticsQueryLog.id).label("cnt"),
        ).where(*conditions).group_by(AnalyticsQueryLog.model_name)
        model_res = await self.db.execute(model_stmt)

        catalog = get_configured_models_catalog()
        catalog_map = {item["model_name"]: item for item in catalog}

        active_models_map = {}
        for row in model_res.all():
            m_name = row.model_name or "default"
            m_inp = int(row.inp or 0)
            m_out = int(row.out or 0)
            m_tok = m_inp + m_out
            m_cost = round(float(row.cost or 0.0), 6)
            m_cnt = int(row.cnt or 0)

            cat_info = catalog_map.get(m_name, {})
            p_info = get_model_pricing(m_name)
            provider = cat_info.get("provider") or getattr(p_info, "provider", "deepinfra") or "deepinfra"

            purpose = cat_info.get("purpose")
            if not purpose:
                if "llama-3.3-70b" in m_name.lower():
                    purpose = "Conversational Answer Generation"
                elif "rerank" in m_name.lower():
                    purpose = "Document Chunk Reranking"
                elif "embed" in m_name.lower():
                    purpose = "Vector Embeddings"
                elif "deepseek-v4" in m_name.lower() or "llama-3-8b" in m_name.lower() or "deepseek" in m_name.lower():
                    purpose = "Entity & Triplet Extraction"
                elif "cypher" in m_name.lower() or "gpt-oss" in m_name.lower():
                    purpose = "Natural Language to Cypher"
                elif "gemma" in m_name.lower():
                    purpose = "User Intent Classification & Routing"
                else:
                    purpose = "General LLM Completion"

            model_type = cat_info.get("model_type", "primary")
            status = "active" if (m_tok > 0 or m_cnt > 0) else cat_info.get("default_status", "configured")

            active_models_map[m_name] = {
                "model_name": m_name,
                "input_tokens": m_inp,
                "output_tokens": m_out,
                "total_tokens": m_tok,
                "total_cost_usd": m_cost,
                "request_count": m_cnt,
                "purpose": purpose,
                "model_type": model_type,
                "status": status,
                "provider": provider,
                "pricing_status": p_info.pricing_status,
                "is_pricing_available": p_info.is_pricing_available,
                "pricing_notice": p_info.pricing_notice,
            }

        # Merge ingestion extraction models from DocumentIngestionRun
        if include_ingestion:
            if user_id:
                ingest_model_stmt = select(
                    DocumentIngestionRun.model_name,
                    func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
                    func.sum(DocumentIngestionRun.llm_output_tokens).label("out"),
                    func.sum(DocumentIngestionRun.embedding_tokens).label("emb"),
                    func.sum(DocumentIngestionRun.embedding_cost_usd).label("emb_cost"),
                    func.count(DocumentIngestionRun.id).label("cnt"),
                ).select_from(DocumentIngestionRun).join(
                    KnowledgeBase, DocumentIngestionRun.document_id == KnowledgeBase.id
                ).where(KnowledgeBase.user_id == user_id, *ingest_conditions).group_by(DocumentIngestionRun.model_name)
            else:
                ingest_model_stmt = select(
                    DocumentIngestionRun.model_name,
                    func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
                    func.sum(DocumentIngestionRun.llm_output_tokens).label("out"),
                    func.sum(DocumentIngestionRun.embedding_tokens).label("emb"),
                    func.sum(DocumentIngestionRun.embedding_cost_usd).label("emb_cost"),
                    func.count(DocumentIngestionRun.id).label("cnt"),
                ).where(*ingest_conditions).group_by(DocumentIngestionRun.model_name)

            ingest_model_res = await self.db.execute(ingest_model_stmt)
            for i_row in ingest_model_res.all():
                raw_m = i_row.model_name
                if not raw_m or raw_m in ("unknown", "deepseek-v3"):
                    m_name = settings.model_extraction
                else:
                    m_name = raw_m

                i_inp = int(i_row.inp or 0)
                i_out = int(i_row.out or 0)
                i_tok = i_inp + i_out
                i_cnt = int(i_row.cnt or 0)

                p_info = get_model_pricing(m_name)
                p_inp, p_out = p_info
                i_cost = round(((i_inp / 1_000_000.0) * p_inp) + ((i_out / 1_000_000.0) * p_out), 6)

                if m_name in active_models_map:
                    active_models_map[m_name]["input_tokens"] += i_inp
                    active_models_map[m_name]["output_tokens"] += i_out
                    active_models_map[m_name]["total_tokens"] += i_tok
                    active_models_map[m_name]["total_cost_usd"] = round(active_models_map[m_name]["total_cost_usd"] + i_cost, 6)
                    active_models_map[m_name]["request_count"] += i_cnt
                    if i_tok > 0 or i_cnt > 0:
                        active_models_map[m_name]["status"] = "active"
                else:
                    cat_info = catalog_map.get(m_name, {})
                    provider = cat_info.get("provider") or getattr(p_info, "provider", "deepinfra") or "deepinfra"
                    active_models_map[m_name] = {
                        "model_name": m_name,
                        "input_tokens": i_inp,
                        "output_tokens": i_out,
                        "total_tokens": i_tok,
                        "total_cost_usd": i_cost,
                        "request_count": i_cnt,
                        "purpose": cat_info.get("purpose", "Entity & Triplet Extraction"),
                        "model_type": cat_info.get("model_type", "primary"),
                        "status": "active" if (i_tok > 0 or i_cnt > 0) else cat_info.get("default_status", "configured"),
                        "provider": provider,
                        "pricing_status": p_info.pricing_status,
                        "is_pricing_available": p_info.is_pricing_available,
                        "pricing_notice": p_info.pricing_notice,
                    }

        # Also populate embedding model usage if embedding tokens were used (across chats and ingestion)
        embed_model_name = settings.model_embedding
        if (not model_name or model_name.strip() == embed_model_name) and tot_emb > 0:
            emb_p_info = get_model_pricing(embed_model_name)
            emb_unit_price = emb_p_info.input_price_per_1m if emb_p_info.input_price_per_1m is not None else 0.010
            embed_cost = round(float(tot_emb / 1_000_000.0 * emb_unit_price), 6)
            if embed_model_name in active_models_map:
                active_models_map[embed_model_name]["input_tokens"] += tot_emb
                active_models_map[embed_model_name]["total_tokens"] += tot_emb
                active_models_map[embed_model_name]["total_cost_usd"] = round(active_models_map[embed_model_name]["total_cost_usd"] + embed_cost, 6)
                active_models_map[embed_model_name]["status"] = "active"
            else:
                cat_info = catalog_map.get(embed_model_name, {})
                active_models_map[embed_model_name] = {
                    "model_name": embed_model_name,
                    "input_tokens": tot_emb,
                    "output_tokens": 0,
                    "total_tokens": tot_emb,
                    "total_cost_usd": embed_cost,
                    "request_count": tot_queries,
                    "purpose": cat_info.get("purpose", "Vector Embeddings (Document Chunks & Queries)"),
                    "model_type": cat_info.get("model_type", "primary"),
                    "status": "active",
                    "provider": cat_info.get("provider", "deepinfra"),
                    "pricing_status": emb_p_info.pricing_status,
                    "is_pricing_available": emb_p_info.is_pricing_available,
                    "pricing_notice": emb_p_info.pricing_notice,
                }

        # If a specific model_name filter was requested, only return that model
        if model_name and model_name.strip():
            filtered_name = model_name.strip()
            if filtered_name in active_models_map:
                by_model = [active_models_map[filtered_name]]
            elif filtered_name in catalog_map:
                cat_info = catalog_map[filtered_name]
                by_model = [{
                    "model_name": filtered_name,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "request_count": 0,
                    "purpose": cat_info.get("purpose"),
                    "model_type": cat_info.get("model_type", "primary"),
                    "status": cat_info.get("default_status", "configured"),
                    "provider": cat_info.get("provider", "deepinfra"),
                }]
            else:
                by_model = []
        else:
            # Full fleet overview: include active models and all configured catalog models
            by_model = list(active_models_map.values())
            for cat_item in catalog:
                c_name = cat_item["model_name"]
                if c_name not in active_models_map:
                    by_model.append({
                        "model_name": c_name,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                        "total_cost_usd": 0.0,
                        "request_count": 0,
                        "purpose": cat_item["purpose"],
                        "model_type": cat_item["model_type"],
                        "status": cat_item["default_status"],
                        "provider": cat_item["provider"],
                    })

        # 3. Breakdown By User
        user_costs = {}
        def get_user_entry(uid, email):
            if uid not in user_costs:
                user_costs[uid] = {
                    "user_id": uid,
                    "user_email": email or "unknown",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "embedding_tokens": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "request_count": 0,
                }
            return user_costs[uid]

        user_stmt = select(
            AnalyticsQueryLog.user_id,
            User.email.label("user_email"),
            func.sum(AnalyticsQueryLog.llm_input_tokens).label("inp"),
            func.sum(AnalyticsQueryLog.llm_output_tokens).label("out"),
            func.sum(AnalyticsQueryLog.embedding_tokens).label("emb"),
            func.sum(AnalyticsQueryLog.total_tokens).label("tok"),
            func.sum(AnalyticsQueryLog.total_cost_usd).label("cost"),
            func.count(AnalyticsQueryLog.id).label("cnt"),
        ).select_from(AnalyticsQueryLog).outerjoin(
            User, AnalyticsQueryLog.user_id == User.id
        ).where(*conditions).group_by(AnalyticsQueryLog.user_id, User.email)
        user_res = await self.db.execute(user_stmt)
        for row in user_res.all():
            entry = get_user_entry(row.user_id, row.user_email)
            u_inp = int(row.inp or 0)
            u_out = int(row.out or 0)
            u_emb = int(row.emb or 0)
            entry["input_tokens"] += u_inp
            entry["output_tokens"] += u_out
            entry["embedding_tokens"] += u_emb
            entry["total_tokens"] += (u_inp + u_out + u_emb)
            entry["total_cost_usd"] += float(row.cost or 0.0)
            entry["request_count"] += int(row.cnt or 0)

        if include_ingestion:
            ingest_user_stmt = select(
                User.id.label("user_id"),
                User.email.label("user_email"),
                func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
                func.sum(DocumentIngestionRun.llm_output_tokens).label("out"),
                func.sum(DocumentIngestionRun.embedding_tokens).label("emb"),
                func.sum(DocumentIngestionRun.embedding_cost_usd).label("emb_cost"),
                func.count(DocumentIngestionRun.id).label("cnt"),
            ).select_from(User).join(
                KnowledgeBase, KnowledgeBase.user_id == User.id
            ).join(
                DocumentIngestionRun, DocumentIngestionRun.document_id == KnowledgeBase.id
            )
            if self.tenant_id is not None:
                ingest_user_stmt = ingest_user_stmt.where(User.tenant_id == self.tenant_id)
            if start_date:
                ingest_user_stmt = ingest_user_stmt.where(DocumentIngestionRun.started_at >= start_date)
            if end_date:
                ingest_user_stmt = ingest_user_stmt.where(DocumentIngestionRun.started_at <= end_date)
            if user_id:
                ingest_user_stmt = ingest_user_stmt.where(User.id == user_id)
            ingest_user_stmt = ingest_user_stmt.group_by(User.id, User.email)
            
            ingest_user_res = await self.db.execute(ingest_user_stmt)
            p_inp, p_out = get_model_pricing(settings.model_extraction)
            for row in ingest_user_res.all():
                entry = get_user_entry(row.user_id, row.user_email)
                i_inp = int(row.inp or 0)
                i_out = int(row.out or 0)
                i_emb = int(row.emb or 0)
                i_emb_cost = float(row.emb_cost or 0.0)
                i_llm_cost = ((i_inp / 1_000_000.0) * p_inp) + ((i_out / 1_000_000.0) * p_out)
                
                entry["input_tokens"] += i_inp
                entry["output_tokens"] += i_out
                entry["embedding_tokens"] += i_emb
                entry["total_tokens"] += (i_inp + i_out + i_emb)
                entry["total_cost_usd"] += (i_llm_cost + i_emb_cost)
                entry["request_count"] += int(row.cnt or 0)

        for entry in user_costs.values():
            entry["total_cost_usd"] = round(entry["total_cost_usd"], 6)

        by_user = list(user_costs.values())

        # 4. Daily Trends
        daily_stmt = select(
            func.to_char(AnalyticsQueryLog.created_at, 'YYYY-MM-DD').label("date"),
            func.sum(AnalyticsQueryLog.llm_input_tokens).label("inp"),
            func.sum(AnalyticsQueryLog.llm_output_tokens).label("out"),
            func.sum(AnalyticsQueryLog.embedding_tokens).label("emb"),
            func.sum(AnalyticsQueryLog.total_tokens).label("tok"),
            func.sum(AnalyticsQueryLog.total_cost_usd).label("cost"),
            func.count(AnalyticsQueryLog.id).label("cnt"),
        ).where(*conditions).group_by("date").order_by("date").limit(60)
        daily_res = await self.db.execute(daily_stmt)
        daily_map = {}
        for row in daily_res.all():
            d_inp = int(row.inp or 0)
            d_out = int(row.out or 0)
            d_emb = int(row.emb or 0)
            d_tok = d_inp + d_out + d_emb
            daily_map[row.date] = {
                "date": row.date,
                "input_tokens": d_inp,
                "output_tokens": d_out,
                "embedding_tokens": d_emb,
                "total_tokens": d_tok,
                "total_cost_usd": float(row.cost or 0.0),
                "query_count": int(row.cnt or 0),
            }

        if include_ingestion:
            if user_id:
                daily_ingest_stmt = select(
                    func.to_char(DocumentIngestionRun.started_at, 'YYYY-MM-DD').label("date"),
                    func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
                    func.sum(DocumentIngestionRun.llm_output_tokens).label("out"),
                    func.sum(DocumentIngestionRun.embedding_tokens).label("emb"),
                    func.sum(DocumentIngestionRun.embedding_cost_usd).label("emb_cost"),
                    func.count(DocumentIngestionRun.id).label("cnt"),
                ).select_from(DocumentIngestionRun).join(
                    KnowledgeBase, DocumentIngestionRun.document_id == KnowledgeBase.id
                ).where(KnowledgeBase.user_id == user_id, *ingest_conditions).group_by("date").order_by("date").limit(60)
            else:
                daily_ingest_stmt = select(
                    func.to_char(DocumentIngestionRun.started_at, 'YYYY-MM-DD').label("date"),
                    func.sum(DocumentIngestionRun.llm_input_tokens).label("inp"),
                    func.sum(DocumentIngestionRun.llm_output_tokens).label("out"),
                    func.sum(DocumentIngestionRun.embedding_tokens).label("emb"),
                    func.sum(DocumentIngestionRun.embedding_cost_usd).label("emb_cost"),
                    func.count(DocumentIngestionRun.id).label("cnt"),
                ).where(*ingest_conditions).group_by("date").order_by("date").limit(60)

            daily_ingest_res = await self.db.execute(daily_ingest_stmt)
            p_inp, p_out = get_model_pricing(settings.model_extraction)
            for row in daily_ingest_res.all():
                d_date = row.date
                i_inp = int(row.inp or 0)
                i_out = int(row.out or 0)
                i_emb = int(row.emb or 0)
                i_emb_cost = float(row.emb_cost or 0.0)
                i_llm_cost = ((i_inp / 1_000_000.0) * p_inp) + ((i_out / 1_000_000.0) * p_out)
                
                if d_date not in daily_map:
                    daily_map[d_date] = {
                        "date": d_date,
                        "input_tokens": i_inp,
                        "output_tokens": i_out,
                        "embedding_tokens": i_emb,
                        "total_tokens": i_inp + i_out + i_emb,
                        "total_cost_usd": i_llm_cost + i_emb_cost,
                        "query_count": int(row.cnt or 0),
                    }
                else:
                    d_entry = daily_map[d_date]
                    d_entry["input_tokens"] += i_inp
                    d_entry["output_tokens"] += i_out
                    d_entry["embedding_tokens"] += i_emb
                    d_entry["total_tokens"] += (i_inp + i_out + i_emb)
                    d_entry["total_cost_usd"] += (i_llm_cost + i_emb_cost)
                    d_entry["query_count"] += int(row.cnt or 0)

        for d_entry in daily_map.values():
            d_entry["total_cost_usd"] = round(d_entry["total_cost_usd"], 6)

        daily_trends = sorted(list(daily_map.values()), key=lambda x: x["date"], reverse=True)[:60]

        # 5. Paginated Detailed Query Records (Optional for fast response)
        records = []
        if include_records:
            offset = max(0, (page - 1) * limit)
            records_stmt = select(AnalyticsQueryLog).where(
                *conditions
            ).order_by(AnalyticsQueryLog.created_at.desc()).offset(offset).limit(limit)
            records_res = await self.db.execute(records_stmt)
            records_objs = records_res.scalars().all()

            records = [
                {
                    "id": rec.id,
                    "tenant_id": rec.tenant_id,
                    "user_id": rec.user_id,
                    "session_id": rec.session_id,
                    "request_id": rec.request_id,
                    "model_name": rec.model_name,
                    "query": rec.query,
                    "response_status": rec.response_status.value if hasattr(rec.response_status, "value") else str(rec.response_status),
                    "latency_ms": rec.latency_ms,
                    "llm_input_tokens": rec.llm_input_tokens,
                    "llm_output_tokens": rec.llm_output_tokens,
                    "embedding_tokens": rec.embedding_tokens,
                    "total_tokens": rec.total_tokens or (rec.llm_input_tokens + rec.llm_output_tokens + rec.embedding_tokens),
                    "llm_cost_usd": rec.llm_cost_usd,
                    "embedding_cost_usd": rec.embedding_cost_usd,
                    "total_cost_usd": rec.total_cost_usd,
                    "created_at": rec.created_at,
                }
                for rec in records_objs
            ]

        return {
            "summary": summary,
            "by_model": by_model,
            "by_user": by_user,
            "daily_trends": daily_trends,
            "records": records,
            "total_records": tot_queries,
            "page": page,
            "limit": limit,
        }
