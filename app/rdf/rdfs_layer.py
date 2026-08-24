"""
Layer 2 — RDFS: Canonical Mapping & Type Hierarchy

Responsibilities:
  1. Predicate normalization — maps freeform LLM predicates ("bought", "ordered")
     to canonical graph edge types ("PURCHASED").
  2. Entity type alias resolution — maps document-specific aliases ("GST Reg. Number")
     to canonical types ("GSTIN").
  3. Type hierarchy inference — infers parent types (EMPLOYEE → PERSON, CITY → LOCATION)
     so subclass-aware queries work automatically.
  4. Tenant-aware overrides — loads custom type hierarchies from OntologyService when available.

Absorbs:
  - CANONICAL_RELATIONS from app/modules/tripets/models.py
  - entity_registry.py from app/core/entity_registry.py
"""

import logging
from typing import Dict, List, Optional, Set

from .namespace import RDFTriple

logger = logging.getLogger(__name__)


# ============================================================================
# CANONICAL PREDICATE MAPPING (rdfs:subPropertyOf equivalent)
# ============================================================================

# Maps freeform LLM predicates → standardized Neo4j edge types.
# This is the RDFS "subPropertyOf" concept: many surface forms collapse
# to one canonical predicate.
CANONICAL_RELATIONS: Dict[str, str] = {
    # Issuance
    "issued": "ISSUED_BY",
    "created_bill": "ISSUED_BY",
    "generated_invoice": "ISSUED_BY",
    # Purchase
    "purchased": "PURCHASED",
    "bought": "PURCHASED",
    "ordered": "PURCHASED",
    # Supply
    "supplied_by": "SUPPLIED_BY",
    "provided_by": "SUPPLIED_BY",
    # Containment
    "contains": "CONTAINS_PRODUCT",
    "includes": "CONTAINS_PRODUCT",
    # Organizational
    "belongs_to": "BELONGS_TO",
    "works_for": "WORKS_FOR",
    "works_at": "WORKS_FOR",
    "employed_by": "WORKS_FOR",
    "employee_of": "WORKS_FOR",
    # Location
    "located_in": "LOCATED_IN",
    "lives_in": "LOCATED_IN",
    "based_in": "LOCATED_IN",
    # Attributes
    "has_amount": "HAS_AMOUNT",
    "has_date": "HAS_DATE",
    # References
    "references": "REFERENCES",
    "derived_from": "DERIVED_FROM",
    # Leadership
    "ceo_of": "CEO_OF",
    "founded": "FOUNDED",
    "leads": "LEADS",
    # Acquisition
    "acquired": "ACQUIRED",
    "merged_with": "MERGED_WITH",
}


# ============================================================================
# ENTITY TYPE ALIAS REGISTRY (rdfs:label equivalents)
# ============================================================================

# Maps document-specific entity aliases → canonical type names.
# Absorbed from app/core/entity_registry.py
ENTITY_TYPE_ALIASES: Dict[str, List[str]] = {
    "GSTIN": [
        "GSTIN No", "GST Reg. Number", "Tax Identification Number",
        "Buyer GST Registration", "GST Registration No.", "GSTIN/UIN",
        "GST Number",
    ],
    "PAN": [
        "PAN Number", "Permanent Account Number", "PAN No", "PAN",
    ],
    "VIN": [
        "Vehicle Identification Number", "VIN Number", "Chassis Number",
    ],
    "INVOICE_NUMBER": [
        "Invoice No", "Bill No", "Invoice ID", "Tax Invoice Number",
        "Reference No", "Inv No",
    ],
    "PO_NUMBER": [
        "PO Number", "Purchase Order Number", "Order No", "PO Ref",
    ],
    "ENGINE_NUMBER": ["Engine No", "Motor Number"],
    "REGISTRATION_NUMBER": [
        "Registration No", "Vehicle Registration Number", "Reg No",
    ],
    "HSN_CODE": ["HSN", "HSN/SAC", "Harmonized System Nomenclature"],
}

# Precomputed reverse lookup: alias.lower() → canonical type
_ALIAS_LOOKUP: Dict[str, str] = {}
for _canonical, _aliases in ENTITY_TYPE_ALIASES.items():
    _ALIAS_LOOKUP[_canonical.lower()] = _canonical
    for _alias in _aliases:
        _ALIAS_LOOKUP[_alias.lower()] = _canonical


# ============================================================================
# TYPE HIERARCHY (rdfs:subClassOf equivalent)
# ============================================================================

# Maps specific types → their parent types.
# When an entity is typed as "EMPLOYEE", it is also a "PERSON".
TYPE_HIERARCHY: Dict[str, str] = {
    "EMPLOYEE": "PERSON",
    "CUSTOMER": "PERSON",
    "FOUNDER": "PERSON",
    "CEO": "PERSON",
    "MANAGER": "PERSON",
    "SUPPLIER": "ORGANIZATION",
    "VENDOR": "ORGANIZATION",
    "COMPANY": "ORGANIZATION",
    "STARTUP": "ORGANIZATION",
    "CITY": "LOCATION",
    "COUNTRY": "LOCATION",
    "STATE": "LOCATION",
    "REGION": "LOCATION",
    "ADDRESS": "LOCATION",
    "INVOICE": "DOCUMENT",
    "RECEIPT": "DOCUMENT",
    "CONTRACT": "DOCUMENT",
    "REPORT": "DOCUMENT",
}


