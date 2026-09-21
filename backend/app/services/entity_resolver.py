import ipaddress
import re
import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.repositories import graph_repo
from app.schemas.application import ApplicationEvent
from app.services.normalize import sha256_hex

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]")


def _address(v: str) -> str:
    return _WS.sub(" ", _NON_ALNUM.sub(" ", v.lower())).strip()


# entity type -> (ApplicationEvent field, normaliser). Normalising before hashing makes
# "Jane.Doe@Example.com " and "jane.doe@example.com" the same entity.
ENTITY_FIELDS: dict[str, tuple[str, Callable[[str], str]]] = {
    "device": ("device_id", lambda v: v.strip().lower()),
    "email": ("email", lambda v: v.strip().lower()),
    "phone": ("phone", lambda v: re.sub(r"\D", "", v)),
    "ip": ("ip", lambda v: str(ipaddress.ip_address(v.strip()))),
    "address": ("address", _address),
}


def entity_keys(event: ApplicationEvent) -> list[tuple[str, str]]:
    """Sorted (type, sha256(normalised value)) pairs. Raw identifiers never leave this function."""
    keys = set()
    for etype, (field, norm) in ENTITY_FIELDS.items():
        value = norm(getattr(event, field))
        if value:
            keys.add((etype, sha256_hex(value)))
    return sorted(keys)


class EntityResolver:
    """Upserts an application's identifiers as hashed entities and links them to the application."""

    def resolve(self, db: Session, application_id: uuid.UUID, event: ApplicationEvent) -> list[int]:
        keys = entity_keys(event)
        # Only history loads carry a confirmed label; live traffic never sets fraud_flag.
        entity_ids = graph_repo.upsert_entities(db, keys, fraud_flag=event.label() == 1)
        graph_repo.link(db, application_id, entity_ids)
        return entity_ids
