import sys
import os
import requests
import json
from datetime import timedelta

# Ensure project root is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.core.security import create_access_token

API_BASE_URL = "http://127.0.0.1:4915/api/v1/database-knowledgebases"
USER_ID = "12690c36-22d1-4aa5-92dd-a17c8d1a3ca0"
TENANT_ID = "d113ef9e-bcb5-4626-af1d-6c995bbfe4d0"

GLOSSARY_DEFINITIONS = [
    {
        "table_name": "attendance_attendance",
        "column_name": "attendance_clock_in",
        "synonyms": [
            "arrive", "arrival", "arrived", "enter", "entered", "entry", 
            "clock in", "clock-in", "clocked in", "punch in", "punched in", 
            "check in", "check-in", "checked in", "start time", "started work", "first arrived"
        ],
        "business_description": "The time of day (TIME) an employee clocked in, entered the workplace, or arrived at work.",
        "semantic_role": "event_timestamp"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "attendance_clock_out",
        "synonyms": [
            "leave", "left", "exit", "exited", "departure", "departed",
            "clock out", "clock-out", "clocked out", "punch out", "punched out",
            "check out", "check-out", "checked out", "end time", "finished work", "last left"
        ],
        "business_description": "The time of day (TIME) an employee clocked out, exited the workplace, or left work.",
        "semantic_role": "event_timestamp"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "at_work_second",
        "synonyms": [
            "duration", "how long", "time spent at work", "time at work", "working time",
            "seconds worked", "working seconds", "work duration", "hours worked",
            "daily working time", "total working time", "hours spent working", "working duration"
        ],
        "business_description": "CANONICAL NUMERIC FIELD for duration calculations, comparisons, SUM, and AVG. Total duration in seconds an employee spent at work on this day. 1 hour = 3600s, 6 hours = 21600s, 8 hours = 28800s, 10 hours = 36000s.",
        "semantic_role": "duration_metric"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "attendance_worked_hour",
        "synonyms": [
            "worked hour", "worked hours", "working hours", "daily worked hours", 
            "formatted hours", "attendance worked hour"
        ],
        "business_description": "Display duration string (VARCHAR formatted as HH:MM). Do NOT use for numeric comparisons or arithmetic; use at_work_second instead.",
        "semantic_role": "duration_string"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "attendance_date",
        "synonyms": [
            "attendance date", "date", "work date", "workday", "that day", "day", "calendar date"
        ],
        "business_description": "The calendar date (DATE, format YYYY-MM-DD) of the attendance record.",
        "semantic_role": "temporal_dimension"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "overtime_second",
        "synonyms": [
            "overtime", "overtime seconds", "overtime duration", "extra hours", "ot seconds", "overtime time"
        ],
        "business_description": "CANONICAL NUMERIC FIELD for overtime calculations. Total overtime worked in seconds on this date. 1 hour = 3600s, 10 hours = 36000s.",
        "semantic_role": "overtime_metric"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "approved_overtime_second",
        "synonyms": [
            "approved overtime", "approved ot", "total approved overtime", "approved overtime seconds"
        ],
        "business_description": "CANONICAL NUMERIC FIELD for approved overtime calculations. Total formally approved overtime in seconds.",
        "semantic_role": "overtime_metric"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "attendance_overtime",
        "synonyms": [
            "attendance overtime", "overtime hours string", "formatted overtime"
        ],
        "business_description": "Display overtime formatted as string (VARCHAR HH:MM). Do NOT use for numeric comparisons; use overtime_second instead.",
        "semantic_role": "overtime_string"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "minimum_hour",
        "synonyms": [
            "minimum required working time", "required working day", "minimum required hours", 
            "minimum working hour", "shift expected working time", "required hours"
        ],
        "business_description": "Display string (VARCHAR HH:MM, typically '08:00') for required daily working time.",
        "semantic_role": "constraint_metric"
    },
    {
        "table_name": "attendance_attendance",
        "column_name": "attendance_validated",
        "synonyms": [
            "validated", "attendance validated", "is validated", "approved attendance"
        ],
        "business_description": "Boolean flag indicating whether the attendance record has been reviewed and validated.",
        "semantic_role": "status_flag"
    },
    {
        "table_name": "employee_employee",
        "column_name": "employee_first_name",
        "synonyms": [
            "first name", "given name", "employee first name", "Ebenezar"
        ],
        "business_description": "The first name of the employee.",
        "semantic_role": "entity_name"
    },
    {
        "table_name": "employee_employee",
        "column_name": "employee_last_name",
        "synonyms": [
            "last name", "surname", "family name", "employee last name"
        ],
        "business_description": "The last name of the employee.",
        "semantic_role": "entity_name"
    },
    {
        "table_name": "employee_employee",
        "column_name": "badge_id",
        "synonyms": [
            "badge id", "badge number", "employee badge", "badge"
        ],
        "business_description": "The unique badge identification number of the employee.",
        "semantic_role": "identifier"
    },
    {
        "table_name": "employee_employee",
        "column_name": "id",
        "synonyms": [
            "employee id", "emp id", "employee identifier"
        ],
        "business_description": "The unique database primary key ID of the employee.",
        "semantic_role": "primary_key"
    },
    {
        "table_name": "attendance_attendanceactivity",
        "column_name": "clock_in",
        "synonyms": [
            "first clock-in", "session clock in", "activity clock in", "clock-in time"
        ],
        "business_description": "Clock-in time for an individual attendance activity punch session.",
        "semantic_role": "event_timestamp"
    },
    {
        "table_name": "attendance_attendanceactivity",
        "column_name": "clock_out",
        "synonyms": [
            "last clock-out", "session clock out", "activity clock out", "clock-out time"
        ],
        "business_description": "Clock-out time for an individual attendance activity punch session.",
        "semantic_role": "event_timestamp"
    }
]

import asyncio
from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
from app.modules.database_knowledgebase.semantic_glossary.feedback_loop import GlossaryFeedbackLoop
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as session:
        # Fetch all KBs
        stmt = select(DatabaseKnowledgebase)
        res = await session.execute(stmt)
        kbs = res.scalars().all()
        if not kbs:
            print("No KBs found in database!")
            return

        target_kbs = [kb for kb in kbs if "hrms" in (kb.name or "").lower() or str(kb.id) == "1a40dee5-c663-4a9f-b5e5-c44a9f0b018d"]
        if not target_kbs:
            target_kbs = kbs

        for kb in target_kbs:
            kb_id = kb.id
            tenant_id = kb.tenant_id
            schema_fingerprint = kb.schema_version or f"kb_{kb_id}"
            print(f"\nTargeting KB: '{kb.name}' (ID: {kb_id}, schema_version: {schema_fingerprint})")

            success_count = 0
            for defn in GLOSSARY_DEFINITIONS:
                entry = await GlossaryFeedbackLoop.record_human_verified_mapping(
                    session=session,
                    tenant_id=tenant_id,
                    table_name=defn["table_name"],
                    column_name=defn["column_name"],
                    schema_fingerprint=schema_fingerprint,
                    synonyms=defn["synonyms"],
                    business_description=defn["business_description"],
                    semantic_role=defn["semantic_role"],
                )
                success_count += 1
                print(f"  [OK] Confirmed & published: {defn['table_name']}.{defn['column_name']} (id={entry.id if entry else 'new'})")

            await session.commit()
            print(f"Glossary population complete for {kb.name}: {success_count}/{len(GLOSSARY_DEFINITIONS)} confirmed and published.")

if __name__ == "__main__":
    asyncio.run(main())
