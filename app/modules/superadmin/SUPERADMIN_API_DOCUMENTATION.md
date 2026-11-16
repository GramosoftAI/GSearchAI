# GSearchAI — SuperAdmin Backend API & Architecture Documentation

## 1. Architecture & Design Principles

The **SuperAdmin** module (`app/modules/superadmin/`) is an enterprise-grade, platform-level administration system designed to grant platform operators complete, secure, and audited control over all customer organizations (tenants), users, AI agents, knowledgebases, background ingestion pipelines, and platform infrastructure.

### 1.1 Core Architectural Invariants

1. **Independent Platform Identity**:
   - SuperAdmin accounts exist in their own dedicated table (`superadmin_users`), completely decoupled from standard customer users (`users`).
   - Platform administrators are **never** simply customer users with `is_admin = true`.
2. **PostgreSQL RLS Bypass Mechanism**:
   - Customer users are strictly constrained by PostgreSQL Row-Level Security (RLS) to their respective `tenant_id`.
   - SuperAdmin requests utilize `get_superadmin_db`, which executes:
     ```sql
     SELECT set_config('app.is_superadmin', 'true', false);
     ```
   - All tenant table policies check:
     ```sql
     USING (current_setting('app.is_superadmin', true) = 'true' OR tenant_id = current_setting('app.current_tenant_id', true)::uuid)
     ```
   - This enables SuperAdmin cross-tenant visibility without disabling RLS or introducing security regressions.
3. **Defense-in-Depth Security**:
   - **Password Hashing**: Bcrypt with auto-salting.
   - **Multi-Factor Authentication (MFA)**: Pure-Python RFC 6238 TOTP engine generating QR codes (`otpauth://`) and hashed recovery backup codes.
   - **Passkeys / WebAuthn**: FIDO2 challenge issuance and public key credential registration/authentication.
   - **Account Lockout**: 5 failed attempts trigger an automatic 15-minute account lockout with exponential backoff.
   - **IP Allowlisting**: Optional CIDR subnet and exact IP access filtering.
   - **Session Lifecycle & Revocation**: Multi-device session tracking with instant single-device or global ("logout-all") revocation.
   - **Step-Up Authentication**: High-impact administrative actions (ownership transfers, tenant migration, database purges, maintenance) require re-authentication within a 10-minute elevation window.
4. **Restricted Customer Data Access & Mandatory Auditing**:
   - Customer document content, raw embeddings, and database rows are **never** automatically exposed to standard administrator roles.
   - Viewing customer knowledge content requires the explicit permission scope `kb:read_content` (or `SUPERADMIN_ROOT`) and triggers an immutable security audit event.
   - Every administrative action affecting customer accounts, agents, or knowledgebases records: actor, target resource, tenant, reason, timestamp, IP, and outcome.

---

## 2. Security & RBAC Model

### 2.1 Role Hierarchy

| Role Identifier | Display Name | Responsibility |
| :--- | :--- | :--- |
| `SUPERADMIN_ROOT` | Platform Root Owner | Unrestricted platform control. Bypasses all role checks, holds all scopes (`*`), and can manage platform roles, security policies, and administrative staff. |
| `SUPER_ADMIN` | Platform Administrator | Standard operational management across tenants, users, AI agents, KBs, and integrations. |
| `PLATFORM_OPERATOR` | Systems & Operations | Infrastructure monitoring, health probes, background job retries, and maintenance operations. |
| `SUPPORT_AUDITOR` | Support & Compliance | Read-only inspection of tenants, users, and audit logs for customer support and security compliance. |
| `BILLING_ADMIN` | Billing & Analytics | Management of plans, tiers, rate limits, token quotas, and financial cost attribution. |

### 2.2 Permission Scopes Catalog

