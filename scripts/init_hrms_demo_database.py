"""Realistic 14-Table HRMS Demo PostgreSQL Database Initialization Script

Provisions an isolated, 14-table HRMS enterprise database ('gsearch_hrms_demo_db')
with primary keys, foreign keys, table and column comments, indexes, rich deterministic
business seed data, and a read-only role ('test_ro_user').
"""

import asyncio
import asyncpg
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PG_HOST = os.getenv("TEST_PG_HOST", "localhost")
PG_PORT = int(os.getenv("TEST_PG_PORT", "5433"))
PG_USER = os.getenv("TEST_PG_ADMIN_USER", "postgres")
PG_PASSWORD = os.getenv("TEST_PG_ADMIN_PASSWORD", "postgres")
DEMO_DB_NAME = os.getenv("HRMS_DEMO_DB_NAME", "gsearch_hrms_demo_db")

RO_USER = "test_ro_user"
RO_PASSWORD = "test_ro_password"


async def create_database_if_not_exists():
    """Create the HRMS demo database if it does not already exist."""
    try:
        sys_conn = await asyncpg.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            database="postgres",
        )
        exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", DEMO_DB_NAME
        )
        if not exists:
            logger.info(f"Creating HRMS demo database '{DEMO_DB_NAME}'...")
            await sys_conn.execute(f'CREATE DATABASE "{DEMO_DB_NAME}"')
            logger.info(f"Database '{DEMO_DB_NAME}' created successfully.")
        else:
            logger.info(f"Database '{DEMO_DB_NAME}' already exists.")
        await sys_conn.close()
    except Exception as e:
        logger.error(f"Error checking/creating database: {e}")
        raise


