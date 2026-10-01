"""CLI tool to run and export Schema Documentation ("Cheat Sheet") for a Knowledgebase.

Usage:
    python scripts/export_schema_doc.py --kb-id c32fb444-883e-4f68-a1d9-8125c8f84c7e --out-dir ./schema_docs
"""

import argparse
import asyncio
import os
import json
import uuid
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
from app.modules.database_knowledgebase.schema_doc.exporter import CheatSheetExporter
from app.modules.database_knowledgebase.schema_doc.pipeline import SchemaDocPipeline
from app.modules.database_knowledgebase.security.secrets import get_secret_manager
from app.modules.database_knowledgebase.schema.introspector import DatabaseIntrospector


async def main():
    parser = argparse.ArgumentParser(description="Export Schema Cheat Sheet")
    parser.add_argument("--kb-id", required=True, help="Knowledgebase UUID")
    parser.add_argument("--sync-now", action="store_true", help="Run Schema Doc pipeline before export")
    parser.add_argument("--only-approved", action="store_true", help="Only export approved tables")
    parser.add_argument("--out-dir", default="./schema_docs", help="Output directory for markdown and json")
    args = parser.parse_args()

    kb_uuid = uuid.UUID(args.kb_id)
    secrets = get_secret_manager()

    async with AsyncSessionLocal() as session:
        kb = await session.get(DatabaseKnowledgebase, kb_uuid)
        if not kb:
            print(f"Error: Database knowledgebase '{kb_uuid}' not found.")
            sys.exit(1)

        print(f"Loaded KB: {kb.name} (tenant={kb.tenant_id})")
        config = secrets.decrypt_credentials(kb.encrypted_credentials)

        if args.sync_now:
            print("Introspecting canonical schema...")
            canonical_schema = await DatabaseIntrospector.introspect(config)
            print(f"Executing SchemaDocPipeline for {len(canonical_schema.all_tables)} tables...")
            pipeline = SchemaDocPipeline(
                session=session,
                tenant_id=kb.tenant_id,
                kb_id=kb_uuid,
                schema=canonical_schema,
                config=config,
            )
            await pipeline.execute()
            print("Pipeline execution finished.")

        print("Exporting cheat sheet...")
        result = await CheatSheetExporter.export_cheat_sheet(
            session=session,
            tenant_id=kb.tenant_id,
            kb_id=kb_uuid,
            only_approved=args.only_approved,
        )

        os.makedirs(args.out_dir, exist_ok=True)
        md_file = os.path.join(args.out_dir, f"cheat_sheet_{args.kb_id}.md")
        json_file = os.path.join(args.out_dir, f"cheat_sheet_{args.kb_id}.json")

        with open(md_file, "w", encoding="utf-8") as f:
            f.write(result["markdown"])

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(result["json_data"], f, indent=2)

        print(f"Exported successfully:")
        print(f"  Markdown: {md_file}")
        print(f"  JSON:     {json_file}")


if __name__ == "__main__":
    asyncio.run(main())
