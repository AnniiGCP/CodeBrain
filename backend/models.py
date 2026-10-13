import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum, Text, Boolean
from sqlalchemy.orm import relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# Pipeline status values
PIPELINE_STATUSES = (
    "PENDING",
    "CLONING",
    "PARSING",
    "EMBEDDING",
    "ANALYZING",
    "DETECTING_ERRORS",
    "AUTO_FIXING",
    "DONE",
    "FAILED",
)

# Fix lifecycle statuses
FIX_STATUSES = ("PENDING", "GENERATING", "READY", "APPLIED", "REJECTED", "FAILED")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    github_id = Column(String, unique=True, nullable=False, index=True)
    github_username = Column(String, nullable=False, index=True)
    user_email = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=True)
    github_avatar_url = Column(String, nullable=True)
    encrypted_github_token = Column(Text, nullable=True)
    encrypted_groq_api_key = Column(Text, nullable=True)
    encrypted_nvidia_api_key = Column(Text, nullable=True)
    encrypted_openrouter_api_key = Column(Text, nullable=True)
    encrypted_anthropic_api_key = Column(Text, nullable=True)
    custom_ai_base_url = Column(String, nullable=True)
    custom_ai_model = Column(String, nullable=True)
    custom_ai_display_name = Column(String, nullable=True)
    encrypted_custom_ai_api_key = Column(Text, nullable=True)
    anthropic_compatible_base_url = Column(String, nullable=True)
    anthropic_compatible_model = Column(String, nullable=True)
    anthropic_compatible_display_name = Column(String, nullable=True)
    encrypted_anthropic_compatible_api_key = Column(Text, nullable=True)
    preferred_ai_provider = Column(String, default="nvidia", nullable=True)
    preferred_ai_model = Column(String, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    repos = relationship("Repo", back_populates="user", cascade="all, delete-orphan")

    @property
    def email(self) -> str:
        """Safe fallback author email for git operations to prevent AttributeError."""
        if self.user_email:
            return self.user_email
        username = self.github_username or "developer"
        return f"{username}@users.noreply.github.com"


class Repo(Base):
    __tablename__ = "repos"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    source_type = Column(Enum("upload", "github", name="source_type_enum"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # CI Workflow detection & setup
    detected_ci = Column(Boolean, default=False, server_default="0", nullable=False)
    detected_ci_files = Column(Text, nullable=True)
    needs_ci_setup = Column(Boolean, default=False, server_default="0", nullable=False)

    # Auto-pipeline tracking
    pipeline_status = Column(
        String,
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    pipeline_error = Column(Text, nullable=True)
    pipeline_meta = Column(Text, nullable=True)

    # Activity & Git metadata for stable History and resuming
    last_activity_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)
    last_activity_summary = Column(Text, default="Repository indexed and ready", nullable=True)
    last_commit_sha = Column(String, nullable=True)
    last_commit_message = Column(Text, nullable=True)
    last_commit_branch = Column(String, nullable=True)
    last_commit_time = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="repos")
    files = relationship("RepoFile", back_populates="repo", cascade="all, delete-orphan")
    error_reports = relationship("ErrorReport", back_populates="repo", cascade="all, delete-orphan")
    automation_logs = relationship("AutomationLog", back_populates="repo", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="repo", cascade="all, delete-orphan")
    readme = relationship("RepoReadme", back_populates="repo", uselist=False, cascade="all, delete-orphan")
    doc = relationship("RepoDoc", back_populates="repo", uselist=False, cascade="all, delete-orphan")
    ci_config = relationship("RepoCiConfig", back_populates="repo", uselist=False, cascade="all, delete-orphan")
    ci_runs = relationship("RepoCiRun", back_populates="repo", cascade="all, delete-orphan", order_by="desc(RepoCiRun.created_at)")


class RepoFile(Base):
    __tablename__ = "repo_files"

    id = Column(String, primary_key=True, default=_uuid)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False)
    path = Column(String, nullable=False)
    language = Column(String, nullable=True)
    size = Column(Integer, nullable=False)
    content_hash = Column(String, nullable=False)

    repo = relationship("Repo", back_populates="files")
    symbols = relationship("Symbol", back_populates="file", cascade="all, delete-orphan")


class Symbol(Base):
    """
    Represents a code symbol extracted from a file — function, class, method, etc.
    Each Symbol is the unit that gets embedded and stored in FAISS.
    """
    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String, ForeignKey("repo_files.id"), nullable=False)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False, index=True)

    symbol_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    source_code = Column(Text, nullable=False)

    embedded_file_hash = Column(String, nullable=True)

    file = relationship("RepoFile", back_populates="symbols")


