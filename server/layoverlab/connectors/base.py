"""Connector contract (frozen, see docs/CONTRACTS.md) + registry."""

from datetime import date
from typing import Protocol, TypedDict, runtime_checkable


class DayFare(TypedDict):
    origin: str
    dest: str
    dep_date: date
    price_cents: int
    currency: str
    deep_link: str | None


@runtime_checkable
class Connector(Protocol):
    name: str

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]: ...

    async def routes_from(self, origin: str) -> list[str]: ...

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None: ...


class ConnectorError(Exception):
    """Recoverable connector failure (bad response, rate limited, ...)."""


class ConnectorDisabled(Exception):
    """Connector cannot run (missing token, feature flag off)."""


_REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> Connector:
    _REGISTRY[connector.name] = connector
    return connector


def get_connector(name: str) -> Connector:
    if name not in _REGISTRY:
        raise KeyError(f"unknown connector: {name}")
    return _REGISTRY[name]


def all_connectors() -> dict[str, Connector]:
    return dict(_REGISTRY)


def load_default_connectors() -> None:
    """Import connector modules for their registration side effects."""
    from layoverlab.connectors import google_flights, ryanair, travelpayouts  # noqa: F401
