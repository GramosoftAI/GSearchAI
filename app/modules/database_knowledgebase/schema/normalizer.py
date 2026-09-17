"""Schema Normalizer: Converts Raw Introspection Metadata to Canonical DatabaseSchema"""

import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
    PrimaryKeySchema,
    ForeignKeySchema,
    RelationshipSchema,
    RelationshipType,
    IndexSchema,
)
from ..exceptions.errors import SchemaParsingError


# Mapping PostgreSQL / SQL types to normalized ColumnDataType
PG_TYPE_MAP: Dict[str, ColumnDataType] = {
    "int": ColumnDataType.INTEGER,
    "int4": ColumnDataType.INTEGER,
    "integer": ColumnDataType.INTEGER,
    "serial": ColumnDataType.INTEGER,
    "int8": ColumnDataType.BIGINT,
    "bigint": ColumnDataType.BIGINT,
    "bigserial": ColumnDataType.BIGINT,
    "int2": ColumnDataType.SMALLINT,
    "smallint": ColumnDataType.SMALLINT,
    "smallserial": ColumnDataType.SMALLINT,
    "numeric": ColumnDataType.NUMERIC,
    "decimal": ColumnDataType.DECIMAL,
    "money": ColumnDataType.DECIMAL,
    "real": ColumnDataType.REAL,
    "float4": ColumnDataType.REAL,
    "double precision": ColumnDataType.DOUBLE,
    "float8": ColumnDataType.DOUBLE,
    "float": ColumnDataType.FLOAT,
    "varchar": ColumnDataType.VARCHAR,
    "character varying": ColumnDataType.VARCHAR,
    "char": ColumnDataType.CHAR,
    "character": ColumnDataType.CHAR,
    "bpchar": ColumnDataType.CHAR,
    "text": ColumnDataType.TEXT,
    "bool": ColumnDataType.BOOLEAN,
    "boolean": ColumnDataType.BOOLEAN,
    "date": ColumnDataType.DATE,
    "timestamp": ColumnDataType.TIMESTAMP,
    "timestamp without time zone": ColumnDataType.TIMESTAMP,
    "timestamptz": ColumnDataType.TIMESTAMPTZ,
    "timestamp with time zone": ColumnDataType.TIMESTAMPTZ,
    "time": ColumnDataType.TIME,
    "time without time zone": ColumnDataType.TIME,
    "timetz": ColumnDataType.TIMESTAMPTZ,
    "json": ColumnDataType.JSON,
    "jsonb": ColumnDataType.JSONB,
    "uuid": ColumnDataType.UUID,
    "bytea": ColumnDataType.BYTEA,
    "array": ColumnDataType.ARRAY,
}