class ErrorReport(Base):
    """
    One row per detected issue from the error-detection scanner.
    Stores the AI-generated explanation and fix diff alongside issue metadata.
    """
    __tablename__ = "error_reports"

    id = Column(String, primary_key=True, default=_uuid)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False, index=True)
    symbol_id = Column(Integer, ForeignKey("symbols.id"), nullable=True)

    # Issue metadata (mirrors the scanner's issue dict)
    rule_id = Column(String, nullable=False)
    source = Column(String, default="static_analysis", nullable=True)  # "parser" | "static_analysis" | "build" | "test"
    severity = Column(String, nullable=False)   # "error" | "warning" | "info"
    message = Column(Text, nullable=False)
    file_path = Column(String, nullable=False)
    symbol_name = Column(String, nullable=True)
    symbol_type = Column(String, nullable=True)
    language = Column(String, nullable=True)
    line = Column(Integer, nullable=True)
    column = Column(Integer, nullable=True)
    stack_trace = Column(Text, nullable=True)

    # AI-generated artefacts (populated async after detection)
    explanation = Column(Text, nullable=True)       # from explainer.py
    suggested_fix = Column(Text, nullable=True)     # unified diff from fixer.py
    fix_model = Column(String, nullable=True)
    fix_provider = Column(String, nullable=True)
    fix_attribution = Column(String, nullable=True)
    fix_attempts = Column(Text, nullable=True)

    # Fix lifecycle: PENDING → GENERATING → READY → APPLIED | REJECTED | FAILED
    fix_status = Column(String, nullable=False, default="PENDING", server_default="PENDING")
    fix_error = Column(Text, nullable=True)

    # GitOps & Auto-Fix tracking
    branch_name = Column(String, nullable=True)
    pr_url = Column(String, nullable=True)
    pr_id = Column(Integer, nullable=True)
    # pr_status: NONE | OPEN | MERGED | FAILED_PIPELINE
    pr_status = Column(String, nullable=False, default="NONE", server_default="NONE")
    auto_fix_attempted = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    repo = relationship("Repo", back_populates="error_reports")
    automation_logs = relationship("AutomationLog", back_populates="error_report", cascade="all, delete-orphan")


class AutomationLog(Base):
    """
    Chronological log of every automated fix attempt and pipeline outcome.
    """
    __tablename__ = "automation_logs"

    id = Column(String, primary_key=True, default=_uuid)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False, index=True)
    error_id = Column(String, ForeignKey("error_reports.id"), nullable=True, index=True)

    # Stage: DETECTED | FIX_GENERATED | SANDBOX_PASSED | SANDBOX_FAILED | BRANCH_PUSHED | PR_OPENED | PIPELINE_PASSED | PIPELINE_FAILED | MERGED | SKIPPED
    stage = Column(String, nullable=False)
    # Outcome: SUCCESS | FAILED | INFO
    outcome = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    repo = relationship("Repo", back_populates="automation_logs")
    error_report = relationship("ErrorReport", back_populates="automation_logs")


