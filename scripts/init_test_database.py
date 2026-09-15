"""Five-Table Disposable PostgreSQL Test Database Initialization Script

Provisions and seeds the isolated five-table test database (or creates it in local PostgreSQL)
with realistic relational constraints, table comments, column comments, indexes, and a dedicated
read-only database user (test_ro_user).
"""

import asyncio
import asyncpg
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Test database connection configuration
PG_HOST = os.getenv("TEST_PG_HOST", "localhost")
PG_PORT = int(os.getenv("TEST_PG_PORT", "5433"))
PG_USER = os.getenv("TEST_PG_ADMIN_USER", "postgres")
PG_PASSWORD = os.getenv("TEST_PG_ADMIN_PASSWORD", "postgres")
TEST_DB_NAME = os.getenv("TEST_PG_DB_NAME", "gsearch_test_db")

RO_USER = "test_ro_user"
RO_PASSWORD = "test_ro_password"


async def create_database_if_not_exists():
    """Create the test database if it does not already exist."""
    try:
        sys_conn = await asyncpg.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            database="postgres",
        )
        exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            logger.info(f"Creating test database '{TEST_DB_NAME}'...")
            await sys_conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
            logger.info(f"Database '{TEST_DB_NAME}' created successfully.")
        else:
            logger.info(f"Database '{TEST_DB_NAME}' already exists.")
        await sys_conn.close()
    except Exception as e:
        logger.error(f"Error checking/creating database: {e}")
        raise