async def init_schema_and_seed():
    """Create 14 tables, constraints, comments, indexes, sample data, and read-only user."""
    conn = await asyncpg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        database=DEMO_DB_NAME,
    )

    try:
        logger.info(f"Connected to '{DEMO_DB_NAME}'. Dropping existing tables if any...")
        await conn.execute(
            """
            DROP TABLE IF EXISTS performance_reviews CASCADE;
            DROP TABLE IF EXISTS payroll_items CASCADE;
            DROP TABLE IF EXISTS payroll CASCADE;
            DROP TABLE IF EXISTS attendance CASCADE;
            DROP TABLE IF EXISTS leave_requests CASCADE;
            DROP TABLE IF EXISTS leave_types CASCADE;
            DROP TABLE IF EXISTS employee_projects CASCADE;
            DROP TABLE IF EXISTS projects CASCADE;
            DROP TABLE IF EXISTS employee_contacts CASCADE;
            DROP TABLE IF EXISTS employee_addresses CASCADE;
            DROP TABLE IF EXISTS employees CASCADE;
            DROP TABLE IF EXISTS job_titles CASCADE;
            DROP TABLE IF EXISTS departments CASCADE;
            DROP TABLE IF EXISTS locations CASCADE;
            """
        )

        logger.info("Creating 14 tables with schemas, constraints, and comments...")
        schema_sql = """
        -- 1. Locations Table
        CREATE TABLE locations (
            id SERIAL PRIMARY KEY,
            city VARCHAR(100) NOT NULL,
            state VARCHAR(100),
            country VARCHAR(100) NOT NULL,
            postal_code VARCHAR(20),
            office_address TEXT
        );
        COMMENT ON TABLE locations IS 'Corporate office locations and geographical branches';
        COMMENT ON COLUMN locations.city IS 'City where the office is located';
        COMMENT ON COLUMN locations.country IS 'Country of the corporate facility';

        -- 2. Departments Table
        CREATE TABLE departments (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            code VARCHAR(20) NOT NULL UNIQUE,
            budget DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
            location_id INT REFERENCES locations(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        COMMENT ON TABLE departments IS 'Company organizational divisions and business departments';
        COMMENT ON COLUMN departments.name IS 'Department name (e.g. Engineering, Sales, Human Resources)';
        COMMENT ON COLUMN departments.budget IS 'Annual operational budget allocated to the department';

        -- 3. Job Titles Table
        CREATE TABLE job_titles (
            id SERIAL PRIMARY KEY,
            title VARCHAR(100) NOT NULL UNIQUE,
            department_id INT NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
            min_salary DECIMAL(12, 2) NOT NULL,
            max_salary DECIMAL(12, 2) NOT NULL,
            grade VARCHAR(10) NOT NULL
        );
        COMMENT ON TABLE job_titles IS 'Catalog of job roles, salary bands, and hierarchy grades';
        COMMENT ON COLUMN job_titles.title IS 'Official corporate job title';
        COMMENT ON COLUMN job_titles.min_salary IS 'Minimum base salary for this position';
        COMMENT ON COLUMN job_titles.max_salary IS 'Maximum base salary for this position';

        -- 4. Employees Table
        CREATE TABLE employees (
            id SERIAL PRIMARY KEY,
            first_name VARCHAR(100) NOT NULL,
            last_name VARCHAR(100) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE,
            hire_date DATE NOT NULL,
            department_id INT NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
            job_title_id INT NOT NULL REFERENCES job_titles(id) ON DELETE RESTRICT,
            salary DECIMAL(12, 2) NOT NULL CHECK (salary >= 0),
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            manager_id INT REFERENCES employees(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        COMMENT ON TABLE employees IS 'Master employee registry containing personnel profile and compensation';
        COMMENT ON COLUMN employees.salary IS 'Current annual base salary';
        COMMENT ON COLUMN employees.status IS 'Employment status: active, on_leave, or terminated';
        COMMENT ON COLUMN employees.manager_id IS 'Direct reporting line manager identifier';

        -- 5. Employee Addresses Table
        CREATE TABLE employee_addresses (
            id SERIAL PRIMARY KEY,
            employee_id INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            address_line TEXT NOT NULL,
            city VARCHAR(100) NOT NULL,
            postal_code VARCHAR(20),
            is_primary BOOLEAN NOT NULL DEFAULT TRUE
        );
        COMMENT ON TABLE employee_addresses IS 'Residential physical addresses for employees';

        -- 6. Employee Contacts Table
        CREATE TABLE employee_contacts (
            id SERIAL PRIMARY KEY,
            employee_id INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            contact_type VARCHAR(50) NOT NULL,
            contact_value VARCHAR(100) NOT NULL,
            is_emergency BOOLEAN NOT NULL DEFAULT FALSE
        );
        COMMENT ON TABLE employee_contacts IS 'Contact phone numbers, emails, and emergency contacts';

        -- 7. Projects Table
        CREATE TABLE projects (
            id SERIAL PRIMARY KEY,
            name VARCHAR(150) NOT NULL UNIQUE,
            client_name VARCHAR(150),
            start_date DATE NOT NULL,
            end_date DATE,
            budget DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
            status VARCHAR(50) NOT NULL DEFAULT 'in_progress'
        );
        COMMENT ON TABLE projects IS 'Client and internal corporate projects';
        COMMENT ON COLUMN projects.budget IS 'Total project funding budget';
        COMMENT ON COLUMN projects.status IS 'Project lifecycle: in_progress, completed, planned, or cancelled';

        -- 8. Employee Projects Table (Many-to-Many Join Table)
        CREATE TABLE employee_projects (
            id SERIAL PRIMARY KEY,
            employee_id INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            project_id INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            role VARCHAR(100) NOT NULL,
            allocation_percentage INT NOT NULL DEFAULT 100,
            assigned_date DATE NOT NULL,
            UNIQUE(employee_id, project_id)
        );
        COMMENT ON TABLE employee_projects IS 'Staffing allocation mapping employees to projects';
        COMMENT ON COLUMN employee_projects.role IS 'Staff role on the project (e.g. Lead, Architect, Developer)';

        -- 9. Leave Types Table
        CREATE TABLE leave_types (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) NOT NULL UNIQUE,
            max_annual_days INT NOT NULL,
            is_paid BOOLEAN NOT NULL DEFAULT TRUE
        );
        COMMENT ON TABLE leave_types IS 'Configured PTO policies, sick leave, and parental leave';

        -- 10. Leave Requests Table
        CREATE TABLE leave_requests (
            id SERIAL PRIMARY KEY,
            employee_id INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            leave_type_id INT NOT NULL REFERENCES leave_types(id) ON DELETE RESTRICT,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            total_days INT NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'approved'
        );
        COMMENT ON TABLE leave_requests IS 'Time-off requests submitted by employees';
        COMMENT ON COLUMN leave_requests.status IS 'Approval status: pending, approved, or rejected';

        -- 11. Attendance Table
        CREATE TABLE attendance (
            id SERIAL PRIMARY KEY,
            employee_id INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            work_date DATE NOT NULL,
            check_in TIMESTAMPTZ,
            check_out TIMESTAMPTZ,
            hours_worked DECIMAL(5, 2) NOT NULL DEFAULT 8.00,
            status VARCHAR(50) NOT NULL DEFAULT 'present'
        );
        COMMENT ON TABLE attendance IS 'Daily employee shift attendance and hours recorded';

        -- 12. Payroll Table
        CREATE TABLE payroll (
            id SERIAL PRIMARY KEY,
            employee_id INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            pay_period_start DATE NOT NULL,
            pay_period_end DATE NOT NULL,
            gross_pay DECIMAL(12, 2) NOT NULL,
            deductions DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
            net_pay DECIMAL(12, 2) NOT NULL,
            payment_date DATE NOT NULL
        );
        COMMENT ON TABLE payroll IS 'Periodic employee payroll disbursements';

        -- 13. Payroll Items Table
        CREATE TABLE payroll_items (
            id SERIAL PRIMARY KEY,
            payroll_id INT NOT NULL REFERENCES payroll(id) ON DELETE CASCADE,
            item_type VARCHAR(50) NOT NULL,
            amount DECIMAL(12, 2) NOT NULL,
            description TEXT
        );
        COMMENT ON TABLE payroll_items IS 'Line-item breakdown of salaries, bonuses, and taxes per pay slip';

        -- 14. Performance Reviews Table
        CREATE TABLE performance_reviews (
            id SERIAL PRIMARY KEY,
            employee_id INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            reviewer_id INT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
            review_period VARCHAR(50) NOT NULL,
            rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comments TEXT,
            review_date DATE NOT NULL
        );
        COMMENT ON TABLE performance_reviews IS 'Annual and quarterly employee performance evaluations';
        COMMENT ON COLUMN performance_reviews.rating IS 'Performance evaluation score from 1 (poor) to 5 (exceptional)';

        -- Indexes for query optimization
        CREATE INDEX idx_emp_dept ON employees(department_id);
        CREATE INDEX idx_emp_job ON employees(job_title_id);
        CREATE INDEX idx_emp_manager ON employees(manager_id);
        CREATE INDEX idx_payroll_emp ON payroll(employee_id);
        CREATE INDEX idx_leave_emp ON leave_requests(employee_id);
        CREATE INDEX idx_att_emp_date ON attendance(employee_id, work_date);
        CREATE INDEX idx_emp_proj_emp ON employee_projects(employee_id);
        CREATE INDEX idx_emp_proj_proj ON employee_projects(project_id);
        """
        await conn.execute(schema_sql)

        logger.info("Seeding deterministic test data...")
        seed_sql = """
        -- Locations
        INSERT INTO locations (id, city, state, country, postal_code, office_address) VALUES
        (1, 'New York', 'NY', 'USA', '10001', '350 5th Ave, Floor 14'),
        (2, 'San Francisco', 'CA', 'USA', '94105', '500 Howard St'),
        (3, 'London', 'London', 'UK', 'EC2A 4NE', '100 Liverpool St'),
        (4, 'Singapore', 'Central', 'Singapore', '018989', '10 Marina Boulevard');

        -- Departments
        INSERT INTO departments (id, name, code, budget, location_id) VALUES
        (1, 'Engineering', 'ENG', 2500000.00, 2),
        (2, 'Sales & Marketing', 'SALES', 1800000.00, 1),
        (3, 'Human Resources', 'HR', 600000.00, 1),
        (4, 'Finance & Legal', 'FIN', 950000.00, 3),
        (5, 'Product & Design', 'PROD', 1200000.00, 2);

        -- Job Titles
        INSERT INTO job_titles (id, title, department_id, min_salary, max_salary, grade) VALUES
        (1, 'VP of Engineering', 1, 200000.00, 280000.00, 'L7'),
        (2, 'Staff Software Engineer', 1, 150000.00, 195000.00, 'L6'),
        (3, 'Senior Software Engineer', 1, 120000.00, 160000.00, 'L5'),
        (4, 'Software Engineer', 1, 90000.00, 125000.00, 'L4'),
        (5, 'VP of Sales', 2, 180000.00, 260000.00, 'L7'),
        (6, 'Enterprise Account Executive', 2, 100000.00, 170000.00, 'L5'),
        (7, 'Marketing Specialist', 2, 65000.00, 95000.00, 'L3'),
        (8, 'Head of People', 3, 130000.00, 180000.00, 'L6'),
        (9, 'HR Generalist', 3, 60000.00, 85000.00, 'L3'),
        (10, 'Chief Financial Officer', 4, 220000.00, 300000.00, 'L8'),
        (11, 'Senior Financial Analyst', 4, 95000.00, 135000.00, 'L5'),
        (12, 'Director of Product', 5, 170000.00, 230000.00, 'L7'),
        (13, 'Senior Product Designer', 5, 115000.00, 155000.00, 'L5');

        -- Employees (20 Realistic Profiles)
        INSERT INTO employees (id, first_name, last_name, email, hire_date, department_id, job_title_id, salary, status, manager_id) VALUES
        (1, 'Eleanor', 'Vance', 'eleanor.vance@company.com', '2024-01-15', 1, 1, 240000.00, 'active', NULL),
        (2, 'Marcus', 'Chen', 'marcus.chen@company.com', '2024-03-01', 1, 2, 185000.00, 'active', 1),
        (3, 'Sophia', 'Rodriguez', 'sophia.rodriguez@company.com', '2024-06-15', 1, 3, 145000.00, 'active', 2),
        (4, 'David', 'Kim', 'david.kim@company.com', '2025-01-10', 1, 4, 110000.00, 'active', 2),
        (5, 'Liam', 'OConnor', 'liam.oconnor@company.com', '2025-04-20', 1, 4, 105000.00, 'active', 2),
        (6, 'Victoria', 'Sterling', 'victoria.sterling@company.com', '2024-02-01', 2, 5, 225000.00, 'active', NULL),
        (7, 'James', 'Wilson', 'james.wilson@company.com', '2024-05-12', 2, 6, 140000.00, 'active', 6),
        (8, 'Amara', 'Okafor', 'amara.okafor@company.com', '2025-02-15', 2, 6, 130000.00, 'active', 6),
        (9, 'Lucas', 'Muller', 'lucas.muller@company.com', '2025-07-01', 2, 7, 78000.00, 'active', 6),
        (10, 'Chloe', 'Dubois', 'chloe.dubois@company.com', '2024-01-20', 3, 8, 155000.00, 'active', NULL),
        (11, 'Ethan', 'Hunt', 'ethan.hunt@company.com', '2025-03-10', 3, 9, 72000.00, 'active', 10),
        (12, 'Arthur', 'Pendelton', 'arthur.pendelton@company.com', '2023-11-01', 4, 10, 275000.00, 'active', NULL),
        (13, 'Nadia', 'Patel', 'nadia.patel@company.com', '2024-08-15', 4, 11, 115000.00, 'active', 12),
        (14, 'Carlos', 'Santana', 'carlos.santana@company.com', '2025-05-01', 4, 11, 108000.00, 'active', 12),
        (15, 'Maya', 'Lin', 'maya.lin@company.com', '2024-04-01', 5, 12, 195000.00, 'active', NULL),
        (16, 'Oliver', 'Twist', 'oliver.twist@company.com', '2024-09-01', 5, 13, 135000.00, 'active', 15),
        (17, 'Hannah', 'Schmidt', 'hannah.schmidt@company.com', '2025-08-15', 5, 13, 128000.00, 'active', 15),
        (18, 'Julian', 'Assange', 'julian.assange@company.com', '2026-01-05', 1, 4, 98000.00, 'active', 2),
        (19, 'Zoe', 'Kravitz', 'zoe.kravitz@company.com', '2026-02-01', 2, 7, 75000.00, 'active', 6),
        (20, 'Samuel', 'Jackson', 'samuel.jackson@company.com', '2024-07-01', 1, 3, 150000.00, 'on_leave', 2);

        -- Adjust sequence IDs
        SELECT setval('locations_id_seq', (SELECT MAX(id) FROM locations));
        SELECT setval('departments_id_seq', (SELECT MAX(id) FROM departments));
        SELECT setval('job_titles_id_seq', (SELECT MAX(id) FROM job_titles));
        SELECT setval('employees_id_seq', (SELECT MAX(id) FROM employees));

        -- Employee Addresses
        INSERT INTO employee_addresses (employee_id, address_line, city, postal_code, is_primary) VALUES
        (1, '742 Evergreen Terrace', 'San Francisco', '94105', TRUE),
        (2, '123 Market St Apt 4B', 'San Francisco', '94103', TRUE),
        (3, '456 Mission St', 'San Francisco', '94105', TRUE),
        (4, '888 Castro St', 'San Francisco', '94114', TRUE),
        (5, '101 California St', 'San Francisco', '94111', TRUE),
        (6, '15 Central Park West', 'New York', '10023', TRUE),
        (7, '432 Park Ave Apt 12A', 'New York', '10022', TRUE),
        (8, '200 Amsterdam Ave', 'New York', '10023', TRUE),
        (12, '14 Baker St', 'London', 'W1U 3BW', TRUE),
        (13, '221B Baker St', 'London', 'NW1 6XE', TRUE);

        -- Employee Contacts
        INSERT INTO employee_contacts (employee_id, contact_type, contact_value, is_emergency) VALUES
        (1, 'mobile', '+1-555-0101', FALSE),
        (1, 'emergency_phone', '+1-555-0102', TRUE),
        (2, 'mobile', '+1-555-0201', FALSE),
        (3, 'mobile', '+1-555-0301', FALSE),
        (6, 'mobile', '+1-555-0601', FALSE),
        (7, 'mobile', '+1-555-0701', FALSE),
        (12, 'mobile', '+44-20-7946-0101', FALSE);

        -- Projects
        INSERT INTO projects (id, name, client_name, start_date, end_date, budget, status) VALUES
        (1, 'Project Titan - NextGen Core', 'Internal / Enterprise', '2024-03-01', '2025-12-31', 1200000.00, 'completed'),
        (2, 'Project Apollo - AI Integration', 'FinCorp Global', '2025-01-15', '2026-06-30', 850000.00, 'in_progress'),
        (3, 'Project Hermes - Logistics Portal', 'GlobalShip Ltd', '2025-04-01', '2025-11-30', 450000.00, 'completed'),
        (4, 'Project Minerva - Risk Analytics', 'Apex Bank', '2025-09-01', '2026-10-31', 950000.00, 'in_progress'),
        (5, 'Project Vanguard - Security Audit', 'CyberDyne Defense', '2026-01-01', '2026-12-31', 600000.00, 'in_progress');
        SELECT setval('projects_id_seq', (SELECT MAX(id) FROM projects));

        -- Employee Projects (Many-to-Many assignments)
        INSERT INTO employee_projects (employee_id, project_id, role, allocation_percentage, assigned_date) VALUES
        (2, 1, 'Lead Architect', 50, '2024-03-01'),
        (2, 2, 'Principal Engineer', 50, '2025-01-15'),
        (3, 1, 'Senior Backend Dev', 100, '2024-06-15'),
        (3, 2, 'Senior Backend Dev', 50, '2025-01-15'),
        (3, 4, 'Tech Lead', 50, '2025-09-01'),
        (4, 2, 'Full Stack Dev', 100, '2025-01-15'),
        (5, 3, 'Backend Dev', 100, '2025-04-01'),
        (5, 4, 'Full Stack Dev', 100, '2025-12-01'),
        (15, 1, 'Product Director', 30, '2024-03-01'),
        (15, 2, 'Product Director', 40, '2025-01-15'),
        (16, 2, 'Lead UX Designer', 100, '2025-01-15'),
        (17, 4, 'UI Designer', 100, '2025-09-01'),
        (18, 5, 'Security Engineer', 100, '2026-01-05');

        -- Leave Types
        INSERT INTO leave_types (id, name, max_annual_days, is_paid) VALUES
        (1, 'Annual Paid Leave', 25, TRUE),
        (2, 'Sick Leave', 12, TRUE),
        (3, 'Parental Leave', 60, TRUE),
        (4, 'Unpaid Sabbatical', 90, FALSE);
        SELECT setval('leave_types_id_seq', (SELECT MAX(id) FROM leave_types));

        -- Leave Requests
        INSERT INTO leave_requests (employee_id, leave_type_id, start_date, end_date, total_days, status) VALUES
        (1, 1, '2025-07-10', '2025-07-20', 10, 'approved'),
        (2, 1, '2025-08-01', '2025-08-15', 14, 'approved'),
        (3, 2, '2025-09-12', '2025-09-14', 3, 'approved'),
        (4, 1, '2025-12-24', '2025-12-31', 7, 'approved'),
        (7, 1, '2025-06-01', '2025-06-10', 10, 'approved'),
        (8, 2, '2025-11-05', '2025-11-06', 2, 'approved'),
        (13, 1, '2025-10-15', '2025-10-22', 7, 'approved'),
        (16, 1, '2025-12-20', '2025-12-28', 8, 'approved'),
        (20, 3, '2026-01-15', '2026-03-15', 60, 'approved');

        -- Attendance (Sample for Jan-Feb 2026)
        INSERT INTO attendance (employee_id, work_date, check_in, check_out, hours_worked, status) VALUES
        (1, '2026-01-05', '2026-01-05 08:55:00+00', '2026-01-05 17:30:00+00', 8.58, 'present'),
        (1, '2026-01-06', '2026-01-06 09:02:00+00', '2026-01-06 17:00:00+00', 7.97, 'present'),
        (2, '2026-01-05', '2026-01-05 09:15:00+00', '2026-01-05 18:00:00+00', 8.75, 'present'),
        (3, '2026-01-05', '2026-01-05 09:00:00+00', '2026-01-05 17:15:00+00', 8.25, 'present'),
        (4, '2026-01-05', '2026-01-05 09:30:00+00', '2026-01-05 17:30:00+00', 8.00, 'present'),
        (5, '2026-01-05', '2026-01-05 09:05:00+00', '2026-01-05 17:05:00+00', 8.00, 'present'),
        (7, '2026-01-05', '2026-01-05 08:45:00+00', '2026-01-05 17:45:00+00', 9.00, 'present'),
        (8, '2026-01-05', NULL, NULL, 0.00, 'absent'),
        (9, '2026-01-05', '2026-01-05 09:10:00+00', '2026-01-05 17:10:00+00', 8.00, 'present'),
        (12, '2026-01-05', '2026-01-05 08:30:00+00', '2026-01-05 18:00:00+00', 9.50, 'present');

        -- Payroll (January 2026 Runs)
        INSERT INTO payroll (id, employee_id, pay_period_start, pay_period_end, gross_pay, deductions, net_pay, payment_date) VALUES
        (1, 1, '2026-01-01', '2026-01-31', 20000.00, 4200.00, 15800.00, '2026-01-31'),
        (2, 2, '2026-01-01', '2026-01-31', 15416.67, 3100.00, 12316.67, '2026-01-31'),
        (3, 3, '2026-01-01', '2026-01-31', 12083.33, 2300.00, 9783.33, '2026-01-31'),
        (4, 4, '2026-01-01', '2026-01-31', 9166.67, 1600.00, 7566.67, '2026-01-31'),
        (5, 6, '2026-01-01', '2026-01-31', 18750.00, 3900.00, 14850.00, '2026-01-31'),
        (6, 7, '2026-01-01', '2026-01-31', 11666.67, 2200.00, 9466.67, '2026-01-31'),
        (7, 12, '2026-01-01', '2026-01-31', 22916.67, 5100.00, 17816.67, '2026-01-31'),
        (8, 15, '2026-01-01', '2026-01-31', 16250.00, 3300.00, 12950.00, '2026-01-31');
        SELECT setval('payroll_id_seq', (SELECT MAX(id) FROM payroll));

        -- Payroll Items
        INSERT INTO payroll_items (payroll_id, item_type, amount, description) VALUES
        (1, 'base_salary', 20000.00, 'Monthly Base Salary'),
        (1, 'tax_deduction', -3500.00, 'Federal & State Tax'),
        (1, 'health_insurance', -700.00, 'Premium Healthcare Plan'),
        (2, 'base_salary', 15416.67, 'Monthly Base Salary'),
        (2, 'tax_deduction', -2600.00, 'Federal & State Tax'),
        (2, 'health_insurance', -500.00, 'Standard Health Plan'),
        (5, 'base_salary', 18750.00, 'Monthly Base Salary'),
        (5, 'sales_bonus', 2500.00, 'Q4 Target Achievement Commission'),
        (7, 'base_salary', 22916.67, 'Monthly Base Salary');

        -- Performance Reviews
        INSERT INTO performance_reviews (employee_id, reviewer_id, review_period, rating, comments, review_date) VALUES
        (2, 1, '2025-Annual', 5, 'Exceptional architecture leadership on Project Titan. Mentors junior team members proactively.', '2025-12-15'),
        (3, 2, '2025-Annual', 4, 'Reliable delivery on complex distributed systems and microservices.', '2025-12-16'),
        (4, 2, '2025-Annual', 4, 'Fast ramp-up on the Apollo stack with high-quality unit tests.', '2025-12-18'),
        (7, 6, '2025-Annual', 5, 'Exceeded annual enterprise quota by 130%. Closed critical healthcare account.', '2025-12-10'),
        (8, 6, '2025-Annual', 4, 'Strong pipeline execution and customer satisfaction scores.', '2025-12-12'),
        (13, 12, '2025-Annual', 5, 'Outstanding financial modeling and cost optimization for international subsidiaries.', '2025-12-14'),
        (16, 15, '2025-Annual', 4, 'Delivered sleek design system components adopted across the entire platform.', '2025-12-15');
        """
        await conn.execute(seed_sql)
        logger.info("Deterministic HRMS seed data populated successfully.")

        # 3. Configure Dedicated Read-Only User
        logger.info(f"Configuring read-only user '{RO_USER}' for '{DEMO_DB_NAME}'...")
        ro_user_sql = f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{RO_USER}') THEN
                CREATE ROLE {RO_USER} WITH LOGIN PASSWORD '{RO_PASSWORD}';
            ELSE
                ALTER ROLE {RO_USER} WITH PASSWORD '{RO_PASSWORD}';
            END IF;
        END
        $$;

        GRANT CONNECT ON DATABASE "{DEMO_DB_NAME}" TO {RO_USER};
        GRANT USAGE ON SCHEMA public TO {RO_USER};
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO {RO_USER};
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {RO_USER};
        """
        await conn.execute(ro_user_sql)
        logger.info(f"Read-only user '{RO_USER}' granted SELECT permissions on all tables in '{DEMO_DB_NAME}'.")

        # 4. Verification Check
        table_count = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
        )
        emp_count = await conn.fetchval("SELECT count(*) FROM employees;")
        logger.info(f"Verification: {table_count} tables created, {emp_count} employees seeded.")

    finally:
        await conn.close()


async def main():
    logger.info("Initializing HRMS Demo Database...")
    await create_database_if_not_exists()
    await init_schema_and_seed()
    logger.info("HRMS Demo Database initialization completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
