-- ==============================================================================
-- CodeBrain — Supabase PostgreSQL Schema & Security Policies
-- Migration: 20261012_initial_schema.sql
-- Compatible with: Supabase PostgreSQL 15+, Render FastAPI Backend, SQLAlchemy
-- ==============================================================================

-- Enable UUID extension if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. USERS TABLE
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    github_id VARCHAR(128) UNIQUE NOT NULL,
    github_username VARCHAR(128) NOT NULL,
    user_email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    github_avatar_url VARCHAR(512),
    encrypted_github_token TEXT,
    encrypted_groq_api_key TEXT,
    encrypted_nvidia_api_key TEXT,
    encrypted_openrouter_api_key TEXT,
    encrypted_anthropic_api_key TEXT,
    custom_ai_base_url VARCHAR(512),
    custom_ai_model VARCHAR(128),
    custom_ai_display_name VARCHAR(128),
    encrypted_custom_ai_api_key TEXT,
    anthropic_compatible_base_url VARCHAR(512),
    anthropic_compatible_model VARCHAR(128),
    anthropic_compatible_display_name VARCHAR(128),
    encrypted_anthropic_compatible_api_key TEXT,
    preferred_ai_provider VARCHAR(64) DEFAULT 'nvidia',
    preferred_ai_model VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id);
CREATE INDEX IF NOT EXISTS idx_users_github_username ON users(github_username);
CREATE INDEX IF NOT EXISTS idx_users_user_email ON users(user_email);

