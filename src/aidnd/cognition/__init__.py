"""L3 Cognition — память, отношения, рефлексия (main §5)."""

from .cognition import Cognition, RetrievedContext
from .memory import CognitionStore, MemoryNode, NPCMemory
from .relationships import APPRAISAL_RULES, appraise, edge, gate_open

__all__ = [
    "NPCMemory", "MemoryNode", "CognitionStore", "appraise", "edge", "gate_open",
    "APPRAISAL_RULES", "Cognition", "RetrievedContext",
]