class Conversation(Base):
    """
    Seven-day scoped Copilot conversation container.
    Scoped to (user_id, repo_id).
    """
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False, index=True)
    title = Column(String, nullable=False, default="New Conversation")
    last_message_preview = Column(Text, nullable=True)
    model_provider = Column(String, nullable=True)
    model_name = Column(String, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    repo = relationship("Repo", back_populates="conversations")
    messages = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(Base):
    """
    Individual chat turn (user or assistant) in a Conversation.
    """
    __tablename__ = "conversation_messages"

    id = Column(String, primary_key=True, default=_uuid)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    citations = Column(Text, nullable=True)       # JSON string of citations
    error_reports = Column(Text, nullable=True)   # JSON string of attached errors

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    conversation = relationship("Conversation", back_populates="messages")


class ApinexDailyUsage(Base):
    """
    Persistent daily token quota tracking for APInex GPT-6 Luna.
    Scoped by UTC calendar day (date='YYYY-MM-DD').
    Provides persistent, transaction-safe tracking against the 315,000-token daily budget.
    """
    __tablename__ = "apinex_daily_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, unique=True, nullable=False, index=True)  # UTC date 'YYYY-MM-DD'
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    request_count = Column(Integer, default=0, nullable=False)
    is_estimated = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class RepoReadme(Base):
    """
    Stores generated Plain-Language README.md per repository.
    Tracks content, source fingerprint (revision hash), generator model, and generation status.
    """
    __tablename__ = "repo_readmes"

    id = Column(String, primary_key=True, default=_uuid)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False, unique=True, index=True)
    content = Column(Text, nullable=False)
    source_fingerprint = Column(String, nullable=True)
    generator_model = Column(String, nullable=True)
    status = Column(String, default="READY", nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    repo = relationship("Repo", back_populates="readme")


class RepoDoc(Base):
    """
    Stores the full canonical 16-section technical documentation suite per repository in database.
    Enforces permanence across cloud container restarts and browser refreshes.
    """
    __tablename__ = "repo_docs"

    id = Column(String, primary_key=True, default=_uuid)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False, unique=True, index=True)
    commit_sha = Column(String, default="HEAD", nullable=False)
    doc_version = Column(String, default="v1.6", nullable=False)
    is_complete = Column(Boolean, default=False, nullable=False)
    master_content = Column(Text, nullable=False)
    sections_json = Column(Text, nullable=False)  # JSON-encoded array of sections
    manifest_json = Column(Text, nullable=True)   # JSON-encoded documentation manifest
    validation_summary_json = Column(Text, nullable=True)  # JSON-encoded validation summary
    source_fingerprint = Column(String, nullable=True)
    status = Column(String, default="READY", nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    repo = relationship("Repo", back_populates="doc")


class RepoCiConfig(Base):
    """
    Persistent CI/CD and deployment configuration per repository.
    Enforces absolute isolation between repositories.
    """
    __tablename__ = "repo_ci_configs"

    id = Column(String, primary_key=True, default=_uuid)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False, unique=True, index=True)
    provider = Column(String, default="github_actions", nullable=False)
    default_branch = Column(String, default="main", nullable=False)
    detected_ecosystems = Column(Text, default="[]", nullable=False)  # JSON list
    workflow_path = Column(String, default=".github/workflows/ci.yml", nullable=False)
    active_workflow_content = Column(Text, nullable=True)
    proposed_workflow_content = Column(Text, nullable=True)
    proposed_diff = Column(Text, nullable=True)
    setup_status = Column(
        String,
        default="not_configured",
        nullable=False,
    )  # not_configured | proposed | awaiting_installation | installed
    pr_number = Column(Integer, nullable=True)
    pr_url = Column(String, nullable=True)
    branch_name = Column(String, nullable=True)
    auto_fix_enabled = Column(Boolean, default=True, nullable=False)
    auto_commit_enabled = Column(Boolean, default=False, nullable=False)
    max_retry_budget = Column(Integer, default=3, nullable=False)
    current_retry_count = Column(Integer, default=0, nullable=False)
    last_failure_fingerprint = Column(String, nullable=True)
    deployment_provider = Column(String, nullable=True)  # vercel | render | docker | github_pages | none
    deployment_status = Column(String, default="not_configured", nullable=False)
    deployment_url = Column(String, nullable=True)
    last_run_id = Column(String, nullable=True)
    last_run_status = Column(String, nullable=True)
    last_run_conclusion = Column(String, nullable=True)
    last_run_url = Column(String, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    repo = relationship("Repo", back_populates="ci_config")


class RepoCiRun(Base):
    """
    Historical record of remote GitHub Actions CI/CD runs per repository.
    """
    __tablename__ = "repo_ci_runs"

    id = Column(String, primary_key=True, default=_uuid)
    repo_id = Column(String, ForeignKey("repos.id"), nullable=False, index=True)
    run_id = Column(String, nullable=False, index=True)
    run_number = Column(Integer, nullable=True)
    workflow_name = Column(String, nullable=True)
    workflow_path = Column(String, nullable=True)
    event = Column(String, nullable=True)
    status = Column(String, nullable=False)  # queued, in_progress, completed
    conclusion = Column(String, nullable=True)  # success, failure, cancelled, etc.
    html_url = Column(String, nullable=True)
    head_branch = Column(String, nullable=True)
    head_sha = Column(String, nullable=True)
    commit_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    failed_job_name = Column(String, nullable=True)
    failed_step_name = Column(String, nullable=True)
    failure_category = Column(String, nullable=True)  # test_failure, syntax_error, dependency_error, etc.
    ai_diagnosis = Column(Text, nullable=True)
    fix_status = Column(String, default="none", nullable=True)  # none, diagnosing, fix_proposed, fix_committed, exhausted, blocked
    fix_commit_sha = Column(String, nullable=True)
    fix_pr_url = Column(String, nullable=True)
    logs_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    repo = relationship("Repo", back_populates="ci_runs")