| Scope | Category | Description |
| :--- | :--- | :--- |
| `*` | Root | Universal platform authority across all endpoints |
| `orgs:read` | Organizations | View customer organizations and operational status |
| `orgs:write` | Organizations | Create and update customer organizations, tiers, and quotas |
| `orgs:suspend` | Organizations | Suspend or reactivate customer organizations |
| `orgs:delete` | Organizations | Soft-delete or purge customer organizations |
| `users:read` | Users | View users across all customer organizations |
| `users:write` | Users | Update user status, preferences, and organization roles |
| `users:impersonate`| Users | Generate temporary scoped impersonation tokens |
| `users:delete` | Users | Deactivate or delete customer user accounts |
| `agents:read` | AI Agents | View all AI agents, configurations, and health |
| `agents:write` | AI Agents | Modify agent status, prompts, and personality settings |
| `agents:transfer` | AI Agents | Transfer agent ownership across users or organizations |
| `agents:delete` | AI Agents | Deactivate or remove customer AI agents |
| `kb:read` | KnowledgeBases | Inspect document KBs, database KBs, and metadata |
| `kb:read_content` | KnowledgeBases | **Audited** inspection of raw document chunks, table rows, and entities |
| `kb:write` | KnowledgeBases | Trigger re-indexing, re-parsing, or sync jobs |
| `kb:maintenance` | KnowledgeBases | Trigger database maintenance, vector vacuuming, and cleanup |
| `kb:delete` | KnowledgeBases | Deactivate or purge customer knowledgebases |
| `integrations:read`| Integrations | Inspect Google Drive, Slack, and SharePoint connections |
| `integrations:manage`| Integrations | Configure OAuth credentials and enterprise connectors |
| `usage:read` | Usage & Billing | View API volume, token throughput, and financial spend |
| `quotas:manage` | Usage & Billing | Adjust tenant LLM token quotas and rate limits |
| `billing:manage` | Usage & Billing | Configure plans, tiers, and pricing models |
| `system:read` | Operations | Inspect database, Redis, vector index, and worker health |
| `system:config` | Operations | View and update runtime platform configuration flags |
| `system:maintenance`| Operations | Trigger background workers and system diagnostics |
| `audit:read` | Audit Trail | Search, view, and filter administrative audit logs |
| `audit:export` | Audit Trail | Export compliance audit records to CSV/JSON |
| `security:manage` | Security | Enforce platform MFA, password policies, and IP allowlists |
| `admins:read` | Staff | List platform SuperAdmin staff accounts |
| `admins:write` | Staff | Create, update, or revoke SuperAdmin staff accounts |
| `roles:manage` | Security | Create and modify custom roles and permission scopes |

---

## 3. Complete API Endpoint Reference

Mounted Base URL: `/api/v1/superadmin`

### Section 1: Authentication & Access Control

#### `POST /api/v1/superadmin/auth/login`
- **Description**: Authenticate with email and password. If MFA is enabled, returns an `mfa_pending_token`. Tracks login history, IP, and increments failed attempts toward lockout.
- **Request Body**:
  ```json
  {
    "email": "admin@gsearch.ai",
    "password": "SecurePassword123!"
  }
  ```
- **Responses**:
  - `200 OK` (MFA Disabled): Returns `access_token`, `refresh_token`, session info, and user profile.
  - `200 OK` (MFA Enabled):
    ```json
    {
      "status": "success",
      "data": {
        "mfa_required": true,
        "mfa_pending_token": "eyJhbGciOi...",
        "supported_mfa_methods": ["totp", "webauthn"]
      }
    }
    ```
  - `401 Unauthorized`: Invalid credentials.
  - `423 Locked`: Account is locked due to repeated failed login attempts.

#### `POST /api/v1/superadmin/auth/mfa/verify`
- **Description**: Complete multi-factor challenge using TOTP code or backup code.
- **Request Body**:
  ```json
  {
    "mfa_pending_token": "eyJhbGciOi...",
    "code": "123456",
    "is_backup_code": false
  }
  ```

#### `POST /api/v1/superadmin/auth/refresh`
- **Description**: Exchange a valid refresh token for a fresh 30-minute access token.
- **Request Body**:
  ```json
  {
    "refresh_token": "eyJhbGciOi..."
  }
  ```

#### `GET /api/v1/superadmin/auth/me`
- **Description**: Retrieve authenticated administrator profile, roles, permissions, MFA state, and session details.
- **Headers**: `Authorization: Bearer <access_token>`

#### `POST /api/v1/superadmin/auth/logout`
- **Description**: Revoke current session and access token.

#### `POST /api/v1/superadmin/auth/logout-all`
- **Description**: Revoke all active sessions across all devices for the current administrator.

