import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from main import app
from database import SessionLocal, init_db
from models import User, Repo, RepoFile
from auth import create_session_token

client = TestClient(app)


@pytest.fixture
def test_user():
    init_db()
    with SessionLocal() as db:
        user = db.query(User).filter(User.github_id == "test_phase2_user").first()
        if not user:
            user = User(
                github_id="test_phase2_user",
                github_username="test_phase2_user",
                github_avatar_url="https://github.com/test.png",
            )
            db.add(user)
            db.commit()
        # Clear existing repos for clean test run
        db.query(Repo).filter(Repo.user_id == user.id).delete()
        db.commit()
        user_id = user.id
    return user_id


def _create_sample_zip(files: dict[str, str]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf


def test_zip_upload_valid_repo(test_user):
    """Verify clean ZIP upload extracts, ingests files, and returns 201."""
    token = create_session_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}

    sample_files = {
        "main.py": "def add(a, b):\n    return a + b\n",
        "utils.py": "def helper():\n    return True\n",
        "README.md": "# Sample Project\nDocumentation here.\n",
        "node_modules/ignored.js": "console.log('should be ignored');",
        ".git/config": "[core]\nrepositoryformatversion = 0\n",
    }
    zip_buf = _create_sample_zip(sample_files)

    response = client.post(
        "/repos/upload",
        files={"file": ("sample_repo.zip", zip_buf, "application/zip")},
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert "repo_id" in data
    assert data["source_type"] == "upload"
    # Should ingest main.py, utils.py, README.md, but skip node_modules and .git
    assert data["file_count"] == 3

    repo_id = data["repo_id"]

    # Verify file tree
    tree_resp = client.get(f"/repos/{repo_id}/files", headers=headers)
    assert tree_resp.status_code == 200
    tree_data = tree_resp.json()
    assert tree_data["total_files"] == 3

    # Verify file content
    content_resp = client.get(
        f"/repos/{repo_id}/file-content?path=main.py",
        headers=headers,
    )
    assert content_resp.status_code == 200
    assert "def add(a, b):" in content_resp.json()["content"]
    assert content_resp.json()["language"] == "python"


def test_zip_upload_rejects_path_traversal(test_user):
    """Verify ZIP upload with directory traversal attempts is rejected."""
    token = create_session_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}

    traversal_zip = _create_sample_zip({
        "../../evil.py": "print('exploit')",
    })

    response = client.post(
        "/repos/upload",
        files={"file": ("exploit.zip", traversal_zip, "application/zip")},
        headers=headers,
    )
    assert response.status_code == 400
    assert "Unsafe path" in response.json()["detail"]


def test_zip_upload_rejects_empty_and_corrupt(test_user):
    """Verify empty and non-zip files are rejected with 400."""
    token = create_session_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Non-zip
    resp_text = client.post(
        "/repos/upload",
        files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        headers=headers,
    )
    assert resp_text.status_code == 400

    # Corrupt zip
    resp_corrupt = client.post(
        "/repos/upload",
        files={"file": ("corrupt.zip", io.BytesIO(b"not a real zip bytes"), "application/zip")},
        headers=headers,
    )
    assert resp_corrupt.status_code == 400


def test_file_content_rejects_traversal(test_user):
    """Verify /repos/{repo_id}/file-content prevents path traversal."""
    token = create_session_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}

    sample_zip = _create_sample_zip({"index.js": "const x = 1;"})
    upload_resp = client.post(
        "/repos/upload",
        files={"file": ("project.zip", sample_zip, "application/zip")},
        headers=headers,
    )
    repo_id = upload_resp.json()["repo_id"]

    resp = client.get(
        f"/repos/{repo_id}/file-content?path=../../etc/passwd",
        headers=headers,
    )
    assert resp.status_code == 400
