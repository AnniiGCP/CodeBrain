import logging
import os
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("codebrain.api")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import engine, init_db

# Create all tables & run migrations on startup (idempotent)
init_db()
import models  # noqa: F401 — ensure tables are registered
from routers import repos as repos_router
from routers import embeddings as embeddings_router
from routers import ask as ask_router
from routers.docs import repos_router as docs_repos_router
from routers.docs import symbols_router as docs_symbols_router
from routers.codefix import symbols_router as codefix_symbols_router
from routers.codefix import repos_router as codefix_repos_router
from routers.pipeline import router as pipeline_router
from routers.errors import router as errors_router
from voice.router import router as voice_router
from routers.gitops import router as gitops_router
from routers import auth as auth_router
from routers import conversations as conversations_router
from routers import terminals as terminals_router
from routers import cicd as cicd_router

from contextlib import asynccontextmanager

# Create all tables on startup (idempotent)
models.Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from automation.auto_fix_pipeline import start_pr_polling_worker
    start_pr_polling_worker(interval_seconds=30)
    yield


app = FastAPI(
    title="AI-Powered Codebase Understanding & Documentation Assistant API",
    version="0.8.1",
    lifespan=lifespan,
)



# Configure CORS for Vite dev server and production deployments (e.g. Vercel)
cors_origins_env = os.getenv("CORS_ORIGINS", "")
allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()] if cors_origins_env else []
frontend_url = os.getenv("FRONTEND_URL", "").strip()
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)
for default_origin in (
    "https://codebrain-dev.vercel.app",
    "https://codebrain.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
):
    if default_origin not in allowed_origins:
        allowed_origins.append(default_origin)

# Never allow wildcard origin with credentials
clean_origins = [o for o in allowed_origins if o != "*"]
if not clean_origins:
    clean_origins = ["https://codebrain-dev.vercel.app", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=clean_origins,
    allow_origin_regex=r"^https://([a-zA-Z0-9_-]+\.)?vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

from fastapi import Request
from fastapi.responses import JSONResponse
from ai.exceptions import AIProviderError, AllProvidersFailedError
from rate_limiter import enforce_public_rate_limit
from docgen.secret_redactor import redact_secrets, sanitize_host_paths
import uuid


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """
    Attach standard browser defense-in-depth security headers to every response.
    Protects against clickjacking, MIME-sniffing, XSS, and unauthorized embeds.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https: wss: ws:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    is_prod = os.getenv("ENVIRONMENT", "").lower() == "production"
    if is_prod or (hasattr(request, "url") and request.url.scheme == "https"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(AllProvidersFailedError)
async def all_providers_failed_handler(request: Request, exc: AllProvidersFailedError):
    return JSONResponse(
        status_code=503,
        content={"detail": exc.message or "AI generation failed across configured providers."},
    )


@app.exception_handler(AIProviderError)
async def ai_provider_error_handler(request: Request, exc: AIProviderError):
    return JSONResponse(
        status_code=503,
        content={"detail": exc.message or "AI provider error occurred."},
    )


@app.exception_handler(Exception)
async def global_unhandled_exception_handler(request: Request, exc: Exception):
    """Centralized exception handler: prevents leaking stack traces, internal paths, or credentials."""
    # Fast-pass HTTPExceptions so standard FastAPI error codes work
    from fastapi import HTTPException
    if isinstance(exc, HTTPException):
        clean_detail = sanitize_host_paths(redact_secrets(str(exc.detail)))
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": clean_detail},
            headers=exc.headers,
        )

    req_id = str(uuid.uuid4())[:8]
    clean_err = sanitize_host_paths(redact_secrets(str(exc)))
    logger.exception("[%s] Unhandled exception processing %s %s: %s", req_id, request.method, request.url.path, clean_err)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "request_id": req_id,
        },
    )


app.include_router(auth_router.router)
app.include_router(repos_router.router)
app.include_router(embeddings_router.router)
app.include_router(pipeline_router)
app.include_router(errors_router)
app.include_router(ask_router.router)
app.include_router(docs_repos_router)
app.include_router(docs_symbols_router)
app.include_router(codefix_symbols_router)
app.include_router(codefix_repos_router)
app.include_router(voice_router)
# GitOps router: auto-fix, branches, commits, diff, and status
app.include_router(gitops_router)
app.include_router(conversations_router.router)
app.include_router(terminals_router.router)
app.include_router(cicd_router.router)


@app.get("/")
def root(request: Request):
    enforce_public_rate_limit(request)
    return {
        "name": app.title,
        "version": app.version,
        "docs_url": "/docs",
        "health_url": "/health",
        "status": "running"
    }


@app.get("/health")
def health_check(request: Request):
    """
    Production health and readiness probe for Render, uptime monitors, and load balancers.
    Checks application liveness and database readiness safely without exposing credentials or internal paths.
    """
    db_status = "connected"
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as e:
        logger.warning("Database health check probe failed: %s", str(e))
        db_status = "unreachable"

    from execution.provider import get_execution_provider
    provider = get_execution_provider()
    runtime_health = provider.health_check()

    is_healthy = db_status == "connected"
    return {
        "status": "ok" if is_healthy else "degraded",
        "version": app.version,
        "database": db_status,
        "runtime": runtime_health,
        "checks": {
            "liveness": "pass",
            "readiness": "pass" if is_healthy else "warn",
        }
    }