#### `POST /api/v1/superadmin/auth/change-password`
- **Description**: Update administrator password. Revokes all other sessions.

#### `GET /api/v1/superadmin/auth/sessions`
- **Description**: List all active administrative sessions with device information, IP address, user-agent, last active timestamp, and current session flag.

#### `DELETE /api/v1/superadmin/auth/sessions/{session_id}`
- **Description**: Revoke a specific active administrative session by ID.

#### `POST /api/v1/superadmin/auth/step-up`
- **Description**: Elevate current session for sensitive operations (valid for 10 minutes).
- **Request Body**:
  ```json
  {
    "password": "SecurePassword123!",
    "totp_code": "123456"
  }
  ```

#### `POST /api/v1/superadmin/auth/mfa/totp/setup`
- **Description**: Generate a new RFC 6238 TOTP secret, QR code URI (`otpauth://`), and recovery backup codes.
- **Response**:
  ```json
  {
    "secret": "JBSWY3DPEHPK3PXP",
    "otpauth_uri": "otpauth://totp/GSearchAI%20Platform:admin@gsearch.ai?secret=JBSWY3DPEHPK3PXP&issuer=GSearchAI%20Platform",
    "backup_codes": ["ABCD-1234", "EFGH-5678", "..."]
  }
  ```

#### `POST /api/v1/superadmin/auth/mfa/totp/enable`
- **Description**: Verify the generated TOTP code to officially activate MFA on the account.

#### `POST /api/v1/superadmin/auth/mfa/totp/disable`
- **Description**: Deactivate TOTP MFA (requires password confirmation).

#### WebAuthn / Passkey Endpoints
- `POST /api/v1/superadmin/auth/webauthn/register/options`: Generate FIDO2 credential registration challenge.
- `POST /api/v1/superadmin/auth/webauthn/register/verify`: Verify and register WebAuthn public key.
- `POST /api/v1/superadmin/auth/webauthn/login/options`: Issue WebAuthn authentication challenge.
- `POST /api/v1/superadmin/auth/webauthn/login/verify`: Verify WebAuthn signature and issue tokens.
- `GET /api/v1/superadmin/auth/webauthn/credentials`: List registered security keys / passkeys.
- `DELETE /api/v1/superadmin/auth/webauthn/credentials/{credential_id}`: Remove registered security key.

#### Account Recovery & Security Settings
- `POST /api/v1/superadmin/auth/password-reset/request`: Request password recovery email with 15-minute token.
- `POST /api/v1/superadmin/auth/password-reset/confirm`: Reset password with recovery token.
- `PUT /api/v1/superadmin/auth/ip-allowlist`: Configure allowed IP addresses or CIDR subnets (e.g., `["192.168.1.0/24", "10.0.0.5"]`).
- `GET /api/v1/superadmin/auth/login-history`: Inspect historical login attempts (Success, Failed, Locked, MFA Challenged, Blocked IP).

---

### Section 2: Role Hierarchy & Configurable Scopes

#### `GET /api/v1/superadmin/roles/permissions`
- **Description**: Returns the master catalog of all available platform permission scopes grouped by category.

#### `GET /api/v1/superadmin/roles`
- **Description**: List all platform roles (system built-in and custom roles) with assigned permission scopes.

#### `POST /api/v1/superadmin/roles`
- **Description**: Create a new custom platform administrative role with fine-grained scopes.
- **Requires**: `SUPERADMIN_ROOT` or `roles:manage`
- **Request Body**:
  ```json
  {
    "role_name": "TIER1_SUPPORT",
    "description": "Tier 1 customer support with user and KB read permissions",
    "permissions": ["users:read", "kb:read", "audit:read"]
  }
  ```

#### `GET /api/v1/superadmin/roles/{role_id}`
- **Description**: Get role definition by UUID.

#### `PUT /api/v1/superadmin/roles/{role_id}`
- **Description**: Update role description or permission scopes (system roles cannot be modified).

#### `DELETE /api/v1/superadmin/roles/{role_id}`
- **Description**: Delete custom role definition.

---

### Section 3: SuperAdmin Staff Management

