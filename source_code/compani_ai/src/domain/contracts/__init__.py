"""Domain data contracts shared by all agents."""

from .agent_dna import AgentDNA
from .error_codes import ErrorCode
from .message import Message, MessageStatus, MessageType
from .review_result import ReviewDecision, ReviewResult
from .strategy import AgentRole, Strategy, Task
from .task_result import FileInfo, TaskResult
from .work_item import WorkItem, WorkStatus

__all__ = [
    "AgentDNA",
    "AgentRole",
    "ErrorCode",
    "FileInfo",
    "Message",
    "MessageStatus",
    "MessageType",
    "ReviewDecision",
    "ReviewResult",
    "Strategy",
    "Task",
    "TaskResult",
    "WorkItem",
    "WorkStatus",
]
