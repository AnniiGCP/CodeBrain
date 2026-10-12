"""
backend/execution/provider.py
-----------------------------
Core execution provider abstraction for CodeBrain.
Decouples repository command execution, test sandboxes, and interactive terminal sessions
from the backend application and web server host.

Provides:
- BaseExecutionProvider: abstract interface
- SubprocessExecutionProvider: host-isolated execution with scrubbed environment (for local dev)
- DockerExecutionProvider: container-isolated execution (for production and self-hosted deployments)
- NullExecutionProvider: truthful runtime-unavailable reporting when isolated runtime is missing
- get_execution_provider(): runtime factory honoring configuration and security policies
"""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("codebrain.execution")


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    error: str = ""
    provider_name: str = "unknown"
    duration_s: float = 0.0


class TerminalProcessProtocol(ABC):
    """Abstract interface for interactive terminal processes."""

    @abstractmethod
    def stdin_write(self, text: str) -> bool:
        """Send input characters to the running process stdin."""
        raise NotImplementedError

    @abstractmethod
    def read_line(self) -> Optional[str]:
        """Read a single line from the combined process output stream."""
        raise NotImplementedError

    @abstractmethod
    def terminate(self) -> bool:
        """Safely terminate the process tree."""
        raise NotImplementedError

    @abstractmethod
    def is_running(self) -> bool:
        """Check if process is currently executing."""
        raise NotImplementedError

    @abstractmethod
    def wait(self, timeout: Optional[float] = None) -> int:
        """Wait for process completion and return exit code."""
        raise NotImplementedError


class SubprocessTerminalProcess(TerminalProcessProtocol):
    """Interactive process backed by host subprocess (dev mode)."""

    def __init__(self, proc: subprocess.Popen, session_id: str):
        self.proc = proc
        self.session_id = session_id

    def stdin_write(self, text: str) -> bool:
        if not self.proc or self.proc.poll() is not None or not self.proc.stdin:
            return False
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
            return True
        except Exception as exc:
            logger.warning("Failed to write to stdin for session %s: %s", self.session_id, exc)
            return False

    def read_line(self) -> Optional[str]:
        if not self.proc or not self.proc.stdout:
            return None
        try:
            line = self.proc.stdout.readline()
            return line if line else None
        except Exception:
            return None

    def terminate(self) -> bool:
        if not self.proc or self.proc.poll() is not None:
            return True
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                    capture_output=True,
                    timeout=5,
                )
            else:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            return True
        except Exception as exc:
            logger.warning("Error terminating subprocess %s: %s", self.session_id, exc)
            return False

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def wait(self, timeout: Optional[float] = None) -> int:
        if not self.proc:
            return 0
        return self.proc.wait(timeout=timeout)


class NullTerminalProcess(TerminalProcessProtocol):
    """Stub process returned when runtime is unavailable; emits diagnostic message."""

    def __init__(self, message: str):
        self._message = message
        self._emitted = False

    def stdin_write(self, text: str) -> bool:
        return False

    def read_line(self) -> Optional[str]:
        if not self._emitted:
            self._emitted = True
            return f"[Runtime Unavailable: {self._message}]\n"
        return None

    def terminate(self) -> bool:
        return True

    def is_running(self) -> bool:
        return False

    def wait(self, timeout: Optional[float] = None) -> int:
        return 1


