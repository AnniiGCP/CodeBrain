import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger("codebrain.database")

RAW_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db").strip()

def normalize_database_url(raw_url: str) -> str:
    """
    Normalizes PostgreSQL database URLs for SQLAlchemy 2.0+ and psycopg2.
    Safely encodes special characters (like '@' or ':') in database passwords
    so that URI parsing correctly identifies the Supabase host name.
    """
    url = raw_url.strip()
    if not url or url.startswith("sqlite"):
        return url

    prefix, sep, rest = url.partition("://")
    if not sep:
        return url

    # Ensure explicit driver specification (psycopg2) for PostgreSQL
    if prefix in ("postgres", "postgresql"):
        prefix = "postgresql+psycopg2"

    # Handle special characters in password (everything before last '@' is credentials)
    if "@" in rest:
        userinfo, _, host_and_path = rest.rpartition("@")
        if ":" in userinfo:
            user, _, password = userinfo.partition(":")
            import urllib.parse
            unquoted_pw = urllib.parse.unquote_plus(password)
            quoted_pw = urllib.parse.quote_plus(unquoted_pw)
            rest = f"{user}:{quoted_pw}@{host_and_path}"
        else:
            rest = f"{userinfo}@{host_and_path}"

    return f"{prefix}://{rest}"