#### `POST /api/v1/superadmin/admins`
- **Description**: Provision a new platform administrator account.
- **Requires**: `SUPERADMIN_ROOT` or `admins:write`
- **Request Body**:
  ```json
  {
    "email": "ops-lead@gsearch.ai",
    "full_name": "Operations Lead",
    "password": "InitialSecurePassword123!",
    "role": "PLATFORM_OPERATOR",
    "permissions": ["system:*", "kb:write", "kb:maintenance"]
  }
  ```

#### `GET /api/v1/superadmin/admins`
- **Description**: List all platform administrators with roles, MFA status, lockout status, and creation timestamps.

#### `GET /api/v1/superadmin/admins/{admin_id}`
- **Description**: Get details of an administrative account.

#### `PUT /api/v1/superadmin/admins/{admin_id}`
- **Description**: Update staff account (role, permissions, active state, IP allowlist).

#### `DELETE /api/v1/superadmin/admins/{admin_id}`
- **Description**: Deactivate or remove administrator account.

---

### Section 4: Master Dashboard, Metrics & Widgets

#### `GET /api/v1/superadmin/dashboard/overview`
- **Description**: Centralized platform telemetry aggregating 11 core metrics across all customer organizations:
  1. Total registered organizations (tenants).
  2. Total registered users.
  3. Active, suspended, and inactive organizations.
  4. Active and inactive users.
  5. Total AI agents.
  6. Total knowledgebases.
  7. Total connected integrations.
  8. Total documents and ingestion jobs.
  9. Platform-wide API request statistics.
  10. Recent administrative activities.
  11. System health and service availability.
- **Query Parameters**:
  - `start_date`, `end_date`: Date range filters.
  - `tenant_id`: Optional filter for single-tenant overview.

#### `GET /api/v1/superadmin/dashboard/health`
- **Description**: Real-time service availability probes:
  - **PostgreSQL**: Ping latency (ms), connection pool stats.
  - **Redis Cache & Queue**: Latency (ms), memory usage.
  - **Vector DB (pgvector)**: Embedding index status.
  - **Background Workers**: Temporal / ARQ queue status.

#### `GET /api/v1/superadmin/dashboard/usage-summary`
- **Description**: Platform-wide time-series API requests, total tokens consumed, cost USD, and latency metrics.

#### Dashboard Widgets CRUD (`/dashboard/widgets`)
- `GET /api/v1/superadmin/dashboard/widgets`: List saved dashboard widgets and layout arrangement.
- `POST /api/v1/superadmin/dashboard/widgets`: Create a customizable widget (metric card, line chart, bar chart, donut chart).
- `GET /api/v1/superadmin/dashboard/widgets/{widget_id}`: Get widget configuration.
- `PUT /api/v1/superadmin/dashboard/widgets/{widget_id}`: Update widget title, position, dimensions, or filters.
- `DELETE /api/v1/superadmin/dashboard/widgets/{widget_id}`: Remove dashboard widget.

---

### Section 5: Customer User Management Across All Tenants

#### `GET /api/v1/superadmin/users`
- **Description**: View all registered users across all customer tenants with multi-field search and filters.
- **Query Parameters**:
  - `search`: Case-insensitive substring match against email, full name, or user UUID.
  - `tenant_id`: Filter by customer organization UUID.
  - `role`: Filter by tenant role (`admin`, `user`).
  - `is_active`: Filter by active state (`true`, `false`).
  - `is_locked`: Filter by temporary lock status.
  - `page`, `page_size`: Pagination parameters.

#### `GET /api/v1/superadmin/users/{user_id}`
- **Description**: View complete customer user profile, organization info, account creation date, last login timestamp, lock details, and active status.

#### `POST /api/v1/superadmin/users/{user_id}/status`
- **Description**: Activate or deactivate customer account with mandatory audit reason.
- **Request Body**:
  ```json
  {
    "is_active": false,
    "reason": "Customer offboarding requested by primary tenant admin"
  }
  ```

#### `POST /api/v1/superadmin/users/{user_id}/lock`
- **Description**: Temporarily lock a customer user account (prevents login until `locked_until`).
- **Request Body**:
  ```json
  {
    "lock_minutes": 60,
    "reason": "Suspicious login pattern detected from foreign IP"
  }
  ```

