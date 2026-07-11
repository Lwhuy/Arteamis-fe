from typing import List, Literal, Optional

from pydantic import BaseModel, Field

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


class BrainAskEvent(BaseModel):
    """A single SSE event for the graph-aware /brain/ask stream.

    Mirrors the existing ask stream shape (strategy/answer/final_answer/
    complete/error) and adds cited_node_ids for canvas highlighting.
    """

    type: str = Field(..., description="strategy | answer | final_answer | complete | error")
    reasoning: Optional[str] = None
    searches: Optional[list[dict]] = None
    content: Optional[str] = None
    final_answer: Optional[str] = None
    message: Optional[str] = None
    cited_node_ids: list[str] = Field(default_factory=list)
