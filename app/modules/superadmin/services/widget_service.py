"""SuperAdmin Dashboard Widgets CRUD Service.

Allows platform owners to create, customize, reorder, and manage
operational widgets and pinned metric cards on the SuperAdmin interface.
"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
import logging

from ..models import SuperAdminDashboardWidget, SuperAdminUser
from ..schemas import SuperAdminDashboardWidgetCreate, SuperAdminDashboardWidgetUpdate

logger = logging.getLogger(__name__)


# Default starter widgets to seed if table is empty
DEFAULT_WIDGETS = [
    {
        "name": "Organizations Overview",
        "widget_type": "METRIC_CARD",
        "metric_key": "organizations",
        "title": "Total Organizations",
        "description": "Total registered, active, and suspended customer tenants",
        "layout_row": 0,
        "layout_col": 0,
        "layout_width": 1,
        "layout_height": 1,
        "config": {"color": "#3B82F6", "icon": "BuildingOfficeIcon"},
    },
    {
        "name": "Users Directory Summary",
        "widget_type": "METRIC_CARD",
        "metric_key": "users",
        "title": "Total Platform Users",
        "description": "Active users, admins, and recent registrations",
        "layout_row": 0,
        "layout_col": 1,
        "layout_width": 1,
        "layout_height": 1,
        "config": {"color": "#10B981", "icon": "UsersIcon"},
    },
    {
        "name": "AI Agents Fleet",
        "widget_type": "METRIC_CARD",
        "metric_key": "agents",
        "title": "AI Agents Fleet",
        "description": "Platform-wide native and integrated agent instances",
        "layout_row": 0,
        "layout_col": 2,
        "layout_width": 1,
        "layout_height": 1,
        "config": {"color": "#8B5CF6", "icon": "CpuChipIcon"},
    },
    {
        "name": "Knowledge Bases & RAG",
        "widget_type": "METRIC_CARD",
        "metric_key": "knowledge_bases",
        "title": "Knowledge Bases & Chunks",
        "description": "Document and Database KBs with indexed vector chunk counts",
        "layout_row": 0,
        "layout_col": 3,
        "layout_width": 1,
        "layout_height": 1,
        "config": {"color": "#F59E0B", "icon": "CircleStackIcon"},
    },
    {
        "name": "API Request Volume & Accuracy",
        "widget_type": "CHART",
        "metric_key": "api_statistics",
        "title": "Platform API Traffic & Accuracy",
        "description": "Total queries, error rates, token throughput, and cost in USD",
        "layout_row": 1,
        "layout_col": 0,
        "layout_width": 2,
        "layout_height": 2,
        "config": {"chart_type": "area", "show_legend": True},
    },
    {
        "name": "Infrastructure & Service Health",
        "widget_type": "HEALTH",
        "metric_key": "system_health",
        "title": "System Health & Core Services",
        "description": "Real-time availability of Postgres, Neo4j, Redis, and Embedding engines",
        "layout_row": 1,
        "layout_col": 2,
        "layout_width": 2,
        "layout_height": 2,
        "config": {"refresh_interval_sec": 30},
    },
]


class WidgetService:
    """Service providing full CRUD management for dashboard widgets."""

    @staticmethod
    async def list_widgets(
        db: AsyncSession,
        only_visible: bool = False,
    ) -> List[SuperAdminDashboardWidget]:
        """List all dashboard widgets, automatically seeding default widgets if table is empty."""
        query = select(SuperAdminDashboardWidget)
        if only_visible:
            query = query.where(SuperAdminDashboardWidget.is_visible == True)
        query = query.order_by(
            SuperAdminDashboardWidget.layout_row.asc(),
            SuperAdminDashboardWidget.layout_col.asc(),
            SuperAdminDashboardWidget.created_at.asc()
        )

        result = await db.execute(query)
        widgets = result.scalars().all()

        if not widgets:
            # Seed default widgets for convenient out-of-the-box experience
            logger.info("No dashboard widgets found. Seeding standard SuperAdmin widgets...")
            seeded: List[SuperAdminDashboardWidget] = []
            for item in DEFAULT_WIDGETS:
                w = SuperAdminDashboardWidget(
                    name=item["name"],
                    widget_type=item["widget_type"],
                    metric_key=item["metric_key"],
                    title=item["title"],
                    description=item["description"],
                    layout_row=item["layout_row"],
                    layout_col=item["layout_col"],
                    layout_width=item["layout_width"],
                    layout_height=item["layout_height"],
                    is_visible=True,
                    config=item["config"],
                )
                db.add(w)
                seeded.append(w)
            await db.commit()
            for w in seeded:
                await db.refresh(w)
            return seeded

        return list(widgets)

    @staticmethod
    async def get_widget(db: AsyncSession, widget_id: UUID) -> SuperAdminDashboardWidget:
        """Fetch widget by UUID."""
        query = select(SuperAdminDashboardWidget).where(SuperAdminDashboardWidget.id == widget_id)
        result = await db.execute(query)
        widget = result.scalar_one_or_none()
        if not widget:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dashboard widget with ID {widget_id} not found",
            )
        return widget

    @staticmethod
    async def create_widget(
        db: AsyncSession,
        data: SuperAdminDashboardWidgetCreate,
        creator: Optional[SuperAdminUser] = None,
    ) -> SuperAdminDashboardWidget:
        """Create a new custom dashboard widget."""
        widget = SuperAdminDashboardWidget(
            name=data.name,
            widget_type=data.widget_type,
            metric_key=data.metric_key,
            title=data.title,
            description=data.description,
            layout_row=data.layout_row,
            layout_col=data.layout_col,
            layout_width=data.layout_width,
            layout_height=data.layout_height,
            is_visible=data.is_visible,
            config=data.config or {},
            created_by_admin_id=creator.id if creator else None,
        )
        db.add(widget)
        await db.commit()
        await db.refresh(widget)
        return widget

    @staticmethod
    async def update_widget(
        db: AsyncSession,
        widget_id: UUID,
        data: SuperAdminDashboardWidgetUpdate,
    ) -> SuperAdminDashboardWidget:
        """Update properties of an existing dashboard widget."""
        widget = await WidgetService.get_widget(db, widget_id)
        update_dict = data.dict(exclude_unset=True)

        for field, value in update_dict.items():
            setattr(widget, field, value)

        db.add(widget)
        await db.commit()
        await db.refresh(widget)
        return widget

    @staticmethod
    async def delete_widget(db: AsyncSession, widget_id: UUID) -> None:
        """Delete a dashboard widget."""
        widget = await WidgetService.get_widget(db, widget_id)
        await db.delete(widget)
        await db.commit()