#### `POST /api/v1/superadmin/users/{user_id}/unlock`
- **Description**: Immediately unlock a locked customer user account.

#### `POST /api/v1/superadmin/users/{user_id}/password-reset`
- **Description**: Trigger password-reset recovery workflow for customer user.

#### `POST /api/v1/superadmin/users/{user_id}/revoke-sessions`
- **Description**: Instantly blacklist all active refresh tokens and revoke all active customer user sessions.

#### `PUT /api/v1/superadmin/users/{user_id}/role`
- **Description**: Change customer user's role within their tenant (`admin` or `user`).

#### `POST /api/v1/superadmin/users/{user_id}/transfer-tenant`
- **Description**: Transfer a customer user to another organization.
- **Security Guard**: Requires `SUPERADMIN_ROOT`, `require_step_up_auth`, and an `authorization_reference`. Automatically revokes previous tenant sessions and tokens to eliminate cross-tenant data leakage risks.
- **Request Body**:
  ```json
  {
    "target_tenant_id": "8bbca615-1a8c-4bc7-b8db-41712a439df6",
    "authorization_reference": "SEC-TICKET-99231",
    "reason": "Authorized corporate restructuring"
  }
  ```

#### `GET /api/v1/superadmin/users/{user_id}/usage`
- **Description**: View user-specific AI consumption: total queries, input/output/embedding tokens, estimated USD cost, and model breakdown.

#### `GET /api/v1/superadmin/users/{user_id}/activity`
- **Description**: View user audit trail: queries executed, chat sessions opened, and administrative interventions.

---

### Section 6: AI Agent Governance

#### `GET /api/v1/superadmin/agents`
- **Description**: View all AI agents across all customer organizations with operational indicators.
- **Query Parameters**:
  - `search`: Match agent name, description, personality, brand persona.
  - `tenant_id`: Filter by organization UUID.
  - `user_id`: Filter by creator user UUID.
  - `is_active`: Filter by active status.
  - `agent_type`: Filter by `platform` or `integrated`.
  - `has_errors`: Filter only agents with errors in the last 24 hours.
  - `page`, `page_size`: Pagination.
- **Returns**: Paginated agents including associated knowledgebase counts, total queries, 24h error count, and health indicator (`HEALTHY`, `WARNING`, `CRITICAL`).

#### `GET /api/v1/superadmin/agents/analytics/failing`
- **Description**: Automatically identify and rank AI agents experiencing repeated errors or failure rate spikes.
- **Query Parameters**:
  - `threshold`: Minimum error count (default: 3).
  - `timeframe_hours`: Analysis window in hours (default: 24).

#### `GET /api/v1/superadmin/agents/{agent_id}`
- **Description**: Inspect complete agent configuration:
  - System prompts, personality settings, contact info, brand persona.
  - Associated document knowledgebases and database knowledgebases.
  - Query volume, tokens consumed, cost USD, average latency, and health status.

#### `PUT /api/v1/superadmin/agents/{agent_id}/status`
- **Description**: Activate or deactivate an AI agent.
- **Request Body**:
  ```json
  {
    "is_active": false,
    "reason": "Agent prompt generating repetitive hallucinations"
  }
  ```

#### `GET /api/v1/superadmin/agents/{agent_id}/health`
- **Description**: Inspect agent operational health score, 24h query volume, success rate percentage, recent error stack traces, and failure categorization.

#### `GET /api/v1/superadmin/agents/{agent_id}/usage`
- **Description**: Detailed telemetry: total chat sessions, query count, token breakdown (LLM input, output, embedding), total cost USD, and average latency (ms).

#### `PUT /api/v1/superadmin/agents/{agent_id}/transfer-owner`
- **Description**: Transfer agent ownership to another user or customer organization.
- **Security Guard**: Requires `agents:transfer` permission, `require_step_up_auth`, and `authorization_reference`. Updates associated knowledgebases on cross-tenant moves.
- **Request Body**:
  ```json
  {
    "new_user_id": "0df8ec54-4a44-4f40-8480-1a79854ef72d",
    "target_tenant_id": "8bbca615-1a8c-4bc7-b8db-41712a439df6",
    "authorization_reference": "CHANGE-REQ-4421",
    "reason": "Reassigning agent to department lead"
  }
  ```

