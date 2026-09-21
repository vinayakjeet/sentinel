import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories import graph_repo
from app.schemas.decision import GraphSignals
from app.schemas.graph import EntityGraphResponse, GraphEdge, GraphNode

SIGNAL_DEPTH = 2  # DESIGN §6: 2-hop = applications sharing any entity (app -> entity -> app)
DISPLAY_DEPTH = 3  # the case graph also shows those applications' other identifiers
FANOUT = 200


class GraphService:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def signals(self, db: Session, application_id: uuid.UUID) -> GraphSignals:
        hood = graph_repo.neighbourhood(
            db, application_id, max_depth=SIGNAL_DEPTH, max_nodes=self.s.graph_max_nodes, fanout=FANOUT
        )
        others = [a for a in hood.application_ids if a != application_id]
        known_fraud, velocity = graph_repo.neighbour_counts(db, others)
        return GraphSignals(
            component_size=len(hood.application_ids),
            distinct_names_per_device=graph_repo.distinct_names_per_device(db, application_id),
            known_fraud_2hop=known_fraud,
            component_velocity_24h=velocity,
        )

    def uplift(self, g: GraphSignals) -> float:
        """DESIGN §3: config-driven additive uplift, applied after the model and reported separately."""
        s = self.s
        u = (
            s.uplift_known_fraud_2hop * (g.known_fraud_2hop >= 1)
            + s.uplift_component_size * (g.component_size >= s.uplift_component_size_min)
            + s.uplift_names_per_device * (g.distinct_names_per_device >= s.uplift_names_per_device_min)
        )
        return round(u, 4)

    def graph(self, db: Session, application_id: uuid.UUID) -> EntityGraphResponse | None:
        if not graph_repo.application_exists(db, application_id):
            return None
        hood = graph_repo.neighbourhood(
            db, application_id, max_depth=DISPLAY_DEPTH, max_nodes=self.s.graph_max_nodes, fanout=FANOUT
        )
        apps, ents, links = graph_repo.graph_nodes(db, hood)
        nodes = [
            GraphNode(
                id=f"app:{a.id}",
                type="application",
                label=a.external_ref or str(a.id)[:8],
                fraud=bool(a.is_history and a.fraud_bool == 1),
            )
            for a in apps
        ]
        # Entities are labelled by type + hash prefix: the graph never exposes raw identifiers.
        nodes += [
            GraphNode(id=f"ent:{e.id}", type=e.type, label=f"{e.type} {e.value_hash[:8]}", fraud=e.fraud_flag)
            for e in ents
        ]
        edges = [GraphEdge(source=f"app:{a}", target=f"ent:{e}") for a, e in links]
        return EntityGraphResponse(
            application_id=str(application_id), nodes=nodes, edges=edges, truncated=hood.truncated
        )
