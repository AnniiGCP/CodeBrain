"""
backend/execution/__init__.py
-----------------------------
CodeBrain Execution Provider System.
Decouples repository command execution, test sandboxes, and interactive terminal sessions
from the web host.
"""
from .provider import (
    BaseExecutionProvider,
    ExecutionResult,
    TerminalProcessProtocol,
    RemoteExecutionProvider,
    get_execution_provider,
)

__all__ = [
    "BaseExecutionProvider",
    "ExecutionResult",
    "TerminalProcessProtocol",
    "RemoteExecutionProvider",
    "get_execution_provider",
]