---

### Section 7: Knowledgebase & Ingestion Administration

#### `GET /api/v1/superadmin/knowledgebases`
- **Description**: View all customer knowledgebases (both Document KBs and Relational Database KBs) across organizations.
- **Query Parameters**:
  - `search`: Filter by name, description, canonical name.
  - `tenant_id`: Filter by customer organization.
  - `agent_id`: Filter by associated AI agent.
  - `kb_type`: Filter by `document` or `database`.
  - `source`: Filter by source type (`user_upload`, `postgresql`, `sqlite`, etc.).
  - `is_active`: Filter by active status.
  - `page`, `page_size`: Pagination.

#### `GET /api/v1/superadmin/knowledgebases/analytics/storage`
- **Description**: Platform-wide storage consumption analytics:
  - Total document KBs and database KBs.
  - Total chunks in PostgreSQL (`document_chunks`).
  - Total table rows (`document_table_rows`).
  - Total extracted entities (`document_entities`).
  - Total document sections (`document_sections`).
  - Top 10 customer organizations ranked by total chunks and storage.

#### `GET /api/v1/superadmin/knowledgebases/jobs`
- **Description**: Inspect asynchronous background processing jobs (`ProcessingJob`) across all tenants with progress %, current step, and error messages.

#### `GET /api/v1/superadmin/knowledgebases/ingestion-runs`
- **Description**: View synchronization history, extraction telemetry, chunk counts, model names, repair counts, and token costs from `DocumentIngestionRun`.

#### `GET /api/v1/superadmin/knowledgebases/ingestion-runs/failures`
- **Description**: Dedicated monitor for all failed ingestion runs across customer organizations.

#### `GET /api/v1/superadmin/knowledgebases/{kb_id}`
- **Description**: Detailed inspection of a knowledgebase: metadata, aliases, file hash, S3 paths, parsed paths, dataset schema, and storage breakdown. Database credentials are sanitized with zero leakage.

#### `GET /api/v1/superadmin/knowledgebases/{kb_id}/content`
- **CRITICAL SECURITY ENDPOINT**: **Customer document content and knowledge data are strictly restricted.**
- **Security Guard**: Requires explicit `kb:read_content` permission.
- **Audit Requirement**: Every access is immediately logged in the platform security audit trail (`VIEW_KB_CONTENT`).
- **Query Parameters**:
  - `content_type`: `chunks` (default), `tables`, `entities`, or `sections`.
  - `page`, `page_size`: Pagination.

#### `POST /api/v1/superadmin/knowledgebases/jobs/{job_id}/retry`
- **Description**: Retry a failed processing job or document ingestion run. Resets status to `queued`, progress to 0, clears errors, and re-enqueues into the background worker.

#### `POST /api/v1/superadmin/knowledgebases/jobs/{job_id}/cancel`
- **Description**: Cancel a stuck or unwanted background processing job. Aborts active ARQ tasks in Redis and marks the job as `cancelled`.

#### `POST /api/v1/superadmin/knowledgebases/{kb_id}/maintenance`
- **Description**: Execute authorized maintenance operations on a knowledgebase.
- **Security Guard**: Requires `kb:maintenance` and Step-Up Authentication.
- **Supported Operations**:
  - `generate_noisy_words`: Run DF-based noise word extraction and cache invalidation.
  - `cleanup_orphaned_chunks`: Purge empty or corrupted chunk records.
  - `purge_failed_runs`: Clean up stale failed ingestion run records.
- **Request Body**:
  ```json
  {
    "operation": "generate_noisy_words",
    "reason": "Recalibrating stop words after large document batch upload"
  }
  ```

#### `DELETE /api/v1/superadmin/knowledgebases/{kb_id}`
- **Description**: Soft-deactivate (`is_active = false`) or permanently purge (`hard_delete = true`) a knowledgebase.
- **Security Guard**: Requires `kb:delete` and Step-Up Authentication.

#### `PUT /api/v1/superadmin/knowledgebases/{kb_id}/reassign`
- **Description**: Reassign knowledgebase ownership to another user or link to another AI agent within authorized boundaries.

---

