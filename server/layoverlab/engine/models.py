"""Engine data contracts (frozen, see docs/CONTRACTS.md)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SearchParams(BaseModel):
    origin: str
    dest: str
    date_from: date
    date_to: date
    round_trip: bool = False
    trip_min_days: int | None = None
    trip_max_days: int | None = None
    stop_min_hours: int = Field(default=4, ge=0, le=24 * 14)
    stop_max_days: int = Field(default=7, ge=0, le=30)
    max_stops: int = Field(default=3, ge=0, le=5)
    top_k: int = Field(default=10, ge=1, le=25)
    sort: Literal["cheapest", "fastest", "best"] = "cheapest"

    @field_validator("origin", "dest")
    @classmethod
    def _upper_iata(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3:
            raise ValueError("IATA code must be 3 letters")
        return v


class Leg(BaseModel):
    origin: str
    dest: str
    dep_date: date
    mode: str  # "flight" | "ground"
    price_cents: int
    currency: str = "EUR"
    source: str
    deep_link: str | None = None
    fetched_at: datetime
    dep_time: datetime | None = None  # local departure time, resolved during verification
    arr_time: datetime | None = None  # local arrival time, resolved during verification


class Stopover(BaseModel):
    iata: str
    nights: int


class Itinerary(BaseModel):
    id: str | None = None
    legs: list[Leg]
    total_cents: int
    currency: str = "EUR"
    stopovers: list[Stopover]
    warnings: list[str]
    verified: bool = False

    @property
    def signature(self) -> tuple[str, ...]:
        return tuple([self.legs[0].origin, *[leg.dest for leg in self.legs]])
