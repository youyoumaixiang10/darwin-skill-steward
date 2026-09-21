"""Runtime-specific Darwin adapters."""

from .claude import ClaudeCodeAdapter, ClaudeCoworkAdapter
from .codex import CodexAdapter
from .doubao import DoubaoAdapter
from .workbuddy import WorkBuddyAdapter

__all__ = ["ClaudeCodeAdapter", "ClaudeCoworkAdapter", "CodexAdapter", "DoubaoAdapter", "WorkBuddyAdapter"]