# ============================================================================
# RDFS LAYER
# ============================================================================

class RDFSLayer:
    """
    Layer 2 processor: normalizes predicates, resolves entity type aliases,
    and infers parent types using the type hierarchy.

    Optionally loads tenant-specific overrides from the OntologyService.
    """

    def __init__(
        self,
        tenant_id: str,
        custom_relations: Optional[Dict[str, str]] = None,
        custom_hierarchy: Optional[Dict[str, str]] = None,
    ):
        self.tenant_id = tenant_id

        # Merge custom overrides with defaults (custom wins)
        self.relations = dict(CANONICAL_RELATIONS)
        if custom_relations:
            self.relations.update(custom_relations)

        self.hierarchy = dict(TYPE_HIERARCHY)
        if custom_hierarchy:
            self.hierarchy.update(custom_hierarchy)

    @classmethod
    async def create(
        cls,
        tenant_id: str,
    ) -> "RDFSLayer":
        """
        Factory method that loads tenant-specific ontology overrides
        from the OntologyService before constructing the layer.
        """
        custom_relations: Dict[str, str] = {}
        try:
            from app.modules.ontology.service import OntologyService
            ont_svc = OntologyService(tenant_id)
            ont_data = await ont_svc.get_ontology()

            # Tenant-defined relations become canonical mappings
            for r in ont_data.get("relations", []):
                name = r.get("name", "")
                if name:
                    # Self-map so the name is treated as canonical
                    custom_relations[name.lower()] = name.upper()
        except Exception as e:
            logger.warning(f"RDFS Layer: could not load tenant ontology: {e}")

        return cls(tenant_id, custom_relations=custom_relations)

    def normalize(self, triple: RDFTriple) -> RDFTriple:
        """
        Apply RDFS normalization to a single RDFTriple:
          1. Normalize predicate to canonical form
          2. Resolve entity type aliases
          3. Infer parent types via hierarchy
        """
        # --- Predicate normalization ---
        raw_pred = triple.predicate.strip().lower().replace(" ", "_")
        canonical_pred = self.relations.get(raw_pred, raw_pred.upper())
        triple.predicate = canonical_pred

        # --- Entity type resolution ---
        triple.subject_type = self._resolve_type(triple.subject_type)
        triple.object_type = self._resolve_type(triple.object_type)

        # --- Text normalization ---
        if triple.subject_text:
            triple.subject_text = triple.subject_text.strip().lower()
        if triple.object_text:
            triple.object_text = triple.object_text.strip().lower()

        # --- Participant type resolution ---
        for p in triple.participants:
            p.entity_type = self._resolve_type(p.entity_type)
            if p.entity:
                p.entity = p.entity.strip().lower()

        # --- Attribute type resolution ---
        for a in triple.attributes:
            a.entity_type = self._resolve_type(a.entity_type)
            if a.attribute:
                a.attribute = a.attribute.strip().upper().replace(" ", "_")
            if a.value:
                a.value = a.value.strip().lower()

        return triple

    def normalize_batch(self, triples: List[RDFTriple]) -> List[RDFTriple]:
        """Normalize a batch of triples."""
        return [self.normalize(t) for t in triples]

    def _resolve_type(self, raw_type: str) -> str:
        """
        Resolve an entity type through the alias registry and hierarchy.

        Resolution order:
          1. Check alias registry (e.g., "GST Reg. Number" → "GSTIN")
          2. Check type hierarchy for parent type (e.g., "EMPLOYEE" stays "EMPLOYEE"
             but its parent "PERSON" can be inferred at query time)
          3. Fallback to uppercased, underscored form
        """
        if not raw_type:
            return "CONCEPT"

        cleaned = raw_type.strip().lower()

        # 1. Alias registry
        canonical = _ALIAS_LOOKUP.get(cleaned)
        if canonical:
            return canonical

        # 2. Uppercase normalization (matches hierarchy keys)
        upper = cleaned.upper().replace(" ", "_")
        return upper

    def get_parent_type(self, entity_type: str) -> Optional[str]:
        """Return the parent type in the hierarchy, or None if it's a root type."""
        return self.hierarchy.get(entity_type.upper())

    def get_all_supertypes(self, entity_type: str) -> List[str]:
        """
        Walk the type hierarchy upward and return all ancestor types.
        E.g., "CITY" → ["LOCATION"]
        """
        supertypes = []
        current = entity_type.upper()
        visited: Set[str] = set()
        while current in self.hierarchy and current not in visited:
            visited.add(current)
            parent = self.hierarchy[current]
            supertypes.append(parent)
            current = parent
        return supertypes

    def resolve_entity_type(self, alias: str) -> str:
        """
        Public helper — resolves any extracted alias to its canonical entity type.
        Backward-compatible replacement for entity_registry.resolve_entity_type().
        """
        return self._resolve_type(alias)

    def get_all_aliases(self) -> List[str]:
        """
        Returns a flat list of all recognized aliases and canonical names.
        Backward-compatible replacement for entity_registry.get_all_aliases().
        """
        aliases: List[str] = []
        for canonical, alias_list in ENTITY_TYPE_ALIASES.items():
            aliases.append(canonical)
            aliases.extend(alias_list)
        return list(set(aliases))
