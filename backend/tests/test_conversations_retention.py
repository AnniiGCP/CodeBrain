import sys
from pathlib import Path
import uuid
from datetime import datetime, timedelta, timezone

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

import pytest
from fastapi.testclient import TestClient

from main import app
from database import SessionLocal
from models import User, Repo, Conversation, ConversationMessage

client = TestClient(app)


def test_conversation_crud_and_seven_day_retention():
    db = SessionLocal()
    # Create test user and repo
    unique = uuid.uuid4().hex[:8]
    user = User(
        id=f"test-user-{unique}",
        github_id=f"gh-{unique}",
        github_username=f"user_{unique}",
    )
    repo = Repo(
        id=f"test-repo-{unique}",
        user_id=user.id,
        name=f"Repo_{unique}",
        source_type="upload",
    )
    db.add(user)
    db.add(repo)
    db.commit()

    # Headers for auth mock or user injection
    from auth import create_session_token
    token = create_session_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create a conversation
    resp = client.post(
        f"/repos/{repo.id}/conversations",
        json={"title": "Test Chat", "model_provider": "nvidia", "model_name": "glm-5-3-flash"},
        headers=headers,
    )
    assert resp.status_code == 201
    conv_data = resp.json()
    conv_id = conv_data["id"]
    assert conv_data["title"] == "Test Chat"

    # 2. Add messages
    msg_resp = client.post(
        f"/repos/{repo.id}/conversations/{conv_id}/messages",
        json={"role": "user", "content": "How does auth work?"},
        headers=headers,
    )
    assert msg_resp.status_code == 201

    asst_resp = client.post(
        f"/repos/{repo.id}/conversations/{conv_id}/messages",
        json={"role": "assistant", "content": "Auth uses JWT and bcrypt."},
        headers=headers,
    )
    assert asst_resp.status_code == 201

    # 3. Retrieve conversation
    get_resp = client.get(f"/repos/{repo.id}/conversations/{conv_id}", headers=headers)
    assert get_resp.status_code == 200
    conv_detail = get_resp.json()
    assert len(conv_detail["messages"]) == 2

    # 4. Create an expired conversation (> 7 days old)
    old_conv = Conversation(
        id=f"old-conv-{unique}",
        user_id=user.id,
        repo_id=repo.id,
        title="Old Chat",
        created_at=datetime.utcnow() - timedelta(days=10),
        updated_at=datetime.utcnow() - timedelta(days=8),
    )
    old_conv_id = old_conv.id
    db.add(old_conv)
    db.commit()

    # 5. List conversations -> must purge the 8-day-old one and keep the new one
    list_resp = client.get(f"/repos/{repo.id}/conversations", headers=headers)
    assert list_resp.status_code == 200
    conv_list = list_resp.json()["conversations"]
    conv_ids = [c["id"] for c in conv_list]
    assert conv_id in conv_ids
    assert old_conv_id not in conv_ids

    # Cleanup
    db.query(Conversation).filter(Conversation.user_id == user.id).delete()
    db.query(Repo).filter(Repo.user_id == user.id).delete()
    db.query(User).filter(User.id == user.id).delete()
    db.commit()
    db.close()
