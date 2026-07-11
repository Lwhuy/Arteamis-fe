from typing import List, Literal

from pydantic import BaseModel

NodeKind = Literal["domain", "topic", "person", "decision", "source"]
EdgeType = Literal[
    "part_of", "mentions", "supersedes", "disagrees", "complements", "agrees"
]


class BrainNode(BaseModel):
    id: str
    kind: NodeKind
    label: str
    salience: float = 0.0


class BrainEdge(BaseModel):
    source: str
    target: str
    type: EdgeType


class BrainGraphResponse(BaseModel):
    nodes: List[BrainNode]
    edges: List[BrainEdge]


class BrainStatusResponse(BaseModel):
    total_sources: int
    built_sources: int
    running: bool


class BrainRebuildRequest(BaseModel):
    mode: Literal["incremental", "full"] = "incremental"


class BrainRebuildResponse(BaseModel):
    command_id: str
