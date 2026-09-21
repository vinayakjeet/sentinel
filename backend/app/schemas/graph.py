from typing import Literal

from pydantic import BaseModel

NodeType = Literal["application", "device", "email", "phone", "ip", "address"]


class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    fraud: bool


class GraphEdge(BaseModel):
    source: str
    target: str


class EntityGraphResponse(BaseModel):
    """Bipartite application<->entity neighbourhood (2 hops, capped at GRAPH_MAX_NODES)."""

    application_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
