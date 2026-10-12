"""
Tests for CI GitOps diff applicator and file creation.
Verifies fix for: "Target file not found in working tree: .github/workflows/ci.yml"
"""
import pytest
from pathlib import Path
import shutil
import tempfile

from gitops.git_ops import _apply_diff_python


@pytest.fixture
def temp_repo_dir():
    tmp = Path(tempfile.mkdtemp(prefix="codebrain_test_repo_"))
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_apply_diff_python_creates_new_workflow_file(temp_repo_dir):
    """
    Regression test:
    Applying a diff adding .github/workflows/ci.yml when the directory and file
    do NOT yet exist must succeed and create the file with correct content.
    """
    diff_text = """--- /dev/null
+++ b/.github/workflows/ci.yml
@@ -0,0 +1,15 @@
+name: CodeBrain CI
+
+on:
+  push:
+    branches: [ main ]
+  pull_request:
+    branches: [ main ]
+
+jobs:
+  test:
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@v4
+      - name: Run tests
+        run: pytest
+"""
    # Verify .github does not exist initially
    assert not (temp_repo_dir / ".github").exists()

    # Apply diff
    _apply_diff_python(temp_repo_dir, diff_text)

    # Verify created file
    target_file = temp_repo_dir / ".github" / "workflows" / "ci.yml"
    assert target_file.exists()
    content = target_file.read_text(encoding="utf-8")
    assert "name: CodeBrain CI" in content
    assert "run: pytest" in content


def test_apply_diff_python_modifies_existing_file(temp_repo_dir):
    """Test modifying an existing file via diff."""
    f = temp_repo_dir / "app.py"
    f.write_text("def hello():\n    return 'old'\n", encoding="utf-8")

    diff_text = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'old'
+    return 'new'
"""
    _apply_diff_python(temp_repo_dir, diff_text)

    updated = f.read_text(encoding="utf-8")
    assert "return 'new'" in updated
    assert "return 'old'" not in updated


def test_apply_diff_python_deletes_file(temp_repo_dir):
    """Test deleting a file via +++ /dev/null."""
    f = temp_repo_dir / "obsolete.txt"
    f.write_text("to delete", encoding="utf-8")
    assert f.exists()

    diff_text = """--- a/obsolete.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-to delete
"""
    _apply_diff_python(temp_repo_dir, diff_text)
    assert not f.exists()


def test_apply_diff_python_blocks_path_traversal(temp_repo_dir):
    """Test security: rejects paths attempting to escape repository root."""
    diff_text = """--- /dev/null
+++ b/../../evil.txt
@@ -0,0 +1,1 @@
+evil content
"""
    with pytest.raises(RuntimeError, match="escapes repository root"):
        _apply_diff_python(temp_repo_dir, diff_text)
