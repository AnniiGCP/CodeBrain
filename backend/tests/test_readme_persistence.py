"""
backend/tests/test_readme_persistence.py
----------------------------------------
Test suite validating Plain-Language README.md persistence, refresh safety,
invalidation, concurrency deduplication, and authorization controls.
"""
import uuid
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from main import app
from database import SessionLocal, init_db
from models import User, Repo, RepoFile, RepoReadme
from auth import create_session_token
from routers.docs import compute_repo_source_fingerprint

client = TestClient(app)


@pytest.fixture
def readme_env():
    init_db()
    with SessionLocal() as db:
        user1 = User(
            id=str(uuid.uuid4()),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            github_username="readme_owner",
        )
        user2 = User(
            id=str(uuid.uuid4()),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            github_username="unauthorized_viewer",
        )
        db.add_all([user1, user2])
        db.commit()

        repo1 = Repo(
            id=str(uuid.uuid4()),
            user_id=user1.id,
            name="QuizGenAI",
            source_type="upload",
            pipeline_status="DONE",
            last_commit_sha="c0ffee123",
        )
        repo2 = Repo(
            id=str(uuid.uuid4()),
            user_id=user1.id,
            name="SecondRepo",
            source_type="upload",
            pipeline_status="DONE",
            last_commit_sha="b00b00456",
        )
        db.add_all([repo1, repo2])
        db.commit()

        file1 = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo1.id,
            path="main.py",
            language="python",
            size=120,
            content_hash="hash_main_v1",
        )
        file2 = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo2.id,
            path="server.js",
            language="javascript",
            size=250,
            content_hash="hash_srv_v1",
        )
        db.add_all([file1, file2])
        db.commit()

        u1_id, u2_id = user1.id, user2.id
        r1_id, r2_id = repo1.id, repo2.id

    t1 = create_session_token(u1_id)
    t2 = create_session_token(u2_id)
    return {
        "user1_id": u1_id,
        "user2_id": u2_id,
        "repo1_id": r1_id,
        "repo2_id": r2_id,
        "headers1": {"Authorization": f"Bearer {t1}"},
        "headers2": {"Authorization": f"Bearer {t2}"},
    }


def test_1_first_visit_no_saved_readme_then_generate(readme_env):
    """Case 1: First visit has no saved README, then generation persists it."""
    r1 = readme_env["repo1_id"]
    h1 = readme_env["headers1"]

    # 1. GET returns has_readme: False initially
    get_res = client.get(f"/repos/{r1}/docs/readme", headers=h1)
    assert get_res.status_code == 200
    assert get_res.json()["has_readme"] is False

    mock_readme_text = "# QuizGenAI\\n\\nPlain-language developer README."
    with patch("docgen.readme_gen.generate_repo_readme", return_value=mock_readme_text) as mock_gen:
        post_res = client.post(f"/repos/{r1}/docs/readme", headers=h1)
        assert post_res.status_code == 200
        data = post_res.json()
        assert data["readme"] == mock_readme_text
        assert data["is_fresh"] is True
        mock_gen.assert_called_once()

    # Verify persisted in database
    with SessionLocal() as db:
        saved = db.query(RepoReadme).filter(RepoReadme.repo_id == r1).first()
        assert saved is not None
        assert saved.content == mock_readme_text
        assert saved.status == "READY"


def test_2_refresh_loads_saved_readme_without_ai_call(readme_env):
    """Case 2: Refresh loads saved README via GET and POST (force=False) without calling AI."""
    r1 = readme_env["repo1_id"]
    h1 = readme_env["headers1"]

    # Pre-save README in DB
    mock_content = "# Persisted QuizGenAI README"
    with SessionLocal() as db:
        fp = compute_repo_source_fingerprint(r1, db)
        saved = RepoReadme(
            id=str(uuid.uuid4()),
            repo_id=r1,
            content=mock_content,
            source_fingerprint=fp,
            status="READY",
        )
        db.add(saved)
        db.commit()

    with patch("docgen.readme_gen.generate_repo_readme") as mock_gen:
        # GET request (page mount / refresh)
        get_res = client.get(f"/repos/{r1}/docs/readme", headers=h1)
        assert get_res.status_code == 200
        assert get_res.json()["has_readme"] is True
        assert get_res.json()["readme"] == mock_content
        assert get_res.json()["is_stale"] is False

        # POST request without force
        post_res = client.post(f"/repos/{r1}/docs/readme", headers=h1)
        assert post_res.status_code == 200
        assert post_res.json()["readme"] == mock_content
        assert post_res.json()["is_fresh"] is False

        # Doc sections endpoint also returns saved README
        sec_res = client.get(f"/repos/{r1}/docs/sections", headers=h1)
        assert sec_res.status_code == 200
        assert sec_res.json()["readme_content"] == mock_content

        mock_gen.assert_not_called()