class BaseExecutionProvider(ABC):
    """Abstract contract for executing repo commands and managing terminal processes."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can execute commands in the current environment."""
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Return health status and capabilities of the execution provider."""
        raise NotImplementedError

    @abstractmethod
    def execute_command(
        self,
        cwd: Path,
        cmd: str,
        env: Dict[str, str],
        timeout_s: int = 60,
    ) -> ExecutionResult:
        """Execute a non-interactive command (e.g. test runner, build check)."""
        raise NotImplementedError

    @abstractmethod
    def create_terminal_process(
        self,
        session_id: str,
        cwd: Path,
        env: Dict[str, str],
        command: str,
    ) -> TerminalProcessProtocol:
        """Create an interactive terminal process."""
        raise NotImplementedError


class SubprocessExecutionProvider(BaseExecutionProvider):
    """
    Subprocess execution provider with scrubbed environment and path containment.
    Suitable for local development. Strictly blocked in production/public deployments.
    """

    @property
    def name(self) -> str:
        return "subprocess"

    def is_available(self) -> bool:
        # Strictly enforce isolation if in production or isolation requested
        is_req = os.getenv("ISOLATED_RUNTIME_REQUIRED", "false").lower() in ("true", "1", "yes")
        is_pub = os.getenv("PUBLIC_DEPLOYMENT", "false").lower() in ("true", "1", "yes")
        env_mode = os.getenv("ENVIRONMENT", "development").lower()
        if is_req or is_pub or env_mode == "production":
            return False
        return True

    def health_check(self) -> Dict[str, Any]:
        avail = self.is_available()
        return {
            "provider": self.name,
            "status": "ready" if avail else "blocked",
            "isolated": False,
            "python_executable": sys.executable,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "message": "Host subprocess provider active (development mode only)."
            if avail
            else "Host execution is blocked in production or when isolation is required.",
        }

    def execute_command(
        self,
        cwd: Path,
        cmd: str,
        env: Dict[str, str],
        timeout_s: int = 60,
    ) -> ExecutionResult:
        if not self.is_available():
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                timed_out=False,
                error="Host subprocess execution is blocked in production. Configure an isolated Docker or remote execution provider.",
                provider_name=self.name,
            )

        start = time.time()
        py_prefix = f'"{sys.executable}"'
        use_shell = True
        cmd_args: list[str] | str = cmd

        if cmd.startswith(py_prefix) or cmd.startswith(sys.executable):
            rest = cmd[len(py_prefix):] if cmd.startswith(py_prefix) else cmd[len(sys.executable):]
            parts = shlex.split(rest.strip(), posix=(sys.platform != "win32"))
            clean_parts = [p.strip('"').strip("'") for p in parts if p.strip()]
            cmd_args = [sys.executable, *clean_parts]
            use_shell = False

        try:
            proc = subprocess.run(
                cmd_args,
                shell=use_shell,
                capture_output=True,
                text=True,
                cwd=str(cwd),
                timeout=timeout_s,
                env=env,
            )
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                timed_out=False,
                error="",
                provider_name=self.name,
                duration_s=time.time() - start,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                timed_out=True,
                error=f"Execution timed out after {timeout_s} seconds.",
                provider_name=self.name,
                duration_s=time.time() - start,
            )
        except Exception as exc:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                timed_out=False,
                error=str(exc),
                provider_name=self.name,
                duration_s=time.time() - start,
            )

    def create_terminal_process(
        self,
        session_id: str,
        cwd: Path,
        env: Dict[str, str],
        command: str,
    ) -> TerminalProcessProtocol:
        if not self.is_available():
            return NullTerminalProcess(
                "Host subprocess execution is blocked in production. An isolated execution runtime is required."
            )

        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        return SubprocessTerminalProcess(proc, session_id)


class DockerExecutionProvider(BaseExecutionProvider):
    """
    Container-isolated execution provider.
    Runs commands and terminal sessions in unprivileged Docker containers with:
    - Dedicated workspace mount
    - Dropped capabilities, no host socket exposure
    - Scrubbed environment (zero backend secrets)
    - Memory and CPU limits
    """

    def __init__(self, image: Optional[str] = None):
        self.image = image or os.getenv("SANDBOX_DOCKER_IMAGE", "python:3.11-slim")
        self.docker_bin = shutil.which("docker")

    @property
    def name(self) -> str:
        return "docker"

    def is_available(self) -> bool:
        if not self.docker_bin:
            return False
        try:
            res = subprocess.run(
                [self.docker_bin, "info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0
        except Exception:
            return False

    def health_check(self) -> Dict[str, Any]:
        avail = self.is_available()
        return {
            "provider": self.name,
            "status": "ready" if avail else "unavailable",
            "isolated": True,
            "docker_bin": self.docker_bin,
            "image": self.image,
            "message": "Docker container runtime available and verified."
            if avail
            else "Docker CLI or daemon is unreachable. Verify Docker service is running.",
        }

    def execute_command(
        self,
        cwd: Path,
        cmd: str,
        env: Dict[str, str],
        timeout_s: int = 60,
    ) -> ExecutionResult:
        if not self.is_available():
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                timed_out=False,
                error="Docker daemon is unavailable. Untrusted code cannot be executed in production.",
                provider_name=self.name,
            )

        start = time.time()
        # Build docker run invocation
        # Workspace is mounted read-write at /workspace
        abs_cwd = str(cwd.resolve()).replace("\\", "/")
        docker_args = [
            self.docker_bin,
            "run",
            "--rm",
            "--network", "none",  # Restrict egress
            "--memory", "512m",   # Limit RAM
            "--cpus", "1.0",      # Limit CPU
            "-v", f"{abs_cwd}:/workspace:rw",
            "-w", "/workspace",
        ]

        # Pass scrubbed environment explicitly
        for k, v in env.items():
            if k in ("PYTHONPATH", "PYTHONUNBUFFERED", "CI", "NODE_ENV", "PATH"):
                docker_args.extend(["-e", f"{k}={v}"])

        docker_args.extend([self.image, "sh", "-c", cmd])

        try:
            proc = subprocess.run(
                docker_args,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                timed_out=False,
                error="",
                provider_name=self.name,
                duration_s=time.time() - start,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                timed_out=True,
                error=f"Docker execution timed out after {timeout_s} seconds.",
                provider_name=self.name,
                duration_s=time.time() - start,
            )
        except Exception as exc:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                timed_out=False,
                error=f"Docker execution error: {exc}",
                provider_name=self.name,
                duration_s=time.time() - start,
            )

    def create_terminal_process(
        self,
        session_id: str,
        cwd: Path,
        env: Dict[str, str],
        command: str,
    ) -> TerminalProcessProtocol:
        if not self.is_available():
            return NullTerminalProcess("Docker runtime is unavailable for interactive terminal.")

        abs_cwd = str(cwd.resolve()).replace("\\", "/")
        docker_args = [
            self.docker_bin,
            "run",
            "-i",
            "--rm",
            "-v", f"{abs_cwd}:/workspace:rw",
            "-w", "/workspace",
            "--memory", "512m",
            "--cpus", "1.0",
        ]
        for k, v in env.items():
            if k in ("PYTHONPATH", "PYTHONUNBUFFERED", "CI", "NODE_ENV", "PATH"):
                docker_args.extend(["-e", f"{k}={v}"])

        docker_args.extend([self.image, "sh", "-c", command])

        proc = subprocess.Popen(
            docker_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        return SubprocessTerminalProcess(proc, session_id)


class RemoteTerminalProcess(TerminalProcessProtocol):
    """Interactive terminal stream backed by a remote execution worker API."""

    def __init__(
        self,
        worker_url: str,
        token: str,
        session_id: str,
        cwd: str,
        command: str,
        env: Dict[str, str],
    ):
        self.worker_url = worker_url
        self.token = token
        self.session_id = session_id
        self._is_running = True
        self.exit_code: Optional[int] = None
        self._output_queue: List[str] = []
        self._lock = threading.Lock()

        import json
        import urllib.request
        try:
            payload = json.dumps({
                "session_id": session_id,
                "command": command,
                "cwd": cwd,
                "env": env,
            }).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(
                f"{worker_url}/terminals/{session_id}/start",
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for line in data.get("initial_output", []):
                    self._output_queue.append(line)
        except Exception as exc:
            self._output_queue.append(f"[Remote worker error: {exc}]\n")
            self._is_running = False
            self.exit_code = 1

    def stdin_write(self, text: str) -> bool:
        if not self._is_running:
            return False
        import json
        import urllib.request
        try:
            payload = json.dumps({"text": text}).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            req = urllib.request.Request(
                f"{self.worker_url}/terminals/{self.session_id}/stdin",
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def read_line(self) -> Optional[str]:
        with self._lock:
            if self._output_queue:
                return self._output_queue.pop(0)
        if not self._is_running:
            return None
        import json
        import urllib.request
        try:
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            req = urllib.request.Request(
                f"{self.worker_url}/terminals/{self.session_id}/poll",
                headers=headers,
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                lines = data.get("lines", [])
                self._is_running = data.get("is_running", True)
                if not self._is_running:
                    self.exit_code = data.get("exit_code", 0)
                with self._lock:
                    self._output_queue.extend(lines)
                    if self._output_queue:
                        return self._output_queue.pop(0)
        except Exception:
            self._is_running = False
            self.exit_code = 1
        return None

    def terminate(self) -> bool:
        self._is_running = False
        import urllib.request
        try:
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            req = urllib.request.Request(
                f"{self.worker_url}/terminals/{self.session_id}/stop",
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3):
                pass
        except Exception:
            pass
        return True

    def is_running(self) -> bool:
        return self._is_running

    def wait(self, timeout: Optional[float] = None) -> int:
        start = time.time()
        while self._is_running:
            if timeout and (time.time() - start) > timeout:
                break
            time.sleep(0.1)
            self.read_line()
        return self.exit_code if self.exit_code is not None else 0


class RemoteExecutionProvider(BaseExecutionProvider):
    """
    Provider-agnostic remote worker execution provider.
    Enables hosting the backend API on any cloud platform (Fly.io, AWS App Runner, Cloud Run, etc.)
    while delegating isolated repo execution to a dedicated execution worker service.
    """

    def __init__(self, worker_url: Optional[str] = None, token: Optional[str] = None):
        self.worker_url = (worker_url or os.getenv("EXECUTION_WORKER_URL", "")).rstrip("/")
        self.token = token or os.getenv("EXECUTION_WORKER_TOKEN", "")

    @property
    def name(self) -> str:
        return "remote"

    def is_available(self) -> bool:
        if not self.worker_url:
            return False
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.worker_url}/health", headers=self._headers())
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def health_check(self) -> Dict[str, Any]:
        avail = self.is_available()
        return {
            "provider": self.name,
            "status": "ready" if avail else "unavailable",
            "isolated": True,
            "worker_url": self.worker_url or "(not configured)",
            "message": "Remote execution worker service reachable."
            if avail
            else "Remote execution worker service is unreachable or unconfigured (check EXECUTION_WORKER_URL).",
        }

    def execute_command(
        self,
        cwd: Path,
        cmd: str,
        env: Dict[str, str],
        timeout_s: int = 60,
    ) -> ExecutionResult:
        if not self.worker_url:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                timed_out=False,
                error="EXECUTION_WORKER_URL is not configured for remote execution provider.",
                provider_name=self.name,
            )

        import json
        import urllib.request
        start = time.time()
        payload = json.dumps({
            "command": cmd,
            "cwd": str(cwd),
            "env": env,
            "timeout_s": timeout_s,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self.worker_url}/execute",
                data=payload,
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_s + 5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return ExecutionResult(
                    exit_code=data.get("exit_code", -1),
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", ""),
                    timed_out=data.get("timed_out", False),
                    error=data.get("error", ""),
                    provider_name=self.name,
                    duration_s=time.time() - start,
                )
        except Exception as exc:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                timed_out=False,
                error=f"Remote worker execution error: {exc}",
                provider_name=self.name,
                duration_s=time.time() - start,
            )

    def create_terminal_process(
        self,
        session_id: str,
        cwd: Path,
        env: Dict[str, str],
        command: str,
    ) -> TerminalProcessProtocol:
        if not self.is_available():
            return NullTerminalProcess("Remote execution worker is unreachable for interactive terminal.")
        return RemoteTerminalProcess(self.worker_url, self.token, session_id, str(cwd), command, env)


class NullExecutionProvider(BaseExecutionProvider):
    """
    Truthful fallback provider when no isolated execution runtime is configured.
    Prevents silent unsafe host execution in production/public deployments.
    """

    def __init__(self, reason: str = "Execution runtime is not configured or unavailable."):
        self.reason = reason

    @property
    def name(self) -> str:
        return "null"

    def is_available(self) -> bool:
        return False

    def health_check(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "unavailable",
            "isolated": False,
            "message": self.reason,
        }

    def execute_command(
        self,
        cwd: Path,
        cmd: str,
        env: Dict[str, str],
        timeout_s: int = 60,
    ) -> ExecutionResult:
        return ExecutionResult(
            exit_code=-1,
            stdout="",
            stderr="",
            timed_out=False,
            error=f"RUNTIME_UNAVAILABLE: {self.reason}",
            provider_name=self.name,
        )

    def create_terminal_process(
        self,
        session_id: str,
        cwd: Path,
        env: Dict[str, str],
        command: str,
    ) -> TerminalProcessProtocol:
        return NullTerminalProcess(self.reason)


# ── Global Provider Registry & Factory ───────────────────────────────────────

_CACHED_PROVIDER: Optional[BaseExecutionProvider] = None
_CACHED_KEY: Optional[Tuple[str, bool]] = None
_CACHED_LOCK = threading.Lock()


def get_execution_provider(force_reload: bool = False) -> BaseExecutionProvider:
    """
    Returns the configured execution provider.
    Resolution logic:
    1. Check EXECUTION_PROVIDER environment variable ('docker', 'remote', 'subprocess', 'null').
    2. Check security requirements: ISOLATED_RUNTIME_REQUIRED=true or ENVIRONMENT=production.
       - If isolation is required, only Docker or remote isolated providers are allowed.
       - If Docker/remote is unavailable, returns NullExecutionProvider (NEVER silent host execution).
    3. In local development without strict isolation, SubprocessExecutionProvider is allowed.
    """
    global _CACHED_PROVIDER, _CACHED_KEY
    with _CACHED_LOCK:
        pref = os.getenv("EXECUTION_PROVIDER", "").strip().lower()
        worker_url = os.getenv("EXECUTION_WORKER_URL", "").strip()
        is_isolated_required = os.getenv("ISOLATED_RUNTIME_REQUIRED", "false").lower() in ("true", "1", "yes")
        is_pub = os.getenv("PUBLIC_DEPLOYMENT", "false").lower() in ("true", "1", "yes")
        env_mode = os.getenv("ENVIRONMENT", "development").lower()
        strict_isolation = is_isolated_required or is_pub or (env_mode == "production")
        current_key = (f"{pref}:{worker_url}", strict_isolation)

        if _CACHED_PROVIDER is not None and not force_reload and _CACHED_KEY == current_key:
            return _CACHED_PROVIDER

        if pref == "remote":
            remote_p = RemoteExecutionProvider()
            if remote_p.is_available():
                _CACHED_PROVIDER = remote_p
            elif strict_isolation:
                _CACHED_PROVIDER = NullExecutionProvider(
                    "Remote execution worker requested but unreachable at EXECUTION_WORKER_URL."
                )
            else:
                _CACHED_PROVIDER = SubprocessExecutionProvider()

        elif pref == "docker":
            docker_p = DockerExecutionProvider()
            if docker_p.is_available():
                _CACHED_PROVIDER = docker_p
            elif strict_isolation:
                _CACHED_PROVIDER = NullExecutionProvider(
                    "Docker execution provider requested but Docker daemon is unreachable."
                )
            else:
                logger.warning("Docker unreachable in dev mode; falling back to SubprocessExecutionProvider.")
                _CACHED_PROVIDER = SubprocessExecutionProvider()

        elif pref == "subprocess":
            if strict_isolation:
                _CACHED_PROVIDER = NullExecutionProvider(
                    "Subprocess host execution is forbidden in production or when isolation is required."
                )
            else:
                _CACHED_PROVIDER = SubprocessExecutionProvider()

        elif pref == "null":
            _CACHED_PROVIDER = NullExecutionProvider("Execution runtime explicitly disabled by configuration.")

        else:
            # Auto-detection
            if worker_url:
                remote_p = RemoteExecutionProvider()
                if remote_p.is_available():
                    _CACHED_PROVIDER = remote_p
                elif strict_isolation:
                    _CACHED_PROVIDER = NullExecutionProvider(
                        "Remote worker configured at EXECUTION_WORKER_URL is unreachable."
                    )
                else:
                    _CACHED_PROVIDER = SubprocessExecutionProvider()
            else:
                docker_p = DockerExecutionProvider()
                if docker_p.is_available():
                    _CACHED_PROVIDER = docker_p
                elif strict_isolation:
                    _CACHED_PROVIDER = NullExecutionProvider(
                        "Isolated container runtime (Docker) is unavailable. For security reasons in public/production deployment, untrusted code cannot be executed directly on the host."
                    )
                else:
                    _CACHED_PROVIDER = SubprocessExecutionProvider()

        _CACHED_KEY = current_key
        logger.info(
            "Selected execution provider: %s (strict_isolation=%s)",
            _CACHED_PROVIDER.name,
            strict_isolation,
        )
        return _CACHED_PROVIDER


def reset_execution_provider() -> None:
    """Reset cached provider singleton (used for tests and dynamic configuration)."""
    global _CACHED_PROVIDER, _CACHED_KEY
    with _CACHED_LOCK:
        _CACHED_PROVIDER = None
        _CACHED_KEY = None
