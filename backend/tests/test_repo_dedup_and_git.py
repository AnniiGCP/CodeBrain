import sys
from pathlib import Path
import uuid
import tempfile
import subprocess
from datetime import datetime, timezone

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

import pytest
from database import SessionLocal
from models import User, Repo
from routers.repos import list_repos
from gitops.git_ops import create_or_checkout_branch


def test_repo_deduplication_and_git_commit_metadata():
    db = SessionLocal()
    unique = uuid.uuid4().hex[:8]
    user = User(
        id=f"test-user-dedup-{unique}",
        github_id=f"gh-dedup-{unique}",
        github_username=f"user_dedup_{unique}",
    )
    db.add(user)
    db.commit()

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Initialize a real git repo in tmp_dir
        subprocess.run(["git", "init"], cwd=tmp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@codebrain.ai"], cwd=tmp_dir, check=True)
        subprocess.run(["git", "config", "user.name", "CodeBrain Test"], cwd=tmp_dir, check=True)
        
        test_file = Path(tmp_dir) / "app.py"
        test_file.write_text("print('hello world')")
        subprocess.run(["git", "add", "."], cwd=tmp_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit for QuizGenAI"], cwd=tmp_dir, check=True)

        # 1. Simulate duplicate ingestion records for QuizGenAI
        repo_old = Repo(
            id=f"repo-old-{unique}",
            user_id=user.id,
            name="QuizGenAI",
            source_type="github",
            created_at=datetime.fromtimestamp(1000, tz=timezone.utc),
            last_activity_summary="Older ingestion",
        )
        repo_new = Repo(
            id=f"repo-new-{unique}",
            user_id=user.id,
            name="QuizGenAI",
            source_type="github",
            created_at=datetime.fromtimestamp(2000, tz=timezone.utc),
            last_commit_sha="e269f36",
            last_commit_message="Initial commit for QuizGenAI",
            last_commit_branch="main",
            last_activity_summary="Indexed 118 files and AST symbols",
        )
        repo_other = Repo(
            id=f"repo-other-{unique}",
            user_id=user.id,
            name="AnotherRepo",
            source_type="github",
            created_at=datetime.fromtimestamp(1500, tz=timezone.utc),
            last_activity_summary="Indexed 42 files and AST symbols",
        )
        db.add(repo_old)
        db.add(repo_new)
        db.add(repo_other)
        db.commit()

        # Call list_repos
        repos = list_repos(current_user=user, db=db)

        # QuizGenAI must appear exactly once, keeping repo_new (latest created_at)
        quizgen_items = [r for r in repos if r["name"] == "QuizGenAI"]
        assert len(quizgen_items) == 1, "Duplicate QuizGenAI records must be deduplicated"
        assert quizgen_items[0]["repo_id"] == repo_new.id

        # Factual git metadata should be populated
        assert quizgen_items[0]["last_commit_sha"] == "e269f36"
        assert "Initial commit for QuizGenAI" in quizgen_items[0]["last_commit_message"]
        assert "118 files" in quizgen_items[0]["last_activity_summary"]

        # 2. Test idempotent branch creation for 'codebrain/setup-ci-workflow'
        # Calling create_or_checkout_branch twice must succeed without throwing collision error
        res1 = create_or_checkout_branch(tmp_dir, "codebrain/setup-ci-workflow")
        assert res1["success"] is True

        res2 = create_or_checkout_branch(tmp_dir, "codebrain/setup-ci-workflow")
        assert res2["success"] is True

    # Cleanup
    db.query(Repo).filter(Repo.user_id == user.id).delete()
    db.query(User).filter(User.id == user.id).delete()
    db.commit()
    db.close()
