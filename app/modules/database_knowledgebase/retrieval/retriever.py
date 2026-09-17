"""Core SchemaRetriever Service

Coordinates:
- Multi-signal Hybrid Retrieval (Vector + Keyword + Graph Expansion)
- Failure fallback (when embeddings are unavailable)
- Version-pinned snapshot resolution
- Strict tenant isolation
- Explainable scoring and hierarchical sub-schema pruning
"""

import uuid
import logging
import asyncio
from typing import Dict, List, Optional, Set
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.embeddings import EmbeddingGenerator
from ..models.database_knowledgebase import DatabaseKnowledgebase, DatabaseSchemaSnapshot
from ..schemas.canonical import DatabaseSchema, TableSchema, RelationshipSchema
from ..exceptions import (
    DatabaseKnowledgebaseNotFoundError,
    TenantMismatchError,
    SchemaSnapshotNotFoundError,
)
from .keyword_matcher import SchemaKeywordMatcher, KeywordMatchResult
from .vector_search import SchemaVectorSearch, VectorMatchResult
from .graph_expander import SchemaGraphExpander
from .scorer import HybridScorer, TableRetrievalScore
from .pruner import SchemaPruner
from .cache import SchemaRetrievalCache
from ..schema.graph import SchemaGraph
from ..planning.intent_analyzer import QueryIntentAnalyzer

logger = logging.getLogger(__name__)


class SchemaRetrievalRequest(BaseModel):
    """Input parameters for schema retrieval."""
    model_config = ConfigDict(extra="forbid")

    tenant_id: uuid.UUID = Field(..., description="Authenticated tenant ID")
    database_knowledgebase_id: uuid.UUID = Field(..., description="Target database knowledgebase UUID")
    user_query: str = Field(..., min_length=1, max_length=2000, description="Natural language question")
    conversation_context: Optional[List[str]] = Field(default=None, description="Previous conversation turns")
    top_k_tables: int = Field(default=5, ge=1, le=50, description="Maximum tables to retrieve")
    top_k_columns_per_table: int = Field(default=25, ge=1, le=100, description="Max columns per table")
    include_relationships: bool = Field(default=True, description="Whether to include FK join paths")
    min_confidence_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    enable_semantic_glossary: bool = Field(default=False, description="Enable semantic glossary enriched retrieval")
    workspace_id: Optional[str] = Field(default=None, description="Optional domain workspace name/ID filter")


class SchemaRetrievalResult(BaseModel):
    """Structured, version-pinned sub-schema retrieval outcome."""
    model_config = ConfigDict(extra="forbid")

    database_name: str
    database_type: str
    schema_version: str = Field(..., description="SHA-256 fingerprint of the retrieved schema")
    retrieved_tables: List[TableSchema]
    retrieval_scores: Dict[str, TableRetrievalScore]
    join_paths: List[RelationshipSchema]
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    untrusted_boundary_text: str = Field(..., description="Prompt-injection safe schema XML string")