class SchemaNormalizer:
    """Normalizes engine-specific metadata into canonical models."""

    @staticmethod
    def map_data_type(data_type: str, udt_name: Optional[str] = None) -> ColumnDataType:
        """Map raw engine type string to normalized ColumnDataType."""
        dt_clean = (data_type or "").lower().strip()
        udt_clean = (udt_name or "").lower().strip()

        # Check for array types (starts with _ in PostgreSQL udt_name or ends with [])
        if udt_clean.startswith("_") or "[]" in dt_clean or dt_clean == "array":
            return ColumnDataType.ARRAY

        # Check explicit data_type map
        if dt_clean in PG_TYPE_MAP:
            return PG_TYPE_MAP[dt_clean]

        # Check udt_name map
        if udt_clean in PG_TYPE_MAP:
            return PG_TYPE_MAP[udt_clean]

        # Substring heuristics
        if "int" in dt_clean:
            return ColumnDataType.INTEGER
        elif "char" in dt_clean or "varchar" in dt_clean:
            return ColumnDataType.VARCHAR
        elif "text" in dt_clean:
            return ColumnDataType.TEXT
        elif "numeric" in dt_clean or "decimal" in dt_clean:
            return ColumnDataType.DECIMAL
        elif "float" in dt_clean or "double" in dt_clean:
            return ColumnDataType.FLOAT
        elif "bool" in dt_clean:
            return ColumnDataType.BOOLEAN
        elif "time" in dt_clean or "date" in dt_clean:
            return ColumnDataType.TIMESTAMP
        elif "json" in dt_clean:
            return ColumnDataType.JSON
        elif "uuid" in dt_clean:
            return ColumnDataType.UUID

        return ColumnDataType.OTHER

    @classmethod
    def normalize_postgres_raw(cls, raw_data: Dict[str, Any]) -> DatabaseSchema:
        """
        Convert raw PostgreSQL metadata dictionaries into canonical DatabaseSchema.
        """
        try:
            db_name = raw_data.get("database_name", "unknown")
            schemas_dict: Dict[str, SchemaInfo] = {}

            # 1. Initialize Schemas
            raw_schemas = raw_data.get("schemas", [])
            for s in raw_schemas:
                s_name = s["schema_name"]
                schemas_dict[s_name] = SchemaInfo(schema_name=s_name, tables={})

            if not schemas_dict:
                schemas_dict["public"] = SchemaInfo(schema_name="public", tables={})

            # 2. Build Tables dictionary
            raw_tables = raw_data.get("tables", [])
            for t in raw_tables:
                s_name = t["table_schema"]
                t_name = t["table_name"]
                t_type = "VIEW" if "VIEW" in t.get("table_type", "").upper() else "TABLE"
                t_comment = t.get("table_comment")

                if s_name not in schemas_dict:
                    schemas_dict[s_name] = SchemaInfo(schema_name=s_name, tables={})

                schemas_dict[s_name].tables[t_name] = TableSchema(
                    schema_name=s_name,
                    table_name=t_name,
                    table_type=t_type,
                    comment=t_comment,
                    columns={},
                    primary_key=None,
                    foreign_keys=[],
                    relationships=[],
                    indexes=[],
                )

            # 3. Add Columns
            raw_columns = raw_data.get("columns", [])
            for c in raw_columns:
                s_name = c["table_schema"]
                t_name = c["table_name"]
                c_name = c["column_name"]
                raw_dt = c.get("data_type", "unknown")
                udt_name = c.get("udt_name")
                norm_dt = cls.map_data_type(raw_dt, udt_name)
                is_null = str(c.get("is_nullable", "YES")).upper() == "YES"
                col_def = c.get("column_default")
                ord_pos = int(c.get("ordinal_position", 0))
                col_comment = c.get("column_comment")

                if s_name in schemas_dict and t_name in schemas_dict[s_name].tables:
                    col_schema = ColumnSchema(
                        name=c_name,
                        data_type=norm_dt,
                        raw_data_type=raw_dt,
                        is_nullable=is_null,
                        default_value=col_def,
                        is_primary_key=False,
                        is_foreign_key=False,
                        comment=col_comment,
                        ordinal_position=ord_pos,
                    )
                    schemas_dict[s_name].tables[t_name].columns[c_name] = col_schema

            # 4. Add Primary Keys
            raw_pks = raw_data.get("primary_keys", [])
            pk_map: Dict[str, Dict[str, List[str]]] = {}
            for pk in raw_pks:
                s_name = pk["table_schema"]
                t_name = pk["table_name"]
                c_name = pk["column_name"]
                c_constraint = pk.get("constraint_name")

                key = f"{s_name}.{t_name}"
                if key not in pk_map:
                    pk_map[key] = {"name": c_constraint, "columns": []}
                pk_map[key]["columns"].append(c_name)

                # Mark column as PK
                if s_name in schemas_dict and t_name in schemas_dict[s_name].tables:
                    if c_name in schemas_dict[s_name].tables[t_name].columns:
                        schemas_dict[s_name].tables[t_name].columns[c_name].is_primary_key = True

            for key, pk_info in pk_map.items():
                s_name, t_name = key.split(".", 1)
                if s_name in schemas_dict and t_name in schemas_dict[s_name].tables:
                    schemas_dict[s_name].tables[t_name].primary_key = PrimaryKeySchema(
                        name=pk_info["name"],
                        constrained_columns=pk_info["columns"],
                    )

            # 5. Add Foreign Keys & Relationships
            raw_fks = raw_data.get("foreign_keys", [])
            fk_grouped: Dict[str, Dict[str, Any]] = {}
            for fk in raw_fks:
                c_name = fk["constraint_name"]
                s_name = fk["source_schema"]
                s_tbl = fk["source_table"]
                s_col = fk["source_column"]
                t_schema = fk["target_schema"]
                t_tbl = fk["target_table"]
                t_col = fk["target_column"]
                on_del = fk.get("on_delete")
                on_upd = fk.get("on_update")

                group_key = f"{s_name}.{s_tbl}.{c_name}"
                if group_key not in fk_grouped:
                    fk_grouped[group_key] = {
                        "name": c_name,
                        "source_schema": s_name,
                        "source_table": s_tbl,
                        "source_columns": [],
                        "target_schema": t_schema,
                        "target_table": t_tbl,
                        "target_columns": [],
                        "on_delete": on_del,
                        "on_update": on_upd,
                    }
                fk_grouped[group_key]["source_columns"].append(s_col)
                fk_grouped[group_key]["target_columns"].append(t_col)

                # Mark source column as FK
                if s_name in schemas_dict and s_tbl in schemas_dict[s_name].tables:
                    if s_col in schemas_dict[s_name].tables[s_tbl].columns:
                        schemas_dict[s_name].tables[s_tbl].columns[s_col].is_foreign_key = True

            for group_key, fk_data in fk_grouped.items():
                s_name = fk_data["source_schema"]
                s_tbl = fk_data["source_table"]
                t_schema = fk_data["target_schema"]
                t_tbl = fk_data["target_table"]

                fk_obj = ForeignKeySchema(
                    name=fk_data["name"],
                    constrained_columns=fk_data["source_columns"],
                    referred_schema=t_schema,
                    referred_table=t_tbl,
                    referred_columns=fk_data["target_columns"],
                    on_delete=fk_data["on_delete"],
                    on_update=fk_data["on_update"],
                )

                if s_name in schemas_dict and s_tbl in schemas_dict[s_name].tables:
                    schemas_dict[s_name].tables[s_tbl].foreign_keys.append(fk_obj)

                    # Source to target (MANY_TO_ONE)
                    schemas_dict[s_name].tables[s_tbl].relationships.append(
                        RelationshipSchema(
                            source_schema=s_name,
                            source_table=s_tbl,
                            source_columns=fk_data["source_columns"],
                            target_schema=t_schema,
                            target_table=t_tbl,
                            target_columns=fk_data["target_columns"],
                            relationship_type=RelationshipType.MANY_TO_ONE,
                            foreign_key_name=fk_data["name"],
                            description=f"{s_tbl} ({', '.join(fk_data['source_columns'])}) references {t_tbl} ({', '.join(fk_data['target_columns'])})",
                        )
                    )

                # Inverse relationship on Target table (ONE_TO_MANY)
                if t_schema in schemas_dict and t_tbl in schemas_dict[t_schema].tables:
                    schemas_dict[t_schema].tables[t_tbl].relationships.append(
                        RelationshipSchema(
                            source_schema=t_schema,
                            source_table=t_tbl,
                            source_columns=fk_data["target_columns"],
                            target_schema=s_name,
                            target_table=s_tbl,
                            target_columns=fk_data["source_columns"],
                            relationship_type=RelationshipType.ONE_TO_MANY,
                            foreign_key_name=fk_data["name"],
                            description=f"{t_tbl} has many {s_tbl} referencing ({', '.join(fk_data['target_columns'])})",
                        )
                    )

            # 6. Add Indexes
            raw_indexes = raw_data.get("indexes", [])
            for idx in raw_indexes:
                s_name = idx["schema_name"]
                t_name = idx["table_name"]
                i_name = idx["index_name"]
                i_def = idx.get("index_def", "")

                is_unique = "UNIQUE" in i_def.upper()
                is_primary = "_pkey" in i_name.lower()

                # Extract column names from index definition regex like 'USING btree (col1, col2)'
                col_match = re.search(r"\(([^)]+)\)", i_def)
                col_names = []
                if col_match:
                    raw_cols = col_match.group(1).split(",")
                    col_names = [c.strip().strip('"') for c in raw_cols]

                if s_name in schemas_dict and t_name in schemas_dict[s_name].tables:
                    schemas_dict[s_name].tables[t_name].indexes.append(
                        IndexSchema(
                            name=i_name,
                            column_names=col_names,
                            is_unique=is_unique,
                            is_primary=is_primary,
                        )
                    )

            # 7. Construct canonical schema object
            canonical_db = DatabaseSchema(
                database_name=db_name,
                database_type="postgresql",
                schemas=schemas_dict,
                fingerprint="",
                introspected_at=datetime.utcnow(),
            )
            canonical_db.compute_summary()
            return canonical_db

        except Exception as e:
            raise SchemaParsingError(
                detail=f"Failed to normalize database metadata into canonical schema: {str(e)}"
            ) from e
