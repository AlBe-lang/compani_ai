"""Domain data contracts shared by all agents."""

from .agent_dna import AgentDNA
from .message import Message, MessageStatus, MessageType
from .strategy import Strategy, Task
from .task_result import FileInfo, TaskResult
from .work_item import WorkItem, WorkStatus

__all__ = [
    "AgentDNA",
    "FileInfo",
    "Message",
    "MessageStatus",
    "MessageType",
    "Strategy",
    "Task",
    "TaskResult",
    "WorkItem",
    "WorkStatus",
]