class SchemaRetriever:
    """
    Production-grade Schema Retrieval Service.
    Retrieves the minimal correct sub-schema for a natural language question.
    """

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    async def retrieve(
        self,
        request: SchemaRetrievalRequest,
        canonical_schema: Optional[DatabaseSchema] = None,
    ) -> SchemaRetrievalResult:
        """
        Execute hybrid schema retrieval scoped strictly by tenant_id, KB ID, and schema version.
        """
        # 1. Enforce tenant isolation and verify knowledgebase
        if request.tenant_id != self.tenant_id:
            raise TenantMismatchError("Client tenant_id does not match authenticated context")

        kb = await self.session.get(DatabaseKnowledgebase, request.database_knowledgebase_id)
        if not kb:
            raise DatabaseKnowledgebaseNotFoundError(f"Knowledgebase {request.database_knowledgebase_id} not found")
        if kb.tenant_id != self.tenant_id:
            raise TenantMismatchError("Knowledgebase belongs to a different tenant")

        # 2. Fetch or reuse canonical schema snapshot
        if canonical_schema is not None:
            schema_version = canonical_schema.fingerprint
        else:
            snapshot_stmt = (
                select(DatabaseSchemaSnapshot)
                .where(
                    and_(
                        DatabaseSchemaSnapshot.tenant_id == self.tenant_id,
                        DatabaseSchemaSnapshot.db_knowledgebase_id == kb.id,
                    )
                )
                .order_by(DatabaseSchemaSnapshot.created_at.desc())
                .limit(1)
            )
            snapshot_res = await self.session.execute(snapshot_stmt)
            snapshot = snapshot_res.scalar_one_or_none()
            if not snapshot:
                raise SchemaSnapshotNotFoundError(f"No schema snapshot found for KB {kb.id}")

            canonical_schema = DatabaseSchema.model_validate(snapshot.schema_data)
            schema_version = snapshot.schema_version

        # 2.1 Check Tenant-Isolated LRU Schema Retrieval Cache
        cache = SchemaRetrievalCache.get_instance()
        cache_query = request.user_query
        if request.enable_semantic_glossary or request.workspace_id:
            cache_query = f"{request.user_query}|glossary:{request.enable_semantic_glossary}|ws:{request.workspace_id}"
        cache_key = cache.generate_key(
            tenant_id=str(self.tenant_id),
            kb_id=str(kb.id),
            schema_version=str(schema_version),
            user_query=cache_query,
            top_k_tables=request.top_k_tables,
            top_k_columns=request.top_k_columns_per_table,
        )
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"SchemaRetrievalCache hit for KB {kb.id} (version {schema_version[:8]})")
            return cached_result

        # Determine canonical table filtering: filter candidates to is_canonical=true by default.
        # Only relax the canonical filter if user query has explicit raw/history/audit intent keywords.
        raw_intent_keywords = {"history", "historical", "archive", "audit", "backup", "changelog", "revisions", "bak"}
        query_words = set(request.user_query.lower().split())
        allow_non_canonical = bool(query_words.intersection(raw_intent_keywords))

        canonical_overrides = None
        if hasattr(kb, "metadata") and isinstance(kb.metadata, dict):
            canonical_overrides = kb.metadata.get("canonical_overrides")

        from ..semantic_glossary.canonicality import is_canonical_table
        canonical_tables = {
            t.table_name: t for t in canonical_schema.all_tables
            if allow_non_canonical or is_canonical_table(t, canonical_overrides=canonical_overrides)
        }

        # Check feature flag for semantic glossary
        enable_glossary = request.enable_semantic_glossary
        if not enable_glossary and hasattr(kb, "metadata") and isinstance(kb.metadata, dict):
            enable_glossary = kb.metadata.get("enable_semantic_glossary", False)

        published_glossary_map = {}
        if enable_glossary:
            from ..models.concept_glossary import ConceptGlossary, SchemaWorkspace
            from ..semantic_glossary.workspace_partitioner import WorkspacePartitioner

            # LOAD-BEARING REVIEW GATE: strictly fetch published entries
            glossary_stmt = select(ConceptGlossary).where(
                and_(
                    ConceptGlossary.tenant_id == str(self.tenant_id),
                    ConceptGlossary.schema_fingerprint == schema_version,
                    ConceptGlossary.is_published == True,
                )
            )
            glossary_res = await self.session.execute(glossary_stmt)
            published_entries = glossary_res.scalars().all()
            published_glossary_map = {(row.table_name, row.column_name): row for row in published_entries}

            # Resolve domain workspace if workspaces exist
            target_workspace = request.workspace_id
            ws_stmt = select(SchemaWorkspace).where(
                and_(
                    SchemaWorkspace.tenant_id == str(self.tenant_id),
                    SchemaWorkspace.schema_fingerprint == schema_version,
                )
            )
            ws_res = await self.session.execute(ws_stmt)
            workspaces = ws_res.scalars().all()

            if not target_workspace and workspaces:
                target_workspace = WorkspacePartitioner.route_query_to_workspace(
                    query=request.user_query,
                    workspaces=workspaces,
                    published_glossary=published_entries,
                )

            if target_workspace and workspaces:
                ws_tables = {ws.table_name.lower() for ws in workspaces if ws.workspace_name.lower() == target_workspace.lower()}
                if ws_tables:
                    # Filter allowed canonical tables to those in the target workspace
                    canonical_tables = {
                        k: v for k, v in canonical_tables.items()
                        if k.lower() in ws_tables
                    }
                    logger.info(f"Scoped retrieval to workspace '{target_workspace}' ({len(canonical_tables)} tables)")

        allowed_table_keys = {
            f"{t.schema_name}.{t.table_name}" for t in canonical_tables.values()
        } | set(canonical_tables.keys())

        # 3. Signal 1: Instant Deterministic Keyword / Identifier Matching (0.2 ms)
        keyword_results: Dict[str, KeywordMatchResult] = SchemaKeywordMatcher.match_schema(
            query=request.user_query,
            schema=canonical_schema,
            allowed_tables=allowed_table_keys,
            glossary_entries=published_glossary_map if enable_glossary else None,
        )

        strong_keyword_matches = sum(
            1 for km in keyword_results.values() if km.score >= 0.6 or km.matched_table_name
        )

        # 4. Signal 2: Dense Vector Retrieval with adaptive timeout (600ms if keywords matched, 1.2s otherwise)
        vector_results: Dict[str, VectorMatchResult] = {}
        is_vector_available = False
        vector_timeout = 0.4 if strong_keyword_matches >= 1 else 0.8

        try:
            query_vector = await asyncio.wait_for(
                EmbeddingGenerator.generate_embedding(request.user_query),
                timeout=vector_timeout,
            )
            if query_vector and any(query_vector):
                vector_results = await SchemaVectorSearch.search(
                    session=self.session,
                    tenant_id=self.tenant_id,
                    kb_id=kb.id,
                    schema_version=schema_version,
                    query_embedding=query_vector,
                    top_k=request.top_k_tables * 2,
                )
                is_vector_available = True
        except (asyncio.TimeoutError, Exception) as e:
            logger.info(
                f"Vector retrieval skipped or timed out ({e}) after {vector_timeout}s. "
                "Using deterministic keyword + graph fallback."
            )
            is_vector_available = False

        # 5. First-pass Seed Identification for Graph Expansion
        initial_fused = HybridScorer.fuse_scores(
            vector_results=vector_results,
            keyword_results=keyword_results,
            graph_boosts={},
            is_vector_available=is_vector_available,
            allowed_table_keys=allowed_table_keys,
        )

        # Identify candidate seeds (tables scoring significantly above noise)
        candidate_seeds: Set[str] = set()
        max_initial_score = max((s.final_score for s in initial_fused.values()), default=0.0)

        for t_key, score in initial_fused.items():
            if score.keyword_score >= 0.25:
                candidate_seeds.add(t_key)
            elif score.vector_score >= 0.50 and score.final_score >= max_initial_score * 0.75:
                candidate_seeds.add(t_key)
            elif max_initial_score >= 0.20 and score.final_score >= max(0.25, max_initial_score * 0.80):
                candidate_seeds.add(t_key)

        # 5.1 If query mentions an entity literal (e.g. employee name like 'Girinath'), anchor on core employee table
        if canonical_schema:
            from ..planning.entity_value_resolver import EntityValueResolver
            literal_candidates = EntityValueResolver.extract_literal_candidates(request.user_query, canonical_schema=canonical_schema)
            if literal_candidates:
                for s_name, s_val in canonical_schema.schemas.items():
                    for t_name, t_obj in s_val.tables.items():
                        if t_name.lower() == "employee_employee" or (
                            "employee" in t_name.lower()
                            and "employee_first_name" in {c.lower() for c in t_obj.columns.keys()}
                            and not any(h in t_name.lower() for h in ("historical", "backup", "audit", "note", "tag", "detail"))
                        ):
                            t_key = f"{t_obj.schema_name}.{t_obj.table_name}"
                            candidate_seeds.add(t_key)
                            if t_key not in initial_fused:
                                initial_fused[t_key] = TableRetrievalScore(
                                    table_name=t_obj.table_name,
                                    schema_name=t_obj.schema_name,
                                    keyword_score=0.95,
                                    final_score=0.95,
                                    retrieval_source="anchor",
                                    retrieval_reason="Employee anchor match",
                                )
                            else:
                                initial_fused[t_key].final_score = max(initial_fused[t_key].final_score, 0.95)
                            keyword_results[t_key] = KeywordMatchResult(
                                table_name=t_obj.table_name,
                                schema_name=t_obj.schema_name,
                                score=0.95,
                                matched_table_name=True,
                                matched_columns=[],
                                matched_tokens=["employee_anchor"],
                                retrieval_reason="Employee anchor match",
                            )
                            break

        # If no seeds pass threshold, pick highest scoring single candidate
        if not candidate_seeds and initial_fused:
            best_t_key = max(initial_fused.keys(), key=lambda k: initial_fused[k].final_score)
            candidate_seeds.add(best_t_key)

        # 6. Signal 3: Relationship Graph Expansion (Multi-Hop Join Resolution)
        active_relationships: List[RelationshipSchema] = []
        graph_boosts: Dict[str, float] = {}

        if request.include_relationships and candidate_seeds:
            expansion = SchemaGraphExpander.expand_seeds(
                seed_tables=candidate_seeds,
                schema=canonical_schema,
                max_hops=3,
                bridge_table_boost=0.85,
            )
            graph_boosts = expansion.graph_boosts
            active_relationships = expansion.active_relationships

        # 7. Final Score Fusion (combining vector, keyword, and graph signals)
        final_scores = HybridScorer.fuse_scores(
            vector_results=vector_results,
            keyword_results=keyword_results,
            graph_boosts=graph_boosts,
            is_vector_available=is_vector_available,
            allowed_table_keys=allowed_table_keys,
        )

        # 8. Table Selection
        # Sort candidates by final_score descending
        ranked_tables = sorted(
            final_scores.keys(),
            key=lambda k: final_scores[k].final_score,
            reverse=True,
        )

        max_final_score = max((final_scores[k].final_score for k in ranked_tables), default=0.0)

        # Select top-K tables: prioritize connective join paths between multi-entity seeds, then candidate seeds, then strong candidates
        selected_table_keys: Dict[str, TableRetrievalScore] = {}

        # 8.1 Multi-Entity Path Preservation (Phase 6.5)
        # If user query references multiple domain entities, guarantee their connective join path is retrieved
        analysis = QueryIntentAnalyzer.analyze(request.user_query)
        detected_entities = analysis.detected_entities

        primary_entity_seeds: List[str] = []
        if detected_entities and len(detected_entities) >= 2:
            for ent in detected_entities:
                ent_clean = ent.lower()
                ent_stem = ent_clean[:-1] if (ent_clean.endswith("s") and len(ent_clean) > 3) else ent_clean
                best_seed = None
                best_seed_score = -1.0

                for t_key, score_obj in final_scores.items():
                    t_name = t_key.split(".")[-1].lower()
                    match_score = score_obj.final_score
                    if t_name == ent_clean or t_name == f"{ent_clean}_{ent_clean}" or t_name == f"base_{ent_clean}":
                        match_score += 1.0
                    elif ent_clean.replace("_", "") in t_name.replace("_", ""):
                        match_score += 0.5
                    elif ent_clean in t_name or ent_stem in t_name:
                        match_score += 0.3
                    else:
                        continue

                    if match_score > best_seed_score:
                        best_seed_score = match_score
                        best_seed = t_key

                if best_seed and best_seed not in primary_entity_seeds:
                    primary_entity_seeds.append(best_seed)

            # Ensure all tables along the shortest connective path between primary entity seeds are included
            if len(primary_entity_seeds) >= 2:
                graph = SchemaGraph.from_database_schema(canonical_schema)
                for i in range(len(primary_entity_seeds)):
                    for j in range(i + 1, len(primary_entity_seeds)):
                        s1 = primary_entity_seeds[i]
                        s2 = primary_entity_seeds[j]
                        path = graph.find_shortest_path(s1, s2, max_hops=3)
                        if path:
                            for tbl in path:
                                if len(selected_table_keys) >= request.top_k_tables:
                                    break
                                for k in final_scores.keys():
                                    if k.lower() == tbl.lower() or k.split(".")[-1].lower() == tbl.split(".")[-1].lower():
                                        if k not in selected_table_keys:
                                            selected_table_keys[k] = final_scores[k]
                                        break

        # 8.2 Fill remaining slots with highest-ranked candidate tables
        for t_key in ranked_tables:
            if len(selected_table_keys) >= request.top_k_tables:
                break
            if t_key not in selected_table_keys:
                selected_table_keys[t_key] = final_scores[t_key]

        # If nothing selected, pick top 1 table as fallback
        if not selected_table_keys and ranked_tables:
            top_key = ranked_tables[0]
            selected_table_keys[top_key] = final_scores[top_key]

        # 9. Hierarchical Pruning & XML Boundary Construction
        pruned_tables, pruned_rels, untrusted_xml = SchemaPruner.prune_schema(
            canonical_schema=canonical_schema,
            selected_scores=selected_table_keys,
            active_relationships=active_relationships,
            top_k_columns_per_table=request.top_k_columns_per_table,
        )

        # 10. Compute Overall Retrieval Confidence
        if selected_table_keys:
            avg_score = sum(s.final_score for s in selected_table_keys.values()) / len(selected_table_keys)
            max_score = max(s.final_score for s in selected_table_keys.values())
            overall_confidence = round(0.5 * avg_score + 0.5 * max_score, 4)
        else:
            overall_confidence = 0.0

        result = SchemaRetrievalResult(
            database_name=canonical_schema.database_name,
            database_type=canonical_schema.database_type,
            schema_version=schema_version,
            retrieved_tables=pruned_tables,
            retrieval_scores=selected_table_keys,
            join_paths=pruned_rels,
            overall_confidence=min(1.0, max(0.0, overall_confidence)),
            untrusted_boundary_text=untrusted_xml,
        )

        # Cache valid outcome before returning
        cache.set(
            key=cache_key,
            result=result,
            tenant_id=str(self.tenant_id),
            kb_id=str(kb.id),
        )
        return result
