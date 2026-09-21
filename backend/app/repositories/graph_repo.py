"""All entity-graph SQL. The graph is bipartite: applications <-> entities via entity_links."""

import uuid
from dataclasses import dataclass

from sqlalchemy import bindparam, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import ARRAY, UUID, insert
from sqlalchemy.orm import Session

from app.models import Application, Entity, EntityLink


def upsert_entities(db: Session, keys: list[tuple[str, str]], fraud_flag: bool) -> list[int]:
    """Insert unseen (type, value_hash) pairs, OR-in the fraud flag, return ids.

    `keys` must be sorted so concurrent requests touching the same entities lock them in the same order.
    Uses DO NOTHING + a targeted UPDATE rather than DO UPDATE, so re-seeing an entity takes no row lock.
    """
    db.execute(
        insert(Entity)
        .values([{"type": t, "value_hash": h, "fraud_flag": fraud_flag} for t, h in keys])
        .on_conflict_do_nothing(constraint="uq_entities_type_value_hash")
    )
    match = tuple_(Entity.type, Entity.value_hash).in_(keys)
    if fraud_flag:
        db.execute(update(Entity).where(match, Entity.fraud_flag.is_(False)).values(fraud_flag=True))
    return list(db.scalars(select(Entity.id).where(match).order_by(Entity.id)))


def link(db: Session, application_id: uuid.UUID, entity_ids: list[int]) -> None:
    db.execute(
        insert(EntityLink)
        .values([{"application_id": application_id, "entity_id": e} for e in entity_ids])
        .on_conflict_do_nothing(constraint="uq_entity_links_app_entity")
    )


# Bounded breadth-first walk over the bipartite graph. Three independent bounds:
#   :fanout    rows per node expansion (a shared IP with 10k applications contributes at most :fanout)
#   :row_cap   total walk rows; Postgres evaluates a recursive CTE lazily, so the LIMIT stops the recursion
#   :max_nodes distinct nodes returned, nearest first
_NEIGHBOURHOOD = text(
    """
    WITH RECURSIVE walk(app_id, entity_id, depth) AS (
        SELECT CAST(:app_id AS uuid), CAST(NULL AS bigint), 0
      UNION ALL
        SELECT nxt.app_id, nxt.entity_id, w.depth + 1
        FROM walk w
        CROSS JOIN LATERAL (
            (SELECT CAST(NULL AS uuid) AS app_id, l.entity_id
               FROM entity_links l
              WHERE w.app_id IS NOT NULL AND l.application_id = w.app_id
              LIMIT :fanout)
            UNION ALL
            (SELECT l.application_id, CAST(NULL AS bigint)
               FROM entity_links l
              WHERE w.entity_id IS NOT NULL AND l.entity_id = w.entity_id
              LIMIT :fanout)
        ) nxt
        WHERE w.depth < :max_depth
    ),
    bounded AS (SELECT * FROM walk LIMIT :row_cap)
    SELECT app_id, entity_id, min(depth) AS depth
      FROM bounded
     GROUP BY app_id, entity_id
     ORDER BY min(depth), app_id, entity_id
     LIMIT :node_limit
    """
)


@dataclass(frozen=True)
class Neighbourhood:
    application_ids: list[uuid.UUID]  # includes the root
    entity_ids: list[int]
    truncated: bool


def neighbourhood(db: Session, app_id: uuid.UUID, max_depth: int, max_nodes: int, fanout: int) -> Neighbourhood:
    rows = db.execute(
        _NEIGHBOURHOOD,
        {
            "app_id": app_id,
            "max_depth": max_depth,
            "fanout": fanout,
            "row_cap": max_nodes * 10,
            "node_limit": max_nodes + 1,
        },
    ).all()
    truncated = len(rows) > max_nodes
    rows = rows[:max_nodes]
    return Neighbourhood(
        application_ids=[r.app_id for r in rows if r.app_id is not None],
        entity_ids=[r.entity_id for r in rows if r.entity_id is not None],
        truncated=truncated,
    )


_SIGNALS = text(
    """
    SELECT
        count(*) FILTER (WHERE a.is_history AND a.fraud_bool = 1)                AS known_fraud,
        count(*) FILTER (WHERE a.created_at >= now() - interval '24 hours')       AS velocity_24h
    FROM applications a
    WHERE a.id = ANY(:others)
    """
).bindparams(bindparam("others", type_=ARRAY(UUID(as_uuid=True))))

_NAMES_PER_DEVICE = text(
    """
    SELECT coalesce(max(n), 0) FROM (
        SELECT count(DISTINCT a.name_hash) AS n
          FROM entity_links mine
          JOIN entities e      ON e.id = mine.entity_id AND e.type = 'device'
          JOIN entity_links l  ON l.entity_id = e.id
          JOIN applications a  ON a.id = l.application_id
         WHERE mine.application_id = :app_id
         GROUP BY e.id
    ) per_device
    """
)


def neighbour_counts(db: Session, others: list[uuid.UUID]) -> tuple[int, int]:
    if not others:
        return 0, 0
    row = db.execute(_SIGNALS, {"others": others}).one()
    return int(row.known_fraud), int(row.velocity_24h)


def distinct_names_per_device(db: Session, app_id: uuid.UUID) -> int:
    return int(db.execute(_NAMES_PER_DEVICE, {"app_id": app_id}).scalar_one())


def application_exists(db: Session, app_id: uuid.UUID) -> bool:
    return db.get(Application, app_id) is not None


def graph_nodes(
    db: Session, hood: Neighbourhood
) -> tuple[list[Application], list[Entity], list[tuple[uuid.UUID, int]]]:
    """Rows for the nodes in `hood`, plus every link between them (edges are induced by the node set)."""
    apps = list(db.scalars(select(Application).where(Application.id.in_(hood.application_ids))))
    if not hood.entity_ids:
        return apps, [], []
    ents = list(db.scalars(select(Entity).where(Entity.id.in_(hood.entity_ids))))
    edges = db.execute(
        select(EntityLink.application_id, EntityLink.entity_id).where(
            EntityLink.application_id.in_(hood.application_ids),
            EntityLink.entity_id.in_(hood.entity_ids),
        )
    ).all()
    return apps, ents, [(a, e) for a, e in edges]