DATABASE_URL = normalize_database_url(RAW_DATABASE_URL)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Production PostgreSQL / Supabase connection pooling
    pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    pool_recycle = int(os.environ.get("DB_POOL_RECYCLE", "300"))
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db():
    """Create all tables and perform lightweight schema migrations across SQLite and PostgreSQL."""
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        try:
            if engine.dialect.name == "sqlite":
                res = conn.exec_driver_sql("PRAGMA table_info(repos)")
            cols = [row[1] for row in res.fetchall()]
            if cols:
                if "user_id" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN user_id VARCHAR REFERENCES users(id)")
                if "detected_ci" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN detected_ci BOOLEAN DEFAULT 0")
                if "detected_ci_files" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN detected_ci_files TEXT")
                if "needs_ci_setup" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN needs_ci_setup BOOLEAN DEFAULT 0")
                if "last_activity_at" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN last_activity_at DATETIME")
                if "last_activity_summary" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN last_activity_summary TEXT")
                if "last_commit_sha" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN last_commit_sha VARCHAR")
                if "last_commit_message" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN last_commit_message TEXT")
                if "last_commit_branch" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN last_commit_branch VARCHAR")
                if "last_commit_time" not in cols:
                    conn.exec_driver_sql("ALTER TABLE repos ADD COLUMN last_commit_time DATETIME")
                conn.commit()

            res_users = conn.exec_driver_sql("PRAGMA table_info(users)")
            user_cols = [row[1] for row in res_users.fetchall()]
            if user_cols:
                if "user_email" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN user_email VARCHAR")
                if "password_hash" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN password_hash VARCHAR")
                if "encrypted_github_token" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN encrypted_github_token TEXT")
                if "encrypted_groq_api_key" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN encrypted_groq_api_key TEXT")
                if "encrypted_nvidia_api_key" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN encrypted_nvidia_api_key TEXT")
                if "encrypted_openrouter_api_key" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN encrypted_openrouter_api_key TEXT")
                if "encrypted_anthropic_api_key" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN encrypted_anthropic_api_key TEXT")
                if "custom_ai_base_url" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN custom_ai_base_url VARCHAR")
                if "custom_ai_model" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN custom_ai_model VARCHAR")
                if "encrypted_custom_ai_api_key" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN encrypted_custom_ai_api_key TEXT")
                if "anthropic_compatible_base_url" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN anthropic_compatible_base_url VARCHAR")
                if "anthropic_compatible_model" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN anthropic_compatible_model VARCHAR")
                if "encrypted_anthropic_compatible_api_key" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN encrypted_anthropic_compatible_api_key TEXT")
                if "custom_ai_display_name" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN custom_ai_display_name VARCHAR")
                if "anthropic_compatible_display_name" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN anthropic_compatible_display_name VARCHAR")
                if "preferred_ai_provider" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN preferred_ai_provider VARCHAR DEFAULT 'nvidia'")
                if "preferred_ai_model" not in user_cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN preferred_ai_model VARCHAR")
                conn.commit()


            res_err = conn.exec_driver_sql("PRAGMA table_info(error_reports)")
            err_cols = [row[1] for row in res_err.fetchall()]
            if err_cols:
                if "source" not in err_cols:
                    conn.exec_driver_sql("ALTER TABLE error_reports ADD COLUMN source VARCHAR DEFAULT 'static_analysis'")
                if "column" not in err_cols:
                    conn.exec_driver_sql("ALTER TABLE error_reports ADD COLUMN column INTEGER")
                if "stack_trace" not in err_cols:
                    conn.exec_driver_sql("ALTER TABLE error_reports ADD COLUMN stack_trace TEXT")
                if "fix_provider" not in err_cols:
                    conn.exec_driver_sql("ALTER TABLE error_reports ADD COLUMN fix_provider VARCHAR")
                if "fix_attribution" not in err_cols:
                    conn.exec_driver_sql("ALTER TABLE error_reports ADD COLUMN fix_attribution VARCHAR")
                if "fix_attempts" not in err_cols:
                    conn.exec_driver_sql("ALTER TABLE error_reports ADD COLUMN fix_attempts TEXT")
                conn.commit()

            res_readmes = conn.exec_driver_sql("PRAGMA table_info(repo_readmes)")
            rm_cols = [row[1] for row in res_readmes.fetchall()]
            if rm_cols:
                if "source_fingerprint" not in rm_cols:
                    conn.exec_driver_sql("ALTER TABLE repo_readmes ADD COLUMN source_fingerprint VARCHAR")
                if "generator_model" not in rm_cols:
                    conn.exec_driver_sql("ALTER TABLE repo_readmes ADD COLUMN generator_model VARCHAR")
                if "status" not in rm_cols:
                    conn.exec_driver_sql("ALTER TABLE repo_readmes ADD COLUMN status VARCHAR DEFAULT 'READY'")
                if "error" not in rm_cols:
                    conn.exec_driver_sql("ALTER TABLE repo_readmes ADD COLUMN error TEXT")
                conn.commit()

            res_ciconf = conn.exec_driver_sql("PRAGMA table_info(repo_ci_configs)")
            ciconf_cols = [row[1] for row in res_ciconf.fetchall()]
            if ciconf_cols:
                if "proposed_workflow_content" not in ciconf_cols:
                    conn.exec_driver_sql("ALTER TABLE repo_ci_configs ADD COLUMN proposed_workflow_content TEXT")
                conn.commit()
            elif engine.dialect.name == "postgresql":
                pg_migrations = [
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS user_id VARCHAR REFERENCES users(id)",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS detected_ci BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS detected_ci_files TEXT",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS needs_ci_setup BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP WITH TIME ZONE",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_activity_summary TEXT",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_commit_sha VARCHAR",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_commit_message TEXT",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_commit_branch VARCHAR",
                    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_commit_time TIMESTAMP WITH TIME ZONE",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS user_email VARCHAR",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS encrypted_github_token TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS encrypted_groq_api_key TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS encrypted_nvidia_api_key TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS encrypted_openrouter_api_key TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS encrypted_anthropic_api_key TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_ai_base_url VARCHAR",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_ai_model VARCHAR",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS encrypted_custom_ai_api_key TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS anthropic_compatible_base_url VARCHAR",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS anthropic_compatible_model VARCHAR",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS encrypted_anthropic_compatible_api_key TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_ai_display_name VARCHAR",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS anthropic_compatible_display_name VARCHAR",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_ai_provider VARCHAR DEFAULT 'nvidia'",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_ai_model VARCHAR",
                    "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'static_analysis'",
                    "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS column INTEGER",
                    "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS stack_trace TEXT",
                    "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS fix_provider VARCHAR",
                    "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS fix_attribution VARCHAR",
                    "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS fix_attempts TEXT",
                    "ALTER TABLE repo_readmes ADD COLUMN IF NOT EXISTS source_fingerprint VARCHAR",
                    "ALTER TABLE repo_readmes ADD COLUMN IF NOT EXISTS generator_model VARCHAR",
                    "ALTER TABLE repo_readmes ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'READY'",
                    "ALTER TABLE repo_readmes ADD COLUMN IF NOT EXISTS error TEXT",
                    "ALTER TABLE repo_ci_configs ADD COLUMN IF NOT EXISTS proposed_workflow_content TEXT",
                    "ALTER TABLE repo_ci_configs ADD COLUMN IF NOT EXISTS proposed_diff TEXT",
                ]
                for stmt in pg_migrations:
                    try:
                        conn.exec_driver_sql(stmt)
                    except Exception as pg_err:
                        logger.debug("PostgreSQL migration note for '%s': %s", stmt, pg_err)
                conn.commit()
        except Exception as e:
            logger.warning("Database init_db encountered non-fatal migration warning: %s", e)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
