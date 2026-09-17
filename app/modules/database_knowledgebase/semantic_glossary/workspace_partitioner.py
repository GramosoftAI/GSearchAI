"""Domain Workspace Partitioner

Clusters canonical database tables into domain workspaces strictly using
foreign key graph topology (connected components and hub entity centrality).
Enforces the core GraphMind architectural invariant: ZERO hardcoded domain-specific
heuristics or vocabulary (no 'if HRMS:', 'if employee:', etc.). Works identically
across HRMS, Hospital, CRM, Finance, and Supply Chain schemas.
"""

import logging
import uuid
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..models.concept_glossary import ConceptGlossary, SchemaWorkspace
from ..schemas.canonical import DatabaseSchema, TableSchema
from .canonicality import is_canonical_table

logger = logging.getLogger(__name__)


class WorkspacePartitioner:
    """
    Partitions a database schema into domain workspaces based strictly on
    foreign key graph topology (connected components and hub entities).
    """

    @classmethod
    def _extract_canonical_adjacency(
        cls,
        schema: DatabaseSchema,
        canonical_tables: Dict[str, TableSchema],
    ) -> Tuple[Dict[str, Set[str]], Dict[str, int]]:
        """
        Builds undirected adjacency list and degree map for canonical tables
        based strictly on foreign key relationships.
        """
        adj: Dict[str, Set[str]] = {t_name: set() for t_name in canonical_tables}
        degrees: Dict[str, int] = {t_name: 0 for t_name in canonical_tables}

        # Normalize canonical names
        canon_set = set(canonical_tables.keys())

        for table in canonical_tables.values():
            src_name = table.table_name

            # Check explicit foreign keys
            for fk in table.foreign_keys:
                tgt_name = fk.referred_table
                if tgt_name in canon_set and tgt_name != src_name:
                    adj[src_name].add(tgt_name)
                    adj[tgt_name].add(src_name)
                    degrees[src_name] += 1
                    degrees[tgt_name] += 1

            # Check declared relationships if present
            for rel in table.relationships:
                tgt_name = rel.target_table
                if tgt_name in canon_set and tgt_name != src_name:
                    adj[src_name].add(tgt_name)
                    adj[tgt_name].add(src_name)
                    degrees[src_name] += 1
                    degrees[tgt_name] += 1

        return adj, degrees

    @classmethod
    def _derive_workspace_display_label(
        cls,
        component_tables: List[str],
        degrees: Dict[str, int],
    ) -> str:
        """
        Derives a human-readable display label for a cluster of connected tables.
        Uses the highest-degree hub entity in the cluster, or a shared common prefix.
        Purely a display label heuristic; NOT load-bearing for cluster membership.
        """
        if not component_tables:
            return "general"

        if len(component_tables) == 1:
            # Single isolated table
            t = component_tables[0]
            # Strip common table prefixes like tbl_ or base_ if present
            for pfx in ("tbl_", "base_", "dim_", "fact_", "ref_"):
                if t.startswith(pfx) and len(t) > len(pfx):
                    return t[len(pfx):]
            return t

        # Find the hub entity: table with maximum foreign key connections
        hub_table = max(component_tables, key=lambda t: (degrees.get(t, 0), -len(t)))

        # Check if all or most tables in this cluster share a common lexical prefix before '_'
        prefixes = [t.split("_")[0] for t in component_tables if "_" in t]
        if prefixes:
            prefix_counts = defaultdict(int)
            for p in prefixes:
                # Ignore generic prefix words
                if p not in ("tbl", "base", "dim", "fact", "ref", "auth", "django"):
                    prefix_counts[p] += 1
            if prefix_counts:
                most_common_pfx, count = max(prefix_counts.items(), key=lambda x: x[1])
                if count >= len(component_tables) * 0.5:
                    return most_common_pfx

        # Fallback to hub table name stripped of common technical prefixes
        hub_clean = hub_table
        for pfx in ("tbl_", "base_", "dim_", "fact_", "ref_"):
            if hub_clean.startswith(pfx) and len(hub_clean) > len(pfx):
                hub_clean = hub_clean[len(pfx):]
                break

        return hub_clean

    @classmethod
    def partition_workspaces(
        cls,
        schema: DatabaseSchema,
        tenant_id: str | uuid.UUID,
        fingerprint: Optional[str] = None,
        canonical_overrides: Optional[Dict[str, bool]] = None,
    ) -> List[SchemaWorkspace]:
        """
        Partitions canonical tables into domain workspaces using FK graph connected components.
        Agnostic to schema domain (HRMS, Hospital, CRM, Finance, etc.).
        """
        t_id_str = str(tenant_id)
        fp_str = fingerprint or schema.fingerprint

        # 1. Filter to canonical tables
        canonical_tables = {
            t.table_name: t for t in schema.all_tables
            if is_canonical_table(t, canonical_overrides=canonical_overrides)
        }

        if not canonical_tables:
            return []

        # 2. Build FK graph adjacency and degree counts
        adj, degrees = cls._extract_canonical_adjacency(schema, canonical_tables)

        # 3. Find connected components via BFS
        visited: Set[str] = set()
        components: List[List[str]] = []

        for t_name in sorted(canonical_tables.keys()):
            if t_name in visited:
                continue

            component: List[str] = []
            queue = deque([t_name])
            visited.add(t_name)

            while queue:
                curr = queue.popleft()
                component.append(curr)

                for neighbor in sorted(adj.get(curr, set())):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            components.append(component)

        # 4. Generate SchemaWorkspace mapping records
        workspace_records: List[SchemaWorkspace] = []
        used_workspace_names: Set[str] = set()

        for component in components:
            ws_label = cls._derive_workspace_display_label(component, degrees)
            
            # Ensure unique workspace names if collision occurs
            final_ws_name = ws_label
            counter = 1
            while final_ws_name in used_workspace_names:
                counter += 1
                final_ws_name = f"{ws_label}_{counter}"
            used_workspace_names.add(final_ws_name)

            for t_name in component:
                ws_entry = SchemaWorkspace(
                    tenant_id=t_id_str,
                    workspace_name=final_ws_name,
                    table_name=t_name,
                    schema_fingerprint=fp_str,
                )
                workspace_records.append(ws_entry)

        logger.info(
            f"Partitioned {len(canonical_tables)} canonical tables into "
            f"{len(components)} domain workspaces for tenant {tenant_id}"
        )
        return workspace_records

    @classmethod
    async def persist_workspaces_async(
        cls,
        session: AsyncSession,
        workspaces: List[SchemaWorkspace],
    ) -> List[SchemaWorkspace]:
        """
        Persists workspaces idempotently to avoid unique constraint violations on retry.
        """
        if not workspaces:
            return []

        t_id = workspaces[0].tenant_id
        fp = workspaces[0].schema_fingerprint

        stmt = select(SchemaWorkspace).where(
            and_(
                SchemaWorkspace.tenant_id == t_id,
                SchemaWorkspace.schema_fingerprint == fp,
            )
        )
        existing_res = await session.execute(stmt)
        existing_map = {row.table_name: row for row in existing_res.scalars().all()}

        persisted: List[SchemaWorkspace] = []
        for ws in workspaces:
            if ws.table_name in existing_map:
                existing_row = existing_map[ws.table_name]
                existing_row.workspace_name = ws.workspace_name
                persisted.append(existing_row)
            else:
                session.add(ws)
                persisted.append(ws)

        await session.flush()
        return persisted

    @classmethod
    def route_query_to_workspace(
        cls,
        query: str,
        workspaces: List[SchemaWorkspace],
        published_glossary: Optional[List[ConceptGlossary]] = None,
    ) -> Optional[str]:
        """
        Determines if a natural language query targets a specific single domain workspace.
        
        CRITICAL ARCHITECTURAL GUARANTEE:
        If a query is cross-domain (e.g. 'average salary by attendance pattern') or ambiguous,
        returns None so retrieval falls back to the full canonical schema pool,
        rather than silently scoping to an incomplete single domain.
        """
        if not workspaces or not query:
            return None

        q_clean = query.lower()
        q_tokens = set(q_clean.split())

        # Group tables by workspace
        ws_tables: Dict[str, Set[str]] = defaultdict(set)
        for ws in workspaces:
            ws_tables[ws.workspace_name].add(ws.table_name.lower())

        # Map published synonyms and column names to workspace
        ws_terms: Dict[str, Set[str]] = defaultdict(set)
        for ws_name, tables in ws_tables.items():
            for t in tables:
                # Add table name and parts
                ws_terms[ws_name].add(t)
                for part in t.split("_"):
                    if len(part) >= 3:
                        ws_terms[ws_name].add(part)

        if published_glossary:
            # Map table -> workspace
            tbl_to_ws = {ws.table_name.lower(): ws.workspace_name for ws in workspaces}
            for entry in published_glossary:
                if not getattr(entry, "is_published", False):
                    continue
                t_lower = entry.table_name.lower()
                ws_name = tbl_to_ws.get(t_lower)
                if ws_name:
                    if entry.synonyms:
                        for s in entry.synonyms:
                            s_clean = s.lower().strip()
                            ws_terms[ws_name].add(s_clean)
                            for s_tok in s_clean.split():
                                if len(s_tok) >= 3:
                                    ws_terms[ws_name].add(s_tok)

        # Score matching workspaces
        matched_workspaces: Set[str] = set()
        for ws_name, terms in ws_terms.items():
            # Check workspace name itself
            if ws_name.lower() in q_clean:
                matched_workspaces.add(ws_name)
                continue

            # Check term overlap
            matching_terms = [term for term in terms if term in q_clean or term in q_tokens]
            if len(matching_terms) >= 2:
                matched_workspaces.add(ws_name)
            elif len(matching_terms) == 1 and len(matching_terms[0]) >= 5:
                matched_workspaces.add(ws_name)

        # Cross-domain query: spans 2 or more distinct workspaces -> return None (fallback to full candidate pool)
        if len(matched_workspaces) > 1:
            logger.info(
                f"Query '{query[:50]}' touches multiple workspaces {matched_workspaces}. "
                "Falling back to full canonical schema pool."
            )
            return None

        # Single unambiguous workspace
        if len(matched_workspaces) == 1:
            return next(iter(matched_workspaces))

        # No specific workspace matched -> return None (fallback to full pool)
        return None


# Alias for backward-compatibility and clean domain naming
DomainWorkspacePartitioner = WorkspacePartitioner

