"""
backend/terminals/manager.py
----------------------------
Production-grade multi-terminal session manager for CodeBrain workspaces.
Provides independent, isolated, concurrent terminal sessions:
  - Each session has its own process, input/output stream, working directory, and exit state.
  - Strict environment variable whitelisting (prevents leaking backend secrets/API keys).
  - Thread-safe output buffering with circular line bounds.
  - Safe process tree termination and session cleanup.
  - User and repository authorization boundaries.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("terminals.manager")

STORAGE_ROOT = Path(__file__).parent.parent / "storage"
MAX_BUFFER_LINES = 3000
SESSION_IDLE_TIMEOUT_SECONDS = 3600  # 1 hour

SAFE_SYSTEM_ENV_VARS = {
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT",
    "USERPROFILE", "HOME", "LANG", "LC_ALL", "TERM", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS", "SYSTEMDRIVE", "APPDATA", "LOCALAPPDATA",
}


def _build_safe_env(cwd: Path) -> Dict[str, str]:
    """
    Construct a scrubbed environment that preserves necessary system paths
    while completely stripping host backend secrets, provider keys, and tokens.
    """
    clean_env: Dict[str, str] = {}
    for k in SAFE_SYSTEM_ENV_VARS:
        v = os.environ.get(k)
        if v:
            clean_env[k] = v

    # Add workspace-scoped pythonpath dynamically
    paths = [str(cwd)]
    visited = {str(cwd)}
    for sub in ("backend", "backend/app", "src", "app", "server", "services", "chatbot", "llm_service", "db", "lib"):
        p = cwd / sub
        if p.is_dir() and str(p) not in visited:
            visited.add(str(p))
            paths.append(str(p))

    clean_env["PYTHONPATH"] = os.pathsep.join(paths)
    clean_env["PYTHONUNBUFFERED"] = "1"
    clean_env["CI"] = "true"
    clean_env["NODE_ENV"] = "development"
    # Safe test mocks
    clean_env["NVIDIA_API_KEY"] = "mock_test_nvidia_key"
    clean_env["GROQ_API_KEY"] = "mock_test_groq_key"
    clean_env["APINEX_API_KEY"] = "mock_test_apinex_key"

    return clean_env


@dataclass
class TerminalOutputLine:
    index: int
    text: str
    stream: str  # "stdout" | "stderr" | "system"
    timestamp: float


class TerminalSession:
    def __init__(
        self,
        session_id: str,
        user_id: str,
        repo_id: str,
        title: str,
        cwd: Path,
        repo_root: Optional[Path] = None,
    ):
        self.id = session_id
        self.user_id = user_id
        self.repo_id = repo_id
        self.title = title
        self.repo_root = (repo_root or cwd).resolve()
        self.cwd = cwd.resolve()
        self.created_at = datetime.now(timezone.utc)
        self.last_activity = time.time()
        
        self.status: str = "idle"  # "idle" | "running" | "exited" | "closed"
        self.current_command: Optional[str] = None
        self.process: Optional[subprocess.Popen] = None
        self.exit_code: Optional[int] = None
        
        self.lock = threading.Lock()
        self.output_buffer: List[TerminalOutputLine] = []
        self._next_line_index: int = 0
        self._reader_thread: Optional[threading.Thread] = None

    @property
    def prompt(self) -> str:
        """Dynamic shell prompt representing repository root as 'CodeBrain'."""
        is_windows = sys.platform == "win32"
        prefix = "PS " if is_windows else ""
        suffix = ">" if is_windows else "$ "

        try:
            rel = self.cwd.resolve().relative_to(self.repo_root.resolve())
            if str(rel) == ".":
                path_str = "CodeBrain"
            else:
                sep = "\\" if is_windows else "/"
                clean_rel = str(rel).replace("/", sep)
                path_str = f"CodeBrain{sep}{clean_rel}"
        except Exception:
            path_str = "CodeBrain"

        return f"{prefix}{path_str}{suffix}"

    def append_output(self, text: str, stream: str = "stdout") -> None:
        with self.lock:
            self.last_activity = time.time()
            line = TerminalOutputLine(
                index=self._next_line_index,
                text=text,
                stream=stream,
                timestamp=time.time(),
            )
            self._next_line_index += 1
            self.output_buffer.append(line)
            if len(self.output_buffer) > MAX_BUFFER_LINES:
                self.output_buffer.pop(0)

    def get_output(self, since_index: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        with self.lock:
            lines = [
                {"index": l.index, "text": l.text, "stream": l.stream, "timestamp": l.timestamp}
                for l in self.output_buffer
                if l.index >= since_index
            ]
            return lines, self._next_line_index

    def execute_command(self, command: str) -> bool:
        cmd_clean = command.strip()
        if not cmd_clean:
            return True

        with self.lock:
            if self.status == "running":
                logger.warning("Session %s is already running a command", self.id)
                return False

            self.current_command = cmd_clean
            self.last_activity = time.time()

        current_prompt = self.prompt
        # Record user command line with the dynamic prompt
        self.append_output(f"{current_prompt} {cmd_clean}", stream="command")

        # 1. Handle directory change navigation ('cd')
        if (
            cmd_clean == "cd"
            or cmd_clean.startswith("cd ")
            or cmd_clean.startswith("cd\\")
            or cmd_clean.startswith("cd/")
        ):
            target_arg = ""
            if cmd_clean == "cd":
                target_arg = ""
            elif cmd_clean.startswith("cd "):
                target_arg = cmd_clean[3:].strip().strip('"').strip("'")
            elif cmd_clean.startswith("cd\\") or cmd_clean.startswith("cd/"):
                target_arg = cmd_clean[2:].strip().strip('"').strip("'")

            # Return to repo root
            if not target_arg or target_arg == "~":
                self.cwd = self.repo_root
                self.status = "idle"
                self.exit_code = 0
                return True

            # Navigate to parent
            if target_arg == "..":
                parent_dir = self.cwd.parent.resolve()
                repo_root_res = self.repo_root.resolve()
                if parent_dir == repo_root_res or str(parent_dir).startswith(str(repo_root_res) + os.sep):
                    self.cwd = parent_dir
                else:
                    self.cwd = repo_root_res
                self.status = "idle"
                self.exit_code = 0
                return True

            if target_arg == ".":
                self.status = "idle"
                self.exit_code = 0
                return True

            # Resolve relative candidate
            cand = (self.cwd / target_arg).resolve()
            repo_root_res = self.repo_root.resolve()

            # Boundary validation: must stay inside repository root
            if cand != repo_root_res and not str(cand).startswith(str(repo_root_res) + os.sep):
                is_win = sys.platform == "win32"
                err_msg = (
                    "Set-Location : Access denied: cannot navigate outside workspace repository root."
                    if is_win
                    else "cd: Access denied: cannot navigate outside workspace repository root."
                )
                self.append_output(err_msg, stream="stderr")
                self.status = "idle"
                self.exit_code = 1
                return True

            if not cand.exists() or not cand.is_dir():
                is_win = sys.platform == "win32"
                err_msg = (
                    f"Set-Location : Cannot find path '{target_arg}' because it does not exist."
                    if is_win
                    else f"bash: cd: {target_arg}: No such file or directory"
                )
                self.append_output(err_msg, stream="stderr")
                self.status = "idle"
                self.exit_code = 1
                return True

            # Successfully update session working directory
            self.cwd = cand
            self.status = "idle"
            self.exit_code = 0
            return True

        # 2. Handle 'cls' or 'clear' to reset output buffer
        if cmd_clean.lower() in ("cls", "clear"):
            with self.lock:
                self.output_buffer.clear()
                self._next_line_index = 0
                self.status = "idle"
                self.exit_code = 0
            return True

        # 3. Execute external command via the configured execution provider
        from execution.provider import get_execution_provider

        provider = get_execution_provider()
        if not provider.is_available() and provider.name == "null":
            health = provider.health_check()
            err_msg = f"[Runtime Unavailable: {health.get('message', 'Execution provider unavailable.')}]"
            self.append_output(err_msg, stream="stderr")
            with self.lock:
                self.status = "idle"
                self.exit_code = 1
            return False

        with self.lock:
            self.status = "running"
            self.exit_code = None

        env = _build_safe_env(self.cwd)

        try:
            proc_wrapper = provider.create_terminal_process(
                session_id=self.id,
                cwd=self.cwd,
                env=env,
                command=cmd_clean,
            )
            self.terminal_proc = proc_wrapper
            self.process = getattr(proc_wrapper, "proc", None)

            def _reader():
                try:
                    while True:
                        line = proc_wrapper.read_line()
                        if line is None:
                            break
                        self.append_output(line.rstrip("\r\n"), stream="stdout")
                except Exception as exc:
                    self.append_output(f"[Stream read error: {exc}]", stream="stderr")
                finally:
                    code = proc_wrapper.wait()
                    with self.lock:
                        self.exit_code = code
                        self.status = "idle"
                        self.terminal_proc = None
                        self.process = None

            t = threading.Thread(target=_reader, daemon=True, name=f"term-read-{self.id[:6]}")
            self._reader_thread = t
            t.start()
            return True

        except Exception as exc:
            with self.lock:
                self.status = "idle"
                self.terminal_proc = None
                self.process = None
                self.exit_code = -1
            self.append_output(f"[Failed to start command: {exc}]", stream="stderr")
            return False

    def send_input(self, text: str) -> bool:
        with self.lock:
            proc_wrapper = getattr(self, "terminal_proc", None)
            if not proc_wrapper or self.status != "running":
                return False
            try:
                ok = proc_wrapper.stdin_write(text)
                if ok:
                    self.last_activity = time.time()
                return ok
            except Exception as exc:
                logger.warning("Failed to send stdin to session %s: %s", self.id, exc)
                return False

    def stop_process(self) -> bool:
        with self.lock:
            proc_wrapper = getattr(self, "terminal_proc", None)
            if not proc_wrapper or self.status != "running":
                return True

        try:
            proc_wrapper.terminate()
        except Exception as exc:
            logger.warning("Error stopping process for session %s: %s", self.id, exc)

        with self.lock:
            self.status = "idle"
            self.terminal_proc = None
            self.process = None
            self.exit_code = -1
        self.append_output("[Process terminated by user]", stream="system")
        return True

    def close(self) -> None:
        self.stop_process()
        with self.lock:
            self.status = "closed"

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            try:
                rel = str(self.cwd.resolve().relative_to(self.repo_root.resolve()))
                rel_cwd = "" if rel == "." else rel
            except Exception:
                rel_cwd = ""
            from execution.provider import get_execution_provider
            provider = get_execution_provider()
            return {
                "id": self.id,
                "title": self.title,
                "repo_id": self.repo_id,
                "cwd": str(self.cwd),
                "rel_cwd": rel_cwd,
                "prompt": self.prompt,
                "shell": "powershell" if sys.platform == "win32" else "bash",
                "status": self.status,
                "is_running": bool(self.status == "running"),
                "current_command": self.current_command,
                "exit_code": self.exit_code,
                "created_at": self.created_at.isoformat(),
                "line_count": len(self.output_buffer),
                "provider": provider.name,
                "isolated": provider.name == "docker",
            }


class TerminalManager:
    """Thread-safe registry of active multi-terminal sessions."""
    def __init__(self):
        self._sessions: Dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        user_id: str,
        repo_id: str,
        title: Optional[str] = None,
        subpath: Optional[str] = None,
    ) -> TerminalSession:
        storage_dir = STORAGE_ROOT / repo_id
        if not storage_dir.exists():
            storage_dir.mkdir(parents=True, exist_ok=True)

        # Detect actual repo root
        repo_root = storage_dir
        children = [c for c in storage_dir.iterdir() if c.is_dir() and c.name not in ("docs", "faiss.index")]
        if len(children) == 1:
            repo_root = children[0]

        target_cwd = repo_root
        if subpath:
            candidate = (repo_root / subpath).resolve()
            if candidate.is_dir() and str(candidate).startswith(str(repo_root.resolve())):
                target_cwd = candidate

        session_id = str(uuid.uuid4())
        with self._lock:
            # Count existing sessions for default naming
            user_repo_sessions = [
                s for s in self._sessions.values()
                if s.user_id == user_id and s.repo_id == repo_id and s.status != "closed"
            ]
            sess_idx = len(user_repo_sessions) + 1
            default_title = f"{sess_idx}: powershell" if sys.platform == "win32" else f"{sess_idx}: bash"
            session = TerminalSession(
                session_id=session_id,
                user_id=user_id,
                repo_id=repo_id,
                title=title or default_title,
                cwd=target_cwd,
                repo_root=repo_root,
            )
            self._sessions[session_id] = session

        logger.info("Created terminal session %s for user %s, repo %s", session_id, user_id, repo_id)
        return session

    def get_session(self, session_id: str, user_id: str) -> Optional[TerminalSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session and session.user_id == user_id and session.status != "closed":
                return session
        return None

    def list_sessions(self, user_id: str, repo_id: str) -> List[TerminalSession]:
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.user_id == user_id and s.repo_id == repo_id and s.status != "closed"
            ]

    def close_session(self, session_id: str, user_id: str) -> bool:
        session = self.get_session(session_id, user_id)
        if not session:
            return False
        session.close()
        with self._lock:
            self._sessions.pop(session_id, None)
        logger.info("Closed terminal session %s", session_id)
        return True

    def cleanup_stale_sessions(self, max_idle_seconds: float = SESSION_IDLE_TIMEOUT_SECONDS) -> int:
        """Purge sessions that have exceeded idle timeout or have been closed."""
        now = time.time()
        stale_ids = []
        with self._lock:
            for s_id, s in self._sessions.items():
                if (now - s.last_activity > max_idle_seconds) or s.status == "closed":
                    stale_ids.append(s_id)
        cleaned = 0
        for s_id in stale_ids:
            with self._lock:
                session = self._sessions.get(s_id)
            if session:
                session.close()
                with self._lock:
                    self._sessions.pop(s_id, None)
                cleaned += 1
        if cleaned > 0:
            logger.info("Cleaned up %d stale terminal sessions", cleaned)
        return cleaned


# Global manager singleton
terminal_manager = TerminalManager()