async def init_schema_and_seed():
    """Create tables, constraints, comments, indexes, sample data, and read-only user."""
    conn = await asyncpg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        database=TEST_DB_NAME,
    )

    try:
        logger.info(f"Connected to test database '{TEST_DB_NAME}'. Setting up schema...")

        # 1. Clean existing tables if any
        await conn.execute(
            """
            DROP TABLE IF EXISTS payments CASCADE;
            DROP TABLE IF EXISTS order_items CASCADE;
            DROP TABLE IF EXISTS orders CASCADE;
            DROP TABLE IF EXISTS products CASCADE;
            DROP TABLE IF EXISTS customers CASCADE;
            """
        )

        # 2. Create 5 Tables with Constraints
        schema_sql = """
        -- 1. Customers Table
        CREATE TABLE customers (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            city VARCHAR(50),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        COMMENT ON TABLE customers IS 'Customer account master catalog';
        COMMENT ON COLUMN customers.id IS 'Unique customer primary key identifier';
        COMMENT ON COLUMN customers.name IS 'Full legal name of the customer';
        COMMENT ON COLUMN customers.email IS 'Verified unique customer contact email address';
        COMMENT ON COLUMN customers.city IS 'Primary customer billing city';

        -- 2. Products Table
        CREATE TABLE products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            category VARCHAR(50) NOT NULL,
            price DECIMAL(10, 2) NOT NULL CHECK (price >= 0)
        );
        COMMENT ON TABLE products IS 'Product inventory and retail pricing catalog';
        COMMENT ON COLUMN products.id IS 'Unique product primary key';
        COMMENT ON COLUMN products.name IS 'Commercial product title';
        COMMENT ON COLUMN products.category IS 'Merchandise department category';
        COMMENT ON COLUMN products.price IS 'Current retail unit price in USD';

        -- 3. Orders Table
        CREATE TABLE orders (
            id SERIAL PRIMARY KEY,
            customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            order_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            total_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00
        );
        COMMENT ON TABLE orders IS 'Customer sales orders and transaction status';
        COMMENT ON COLUMN orders.id IS 'Unique order sequence identifier';
        COMMENT ON COLUMN orders.customer_id IS 'Foreign key referencing ordering customer';
        COMMENT ON COLUMN orders.order_date IS 'UTC placement timestamp';
        COMMENT ON COLUMN orders.status IS 'Order state: PENDING, COMPLETED, CANCELLED, SHIPPED';
        COMMENT ON COLUMN orders.total_amount IS 'Total billed order monetary amount';

        -- 4. Order Items Table
        CREATE TABLE order_items (
            id SERIAL PRIMARY KEY,
            order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
            quantity INT NOT NULL CHECK (quantity > 0),
            unit_price DECIMAL(10, 2) NOT NULL
        );
        COMMENT ON TABLE order_items IS 'Line item details associated with each order';
        COMMENT ON COLUMN order_items.id IS 'Line item primary key';
        COMMENT ON COLUMN order_items.order_id IS 'Foreign key referencing parent order';
        COMMENT ON COLUMN order_items.product_id IS 'Foreign key referencing ordered product';
        COMMENT ON COLUMN order_items.quantity IS 'Quantity of items ordered';
        COMMENT ON COLUMN order_items.unit_price IS 'Locked unit price at moment of order';

        -- 5. Payments Table
        CREATE TABLE payments (
            id SERIAL PRIMARY KEY,
            order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            payment_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            amount DECIMAL(10, 2) NOT NULL CHECK (amount > 0),
            payment_status VARCHAR(20) NOT NULL DEFAULT 'SUCCESS'
        );
        COMMENT ON TABLE payments IS 'Settlement and payment records for orders';
        COMMENT ON COLUMN payments.id IS 'Payment transaction primary key';
        COMMENT ON COLUMN payments.order_id IS 'Foreign key referencing settled order';
        COMMENT ON COLUMN payments.amount IS 'Settlement amount';
        COMMENT ON COLUMN payments.payment_status IS 'Payment state: SUCCESS, FAILED, REFUNDED';

        -- Additional performance indexes
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE INDEX idx_orders_status ON orders(status);
        CREATE INDEX idx_order_items_order ON order_items(order_id);
        CREATE INDEX idx_order_items_product ON order_items(product_id);
        CREATE INDEX idx_payments_order ON payments(order_id);
        """
        await conn.execute(schema_sql)
        logger.info("Created 5 related tables, indexes, primary keys, foreign keys, and comments.")

        # 3. Seed Realistic Sample Data
        seed_sql = """
        -- Seed Customers
        INSERT INTO customers (name, email, city, created_at) VALUES
            ('Alice Johnson', 'alice.johnson@example.com', 'New York', '2026-01-15 10:00:00Z'),
            ('Bob Smith', 'bob.smith@example.com', 'San Francisco', '2026-01-16 11:30:00Z'),
            ('Charlie Davis', 'charlie.davis@example.com', 'Chicago', '2026-02-01 09:15:00Z'),
            ('Diana Prince', 'diana.prince@example.com', 'Seattle', '2026-02-10 14:20:00Z'),
            ('Evan Wright', 'evan.wright@example.com', 'Austin', '2026-02-20 16:45:00Z');

        -- Seed Products
        INSERT INTO products (name, category, price) VALUES
            ('Ergonomic Mechanical Keyboard', 'Electronics', 149.99),
            ('Wireless Noise-Cancelling Headphones', 'Electronics', 299.50),
            ('Ultra-HD 27-inch Monitor', 'Electronics', 399.00),
            ('Standing Desk Mat', 'Office Supplies', 45.00),
            ('Adjustable Lumbar Support Chair', 'Furniture', 350.00);

        -- Seed Orders
        INSERT INTO orders (customer_id, order_date, status, total_amount) VALUES
            (1, '2026-02-01 10:30:00Z', 'COMPLETED', 449.49),
            (2, '2026-02-05 15:00:00Z', 'COMPLETED', 299.50),
            (3, '2026-02-12 12:00:00Z', 'SHIPPED', 399.00),
            (4, '2026-02-18 17:30:00Z', 'COMPLETED', 395.00),
            (5, '2026-02-25 09:00:00Z', 'PENDING', 149.99);

        -- Seed Order Items
        INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
            (1, 1, 1, 149.99),
            (1, 2, 1, 299.50),
            (2, 2, 1, 299.50),
            (3, 3, 1, 399.00),
            (4, 4, 1, 45.00),
            (4, 5, 1, 350.00),
            (5, 1, 1, 149.99);

        -- Seed Payments
        INSERT INTO payments (order_id, payment_date, amount, payment_status) VALUES
            (1, '2026-02-01 10:35:00Z', 449.49, 'SUCCESS'),
            (2, '2026-02-05 15:02:00Z', 299.50, 'SUCCESS'),
            (3, '2026-02-12 12:05:00Z', 399.00, 'SUCCESS'),
            (4, '2026-02-18 17:35:00Z', 395.00, 'SUCCESS'),
            (5, '2026-02-25 09:05:00Z', 149.99, 'SUCCESS');
        """
        await conn.execute(seed_sql)
        logger.info("Sample seed data inserted across all 5 tables.")

        # 4. Provision Dedicated Read-Only Database Account (test_ro_user)
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

        GRANT CONNECT ON DATABASE "{TEST_DB_NAME}" TO {RO_USER};
        GRANT USAGE ON SCHEMA public TO {RO_USER};
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO {RO_USER};
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {RO_USER};

        -- Explicitly revoke write permissions (Defense-in-depth)
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM {RO_USER};
        """
        await conn.execute(ro_user_sql)
        logger.info(f"Read-only user '{RO_USER}' configured with strict SELECT-only privileges.")

    finally:
        await conn.close()


async def main():
    logger.info("Starting Five-Table Test Database Provisioning...")
    await create_database_if_not_exists()
    await init_schema_and_seed()
    logger.info("Five-Table Test Database Initialization COMPLETE.")


if __name__ == "__main__":
    asyncio.run(main())
