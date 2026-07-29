"""
Analytics Service - Domain logic and statistical computation.
"""

from typing import List, Optional
from uuid import UUID
from .repository import AnalyticsRepository
from .schemas import (
    AnalyticsSummaryCreate, 
    AnalyticsSummaryUpdate, 
    AnalyticsQueryLogCreate,
    DashboardMetrics,
    OperationalDashboardResponse,
    OperationalTrendResponse,
    CostGovernanceResponse,
    CapacityGovernanceResponse,
    CapacityProjection
)
from .models import AnalyticsSummary, AnalyticsQueryLog
from app.core.llm.deepinfra_llm import PRICE_PER_1M_INPUT_TOKENS, PRICE_PER_1M_OUTPUT_TOKENS

class AnalyticsService:
    def __init__(self, repository: AnalyticsRepository):
        self.repo = repository

    async def create_summary(self, data: AnalyticsSummaryCreate) -> AnalyticsSummary:
        summary_dict = data.model_dump()
        
        # Recalculate accuracy to ensure integrity
        if summary_dict["total_queries"] > 0:
            summary_dict["accuracy_score"] = (summary_dict["answered_queries"] / summary_dict["total_queries"]) * 100
        else:
            summary_dict["accuracy_score"] = 0.0

        return await self.repo.create_summary(summary_dict)

    async def get_dashboard_metrics(self) -> DashboardMetrics:
        # Aggregated stats
        stats = await self.repo.get_aggregated_metrics()
        
        # Trends
        trends_raw = await self.repo.get_query_trends()
        trend_list = [{"date": t[0], "count": t[1]} for t in trends_raw]
        
        # Calculate accuracy across all
        accuracy = 0.0
        if stats["total_queries"] > 0:
            accuracy = (stats["answered_queries"] / stats["total_queries"]) * 100

        # Real distribution from logs
        distribution = await self.repo.get_confidence_distribution()

        return DashboardMetrics(
            total_queries=stats["total_queries"],
            accuracy_percent=round(accuracy, 2),
            unanswered_count=stats["unanswered_queries"],
            avg_confidence=round(stats["avg_confidence"], 4),
            trend_queries=trend_list,
            confidence_distribution=distribution
        )

    async def log_query(self, data: AnalyticsQueryLogCreate) -> AnalyticsQueryLog:
        return await self.repo.create_query_log(data.model_dump())

    async def get_all_summaries(self, skip: int = 0, limit: int = 100) -> List[AnalyticsSummary]:
        return await self.repo.get_all_summaries(skip, limit)

    async def get_summary(self, summary_id: UUID) -> Optional[AnalyticsSummary]:
        return await self.repo.get_summary_by_id(summary_id)

    async def update_summary(self, summary_id: UUID, data: AnalyticsSummaryUpdate) -> Optional[AnalyticsSummary]:
        return await self.repo.update_summary(summary_id, data.model_dump(exclude_unset=True))

    async def delete_summary(self, summary_id: UUID) -> bool:
        return await self.repo.delete_summary(summary_id)
        
    async def get_unanswered_logs(self) -> List[AnalyticsQueryLog]:
        return await self.repo.get_unanswered_logs()

    # ================= OPERATIONAL ANALYTICS =================
    
    async def get_operational_dashboard(self) -> OperationalDashboardResponse:
        metrics = await self.repo.get_operational_dashboard_metrics()
        
        # Calculate Health
        system_health = "HEALTHY"
        if metrics["failures"] > 0 or metrics["repair_rate"] > 0.20 or metrics["fallbacks"] > 0:
            system_health = "DEGRADED"
        if metrics["failures"] > metrics["documents_processed"] * 0.1: # 10% failure rate
            system_health = "CRITICAL"
            
        metrics["system_health"] = system_health
        return OperationalDashboardResponse(**metrics)

    async def get_operational_trends(self) -> OperationalTrendResponse:
        trends = await self.repo.get_operational_trends()
        return OperationalTrendResponse(trends=trends)

    # ================= COST GOVERNANCE =================

    async def get_cost_governance(
        self,
        user_id: Optional[UUID] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> CostGovernanceResponse:
        from datetime import datetime as dt_parser
        parsed_start = None
        parsed_end = None
        if start_date:
            try:
                parsed_start = dt_parser.fromisoformat(start_date.replace("Z", "+00:00"))
            except ValueError:
                parsed_start = dt_parser.strptime(start_date, "%Y-%m-%d")
        if end_date:
            try:
                parsed_end = dt_parser.fromisoformat(end_date.replace("Z", "+00:00"))
            except ValueError:
                parsed_end = dt_parser.strptime(end_date, "%Y-%m-%d")

        data = await self.repo.get_cost_governance_data(user_id, parsed_start, parsed_end)
        
        # DeepInfra LLM pricing constants
        inp_price_per_m = PRICE_PER_1M_INPUT_TOKENS
        out_price_per_m = PRICE_PER_1M_OUTPUT_TOKENS
        
        total_inp = sum(d["input_tokens"] for d in data["daily_tokens"])
        total_out = sum(d["output_tokens"] for d in data["daily_tokens"])
        total_emb = sum(d.get("embedding_tokens", 0) for d in data["daily_tokens"])
        total_emb_cost = sum(d.get("embedding_cost_usd", 0.0) for d in data["daily_tokens"])
        
        total_tokens = total_inp + total_out + total_emb
        total_cost = (total_inp / 1_000_000 * inp_price_per_m) + \
                     (total_out / 1_000_000 * out_price_per_m) + \
                     total_emb_cost
        
        category_breakdown = []
        for cat in data["categories"]:
            cat_inp = cat["input_tokens"]
            cat_out = cat["output_tokens"]
            cat_emb = cat.get("embedding_tokens", 0)
            cat_emb_cost = cat.get("embedding_cost_usd", 0.0)
            
            cat_cost = (cat_inp / 1_000_000 * inp_price_per_m) + \
                       (cat_out / 1_000_000 * out_price_per_m) + \
                       cat_emb_cost
            category_breakdown.append({
                "document_category": cat["document_category"],
                "total_tokens": cat_inp + cat_out + cat_emb,
                "estimated_cost_usd": round(cat_cost, 4)
            })
            
        daily_tokens = []
        for d in data["daily_tokens"]:
            daily_tokens.append({
                "date": d["date"],
                "input_tokens": d["input_tokens"],
                "output_tokens": d["output_tokens"]
            })
            
        return CostGovernanceResponse(
            total_tokens_30d=total_tokens,
            total_cost_usd_30d=round(total_cost, 4),
            total_tokens=total_tokens,
            total_cost_usd=round(total_cost, 4),
            category_breakdown=category_breakdown,
            daily_tokens=daily_tokens
        )

    async def get_user_cost_governance(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[dict]:
        from datetime import datetime as dt_parser
        parsed_start = None
        parsed_end = None
        if start_date:
            try:
                parsed_start = dt_parser.fromisoformat(start_date.replace("Z", "+00:00"))
            except ValueError:
                parsed_start = dt_parser.strptime(start_date, "%Y-%m-%d")
        if end_date:
            try:
                parsed_end = dt_parser.fromisoformat(end_date.replace("Z", "+00:00"))
            except ValueError:
                parsed_end = dt_parser.strptime(end_date, "%Y-%m-%d")

        return await self.repo.get_user_cost_governance(parsed_start, parsed_end)

    # ================= CAPACITY PLANNING =================

    async def get_capacity_governance(self) -> CapacityGovernanceResponse:
        metrics = await self.repo.get_operational_dashboard_metrics()
        cap_data = await self.repo.get_capacity_planning_data()
        
        daily_stats = cap_data["daily_stats"]
        num_days = len(daily_stats)
        
        if num_days > 0:
            avg_chunks_per_day = sum(d["chunks"] for d in daily_stats) / num_days
            avg_docs_per_day = sum(d["docs"] for d in daily_stats) / num_days
        else:
            avg_chunks_per_day = 0
            avg_docs_per_day = 0
            
        # Simple Linear Growth Projection (Assuming 15% month-over-month growth for enterprise SaaS)
        # Using a static multiplier since we only have up to 30 days of data
        monthly_growth_rate = 1.15 
        projected_30d = avg_chunks_per_day * monthly_growth_rate
        projected_90d = avg_chunks_per_day * (monthly_growth_rate ** 3)
        
        return CapacityGovernanceResponse(
            projection=CapacityProjection(
                current_daily_chunks=round(avg_chunks_per_day, 2),
                projected_30d_daily_chunks=round(projected_30d, 2),
                projected_90d_daily_chunks=round(projected_90d, 2),
                avg_latency_ms=metrics["avg_latency_ms"],
                p95_latency_ms=metrics["p95_latency_ms"],
                documents_per_day=round(avg_docs_per_day, 2)
            )
        )
