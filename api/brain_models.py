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