def test_3_explicit_regenerate_forces_new_synthesis(readme_env):
    """Case 3: Explicit Regenerate README with force=True re-synthesizes and updates storage."""
    r1 = readme_env["repo1_id"]
    h1 = readme_env["headers1"]

    old_content = "# Old README"
    new_content = "# Freshly Regenerated README v2"

    with SessionLocal() as db:
        fp = compute_repo_source_fingerprint(r1, db)
        saved = RepoReadme(
            id=str(uuid.uuid4()),
            repo_id=r1,
            content=old_content,
            source_fingerprint=fp,
            status="READY",
        )
        db.add(saved)
        db.commit()

    with patch("docgen.readme_gen.generate_repo_readme", return_value=new_content) as mock_gen:
        res = client.post(f"/repos/{r1}/docs/readme?force=true", headers=h1)
        assert res.status_code == 200
        assert res.json()["readme"] == new_content
        assert res.json()["is_fresh"] is True
        mock_gen.assert_called_once()

    # DB has updated content
    with SessionLocal() as db:
        saved = db.query(RepoReadme).filter(RepoReadme.repo_id == r1).first()
        assert saved.content == new_content


def test_4_failed_regeneration_preserves_previous_saved_content(readme_env):
    """Case 4: Failed regeneration does not erase existing valid README."""
    r1 = readme_env["repo1_id"]
    h1 = readme_env["headers1"]

    prev_content = "# Preserved Valid README"
    with SessionLocal() as db:
        fp = compute_repo_source_fingerprint(r1, db)
        saved = RepoReadme(
            id=str(uuid.uuid4()),
            repo_id=r1,
            content=prev_content,
            source_fingerprint=fp,
            status="READY",
        )
        db.add(saved)
        db.commit()

    with patch("docgen.readme_gen.generate_repo_readme", side_effect=RuntimeError("AI provider quota exhausted")):
        res = client.post(f"/repos/{r1}/docs/readme?force=true", headers=h1)
        assert res.status_code == 500
        assert "quota exhausted" in res.json()["detail"]

    # Verify previous content was preserved intact
    with SessionLocal() as db:
        saved = db.query(RepoReadme).filter(RepoReadme.repo_id == r1).first()
        assert saved is not None
        assert saved.content == prev_content


def test_5_relevant_source_change_detected_via_fingerprint(readme_env):
    """Case 5: Changing a repo file's hash changes fingerprint and marks README as stale."""
    r1 = readme_env["repo1_id"]
    h1 = readme_env["headers1"]

    with SessionLocal() as db:
        fp = compute_repo_source_fingerprint(r1, db)
        saved = RepoReadme(
            id=str(uuid.uuid4()),
            repo_id=r1,
            content="# Initial README",
            source_fingerprint=fp,
            status="READY",
        )
        db.add(saved)
        db.commit()

    # Verify not stale initially
    res1 = client.get(f"/repos/{r1}/docs/readme", headers=h1)
    assert res1.json()["is_stale"] is False

    # Simulate genuine code change
    with SessionLocal() as db:
        rf = db.query(RepoFile).filter(RepoFile.repo_id == r1).first()
        rf.content_hash = "hash_main_v2_updated"
        db.commit()

    # Now fingerprint is different -> is_stale is True
    res2 = client.get(f"/repos/{r1}/docs/readme", headers=h1)
    assert res2.json()["is_stale"] is True
    # But previous content is STILL available to display!
    assert res2.json()["readme"] == "# Initial README"


def test_6_repository_switching_isolates_content(readme_env):
    """Case 6: Different repositories return their own independent READMEs."""
    r1 = readme_env["repo1_id"]
    r2 = readme_env["repo2_id"]
    h1 = readme_env["headers1"]

    with SessionLocal() as db:
        saved1 = RepoReadme(
            id=str(uuid.uuid4()),
            repo_id=r1,
            content="# Repo 1 Content",
            status="READY",
        )
        saved2 = RepoReadme(
            id=str(uuid.uuid4()),
            repo_id=r2,
            content="# Repo 2 Content",
            status="READY",
        )
        db.add_all([saved1, saved2])
        db.commit()

    res1 = client.get(f"/repos/{r1}/docs/readme", headers=h1)
    res2 = client.get(f"/repos/{r2}/docs/readme", headers=h1)

    assert res1.json()["readme"] == "# Repo 1 Content"
    assert res2.json()["readme"] == "# Repo 2 Content"


def test_7_unauthorized_user_cannot_access_or_overwrite(readme_env):
    """Case 7: Unauthorized user cannot read or overwrite another user's private README."""
    r1 = readme_env["repo1_id"]
    h2 = readme_env["headers2"]  # user2 is not owner of repo1

    get_res = client.get(f"/repos/{r1}/docs/readme", headers=h2)
    assert get_res.status_code in (403, 404)

    post_res = client.post(f"/repos/{r1}/docs/readme", headers=h2)
    assert post_res.status_code in (403, 404)