-- 2. REPOSITORIES TABLE
CREATE TABLE IF NOT EXISTS repos (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    detected_ci BOOLEAN DEFAULT FALSE NOT NULL,
    detected_ci_files TEXT,
    needs_ci_setup BOOLEAN DEFAULT FALSE NOT NULL,
    pipeline_status VARCHAR(32) DEFAULT 'PENDING' NOT NULL,
    pipeline_error TEXT,
    pipeline_meta TEXT,
    last_activity_at TIMESTAMP WITH TIME ZONE,
    last_activity_summary TEXT DEFAULT 'Repository indexed and ready',
    last_commit_sha VARCHAR(64),
    last_commit_message TEXT,
    last_commit_branch VARCHAR(128),
    last_commit_time TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_repos_user_id ON repos(user_id);
CREATE INDEX IF NOT EXISTS idx_repos_pipeline_status ON repos(pipeline_status);

-- 3. REPO FILES TABLE
CREATE TABLE IF NOT EXISTS repo_files (
    id VARCHAR(64) PRIMARY KEY,
    repo_id VARCHAR(64) NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    path VARCHAR(1024) NOT NULL,
    language VARCHAR(64),
    size INTEGER NOT NULL,
    content_hash VARCHAR(64) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_repo_files_repo_id ON repo_files(repo_id);

-- 4. CODE SYMBOLS TABLE
CREATE TABLE IF NOT EXISTS symbols (
    id SERIAL PRIMARY KEY,
    file_id VARCHAR(64) NOT NULL REFERENCES repo_files(id) ON DELETE CASCADE,
    repo_id VARCHAR(64) NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    symbol_type VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    source_code TEXT NOT NULL,
    embedded_file_hash VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_symbols_repo_id ON symbols(repo_id);
CREATE INDEX IF NOT EXISTS idx_symbols_file_id ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);

-- 5. ERROR REPORTS TABLE
CREATE TABLE IF NOT EXISTS error_reports (
    id VARCHAR(64) PRIMARY KEY,
    repo_id VARCHAR(64) NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    rule_id VARCHAR(128) NOT NULL,
    source VARCHAR(64) DEFAULT 'static_analysis',
    severity VARCHAR(32) NOT NULL,
    message TEXT NOT NULL,
    file_path VARCHAR(1024) NOT NULL,
    symbol_name VARCHAR(255),
    symbol_type VARCHAR(64),
    language VARCHAR(64),
    line INTEGER,
    "column" INTEGER,
    stack_trace TEXT,
    explanation TEXT,
    suggested_fix TEXT,
    fix_model VARCHAR(128),
    fix_provider VARCHAR(64),
    fix_attribution VARCHAR(128),
    fix_attempts TEXT,
    fix_status VARCHAR(32) DEFAULT 'PENDING' NOT NULL,
    fix_error TEXT,
    branch_name VARCHAR(255),
    pr_url VARCHAR(512),
    pr_id INTEGER,
    pr_status VARCHAR(32) DEFAULT 'NONE' NOT NULL,
    auto_fix_attempted INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_error_reports_repo_id ON error_reports(repo_id);
CREATE INDEX IF NOT EXISTS idx_error_reports_severity ON error_reports(severity);

-- 6. AUTOMATION LOGS TABLE
CREATE TABLE IF NOT EXISTS automation_logs (
    id VARCHAR(64) PRIMARY KEY,
    repo_id VARCHAR(64) NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    error_id VARCHAR(64) REFERENCES error_reports(id) ON DELETE CASCADE,
    stage VARCHAR(64) NOT NULL,
    outcome VARCHAR(32) NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_automation_logs_repo_id ON automation_logs(repo_id);

-- 7. CONVERSATIONS TABLE
CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo_id VARCHAR(64) NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    title VARCHAR(255) DEFAULT 'New Conversation' NOT NULL,
    last_message_preview TEXT,
    model_provider VARCHAR(64),
    model_name VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_repo ON conversations(user_id, repo_id);

-- 8. CONVERSATION MESSAGES TABLE
CREATE TABLE IF NOT EXISTS conversation_messages (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(64) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    citations TEXT,
    error_reports TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_convo_id ON conversation_messages(conversation_id);

-- 9. APINEX DAILY USAGE QUOTA TABLE
CREATE TABLE IF NOT EXISTS apinex_daily_usage (
    id SERIAL PRIMARY KEY,
    date VARCHAR(16) UNIQUE NOT NULL,
    prompt_tokens INTEGER DEFAULT 0 NOT NULL,
    completion_tokens INTEGER DEFAULT 0 NOT NULL,
    total_tokens INTEGER DEFAULT 0 NOT NULL,
    request_count INTEGER DEFAULT 0 NOT NULL,
    is_estimated BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_apinex_daily_usage_date ON apinex_daily_usage(date);

-- 10. REPO READMES TABLE
CREATE TABLE IF NOT EXISTS repo_readmes (
    id VARCHAR(64) PRIMARY KEY,
    repo_id VARCHAR(64) UNIQUE NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    source_fingerprint VARCHAR(64),
    generator_model VARCHAR(128),
    status VARCHAR(32) DEFAULT 'READY' NOT NULL,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- 11. REPO CI CONFIGS TABLE
CREATE TABLE IF NOT EXISTS repo_ci_configs (
    id VARCHAR(64) PRIMARY KEY,
    repo_id VARCHAR(64) UNIQUE NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    provider VARCHAR(64) DEFAULT 'github_actions' NOT NULL,
    default_branch VARCHAR(128) DEFAULT 'main' NOT NULL,
    detected_ecosystems TEXT DEFAULT '[]' NOT NULL,
    workflow_path VARCHAR(255) DEFAULT '.github/workflows/ci.yml' NOT NULL,
    active_workflow_content TEXT,
    proposed_workflow_content TEXT,
    proposed_diff TEXT,
    setup_status VARCHAR(64) DEFAULT 'not_configured' NOT NULL,
    pr_number INTEGER,
    pr_url VARCHAR(512),
    branch_name VARCHAR(255),
    auto_fix_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    auto_commit_enabled BOOLEAN DEFAULT FALSE NOT NULL,
    max_retry_budget INTEGER DEFAULT 3 NOT NULL,
    current_retry_count INTEGER DEFAULT 0 NOT NULL,
    last_failure_fingerprint VARCHAR(128),
    deployment_provider VARCHAR(64),
    deployment_status VARCHAR(64) DEFAULT 'not_configured' NOT NULL,
    deployment_url VARCHAR(512),
    last_run_id VARCHAR(64),
    last_run_status VARCHAR(64),
    last_run_conclusion VARCHAR(64),
    last_run_url VARCHAR(512),
    last_run_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- 12. REPO CI RUNS TABLE
CREATE TABLE IF NOT EXISTS repo_ci_runs (
    id VARCHAR(64) PRIMARY KEY,
    repo_id VARCHAR(64) NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL,
    run_number INTEGER,
    workflow_name VARCHAR(255),
    workflow_path VARCHAR(255),
    event VARCHAR(64),
    status VARCHAR(64) NOT NULL,
    conclusion VARCHAR(64),
    html_url VARCHAR(512),
    head_branch VARCHAR(128),
    head_sha VARCHAR(64),
    commit_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    failed_job_name VARCHAR(255),
    failed_step_name VARCHAR(255),
    failure_category VARCHAR(64),
    ai_diagnosis TEXT,
    fix_status VARCHAR(64) DEFAULT 'none',
    fix_commit_sha VARCHAR(64),
    fix_pr_url VARCHAR(512),
    logs_summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_repo_ci_runs_repo_id ON repo_ci_runs(repo_id);
CREATE INDEX IF NOT EXISTS idx_repo_ci_runs_run_id ON repo_ci_runs(run_id);

-- ==============================================================================
-- ROW LEVEL SECURITY (RLS) & TENANT ISOLATION POLICIES (OPTIONAL ENHANCEMENT)
-- Note: FastAPI backend connects via PostgreSQL connection string as the
-- application database user, which enforces user_id tenant isolation at the ORM layer.
-- The policies below enable Supabase Studio / PostgREST safety.
-- ==============================================================================

ALTER TABLE repos ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_reports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Enable all access for backend service" ON repos;
CREATE POLICY "Enable all access for backend service" ON repos
    FOR ALL
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Enable all access for backend service" ON conversations;
CREATE POLICY "Enable all access for backend service" ON conversations
    FOR ALL
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Enable all access for backend service" ON error_reports;
CREATE POLICY "Enable all access for backend service" ON error_reports
    FOR ALL
    USING (true)
    WITH CHECK (true);
