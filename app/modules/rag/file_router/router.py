import logging
from typing import List, Dict, Any, Optional
from .schema import RoutingResult
from .identifier import match_exact_identifiers
from .semantic import match_by_summary_embedding

logger = logging.getLogger(__name__)

CONFIDENT_THRESHOLD = 0.65
AMBIGUITY_GAP = 0.10
MIN_BASELINE = 0.60
DOMINANCE_GAP = 0.10

# Module-level dictionary to persist KB pinning across router instantiations
# Key: session_id, Value: {"kb_id": str, "name": str}
_SESSION_PINNED_KBS: Dict[str, Dict[str, str]] = {}

class FileRouter:
    def __init__(self, tenant_id: str, db: Any = None):
        self.tenant_id = tenant_id
        self.db = db

    async def route_query(self, query: str, query_embedding: List[float], candidate_kb_ids: List[str], kb_metadata: Dict[str, Any], session_id: Optional[str] = None) -> RoutingResult:
        # Filter metadata to only include candidates
        filtered_metadata = {k: v for k, v in kb_metadata.items() if k in candidate_kb_ids}
        
        # 1. Tier 1: Exact Match
        exact_matches = match_exact_identifiers(query, filtered_metadata)
        unique_exact_kbs = list({m.kb_id for m in exact_matches})
        
        final_result = None
        
        if len(unique_exact_kbs) == 1:
            matched_kb = unique_exact_kbs[0]
            reason = f"exact_identifier_match on {exact_matches[0].matched_on}"
            logger.info(f"[FileRouter] {reason} for KB {matched_kb}")
            final_result = RoutingResult(
                is_confident_match=True,
                matched_kb_ids=[matched_kb],
                candidates=exact_matches,
                reason=reason
            )
            
        # 2. Tier 2: Semantic Match
        if not final_result:
            semantic_matches = match_by_summary_embedding(query_embedding, filtered_metadata, candidate_kb_ids)
            all_candidates = exact_matches + semantic_matches
            
            if not semantic_matches:
                reason = "No semantic candidates available (missing embeddings) and no single exact-identifier hit."
                if exact_matches:
                     reason = "Multiple exact matches found but no semantic disambiguation possible."
                logger.info(f"[FileRouter] {reason}")
                final_result = RoutingResult(
                    is_confident_match=False,
                    matched_kb_ids=[],
                    candidates=exact_matches,
                    reason=reason
                )
            else:
                with open('C:\\Users\\hp\\Desktop\\GSOFT\\RAG\\GSearchAI\\scratch_scores.txt', 'a') as f:
                    f.write(f"QUERY: {query}\n")
                    for m in semantic_matches:
                        f.write(f"KB: {m.kb_id}, SCORE: {m.score}\n")
                
                top_match = semantic_matches[0]
                second_match = semantic_matches[1] if len(semantic_matches) > 1 else None
                
                # 1. Evaluate Relative Dominance Rule First
                # Overrides MIN_BASELINE and CONFIDENT_THRESHOLD if there's a clear winner
                if second_match and (top_match.score - second_match.score) >= DOMINANCE_GAP:
                    gap = top_match.score - second_match.score
                    reason = f"Relative dominance rule: top score ({top_match.score:.3f}) beat runner-up ({second_match.score:.3f}) by {gap:.3f} >= DOMINANCE_GAP ({DOMINANCE_GAP}). Overriding thresholds."
                    logger.info(f"[FileRouter] {reason}")
                    final_result = RoutingResult(
                        is_confident_match=True,
                        matched_kb_ids=[top_match.kb_id],
                        candidates=all_candidates,
                        reason=reason
                    )
                # 2. Evaluate Absolute Thresholds (If dominance didn't trigger)
                elif top_match.score < MIN_BASELINE:
                    reason = f"Top score ({top_match.score:.3f}) < MIN_BASELINE ({MIN_BASELINE}). No confident match."
                    logger.info(f"[FileRouter] {reason}")
                    final_result = RoutingResult(
                        is_confident_match=False,
                        matched_kb_ids=[],
                        candidates=all_candidates,
                        reason=reason
                    )
                elif len(semantic_matches) == 1:
                    if top_match.score >= CONFIDENT_THRESHOLD:
                        reason = f"Single valid semantic candidate scored {top_match.score:.3f} >= {CONFIDENT_THRESHOLD}."
                        final_result = RoutingResult(
                            is_confident_match=True,
                            matched_kb_ids=[top_match.kb_id],
                            candidates=all_candidates,
                            reason=reason
                        )
                    else:
                        reason = f"Single valid semantic candidate scored {top_match.score:.3f} < {CONFIDENT_THRESHOLD}."
                        final_result = RoutingResult(
                            is_confident_match=False,
                            matched_kb_ids=[],
                            candidates=all_candidates,
                            reason=reason
                        )
                else:
                    gap = top_match.score - second_match.score
                    
                    if top_match.score >= CONFIDENT_THRESHOLD and gap >= AMBIGUITY_GAP:
                        reason = f"Confident single match: top score {top_match.score:.3f} >= {CONFIDENT_THRESHOLD}, gap to next is {gap:.3f} >= {AMBIGUITY_GAP}."
                        final_result = RoutingResult(
                            is_confident_match=True,
                            matched_kb_ids=[top_match.kb_id],
                            candidates=all_candidates,
                            reason=reason
                        )
                    elif top_match.score >= CONFIDENT_THRESHOLD and gap < AMBIGUITY_GAP:
                        clustered_kbs = []
                        for m in semantic_matches:
                            if (top_match.score - m.score) < AMBIGUITY_GAP and m.score >= CONFIDENT_THRESHOLD:
                                clustered_kbs.append(m.kb_id)
                        
                        reason = f"Confident multi-match: {len(clustered_kbs)} candidates clustered within {AMBIGUITY_GAP} gap of top score {top_match.score:.3f}."
                        final_result = RoutingResult(
                            is_confident_match=True,
                            matched_kb_ids=clustered_kbs,
                            candidates=all_candidates,
                            reason=reason
                        )
                    else:
                        reason = f"Top score ({top_match.score:.3f}) < CONFIDENT_THRESHOLD ({CONFIDENT_THRESHOLD}) but >= MIN_BASELINE ({MIN_BASELINE}). Ambiguous, falling back."
                        final_result = RoutingResult(
                            is_confident_match=False,
                            matched_kb_ids=[],
                            candidates=all_candidates,
                            reason=reason
                        )
                        
        # 3. Session Pinning logic
        if session_id:
            if final_result.is_confident_match and len(final_result.matched_kb_ids) == 1:
                kb_id = final_result.matched_kb_ids[0]
                kb_name = kb_metadata.get(kb_id, {}).get("name", kb_id)
                _SESSION_PINNED_KBS[session_id] = {"kb_id": kb_id, "name": kb_name}
                logger.info(f"[FileRouter] Pinned KB {kb_name} ({kb_id}) for session {session_id}")
            elif not final_result.is_confident_match:
                pinned_kb = _SESSION_PINNED_KBS.get(session_id)
                if pinned_kb and pinned_kb["kb_id"] in candidate_kb_ids:
                    logger.info(f"[FileRouter] Match was not confident. Falling back to previously pinned KB {pinned_kb['name']} ({pinned_kb['kb_id']}) for session {session_id}")
                    final_result.is_confident_match = True
                    final_result.matched_kb_ids = [pinned_kb["kb_id"]]
                    final_result.reason += f" -> Overridden by session pinned KB {pinned_kb['kb_id']}"
                    
        return final_result