### Section 8: Centralized Platform Audit Trail

#### `GET /api/v1/superadmin/audit-logs`
- **Description**: Search, filter, and review the immutable platform audit trail.
- **Query Parameters**:
  - `admin_id`: Filter by actor SuperAdmin.
  - `target_tenant_id`: Filter by target customer organization.
  - `resource_type`: Filter by resource (`agent`, `knowledgebase`, `customer_user`, `superadmin_user`, etc.).
  - `action`: Filter by action verb (`ACTIVATE_AGENT`, `VIEW_KB_CONTENT`, `LOCK_USER`, etc.).
  - `status`: `SUCCESS` or `FAILURE`.
  - `start_date`, `end_date`: Date range.
  - `page`, `page_size`: Pagination.

#### `POST /api/v1/superadmin/audit-logs`
- **Description**: Explicitly record a custom administrative audit event.

#### `GET /api/v1/superadmin/audit-logs/{log_id}`
- **Description**: Retrieve complete audit log entry including actor IP, user-agent, target tenant, and JSON execution details.

---

## 4. Usage Workflow Examples

### 4.1 Administrator Login with TOTP MFA

```bash
# Step 1: Submit Login Credentials
curl -X POST https://api.gsearch.ai/api/v1/superadmin/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "superadmin@gsearch.ai",
    "password": "RootSecurePassword2026!"
  }'

# Response requires MFA verification:
# {
#   "status": "success",
#   "data": {
#     "mfa_required": true,
#     "mfa_pending_token": "eyJhbGciOi...",
#     "supported_mfa_methods": ["totp"]
#   }
# }

# Step 2: Verify TOTP Code
curl -X POST https://api.gsearch.ai/api/v1/superadmin/auth/mfa/verify \
  -H "Content-Type: application/json" \
  -d '{
    "mfa_pending_token": "eyJhbGciOi...",
    "code": "482910"
  }'

# Response returns access_token:
# {
#   "status": "success",
#   "data": {
#     "access_token": "eyJhbGciOi...",
#     "token_type": "bearer",
#     "expires_in": 1800
#   }
# }
```

### 4.2 Step-Up Authentication for Sensitive Operations

```bash
# Request Step-Up Elevation Token
curl -X POST https://api.gsearch.ai/api/v1/superadmin/auth/step-up \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "password": "RootSecurePassword2026!",
    "totp_code": "482910"
  }'

# Response:
# {
#   "status": "success",
#   "data": {
#     "step_up_token": "eyJhbGciOi...",
#     "elevated_until": "2026-11-16T17:05:00Z"
#   }
# }
```

### 4.3 Inspecting Customer Knowledgebase Content (Audited)

```bash
# Viewing raw chunks requires kb:read_content permission
curl -X GET "https://api.gsearch.ai/api/v1/superadmin/knowledgebases/550e8400-e29b-41d4-a716-446655440000/content?content_type=chunks&page=1&page_size=10" \
  -H "Authorization: Bearer <access_token>"

# Response:
# {
#   "status": "success",
#   "data": {
#     "kb_id": "550e8400-e29b-41d4-a716-446655440000",
#     "kb_name": "Q3 Financials",
#     "tenant_name": "Acme Global",
#     "content_type": "chunks",
#     "total_items": 450,
#     "audit_warning": "Viewing customer knowledgebase content has been logged in the platform security audit trail.",
#     "items": [ ... ]
#   }
# }
```

### 4.4 Retrying a Stuck Ingestion Job

```bash
curl -X POST https://api.gsearch.ai/api/v1/superadmin/knowledgebases/jobs/6a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d/retry \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Worker node network interruption resolved; restarting document pipeline"
  }'
```

---

## 5. Security Summary & Compliance

- **No Frontend Dependencies**: The entire module is strictly API-first and decoupled from the frontend presentation tier.
- **Cross-Tenant Protection**: Normal tenant requests can never access SuperAdmin endpoints due to explicit route segregation and dedicated JWT validation.
- **Tamper-Evident Audit Logging**: All administrative operations produce audit trail records that cannot be modified or deleted via API.
- **Credential Protection**: Database passwords and API secrets are encrypted at rest with AES-GCM and zero-exposed in all API payloads.

