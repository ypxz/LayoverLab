"""Practical warnings for self-transfer itineraries: risk, baggage, tight connections, visa hints."""

import csv
import io
import itertools
from functools import lru_cache
from importlib.resources import files

from layoverlab.engine.graph import FareSlice
from layoverlab.engine.models import Itinerary

DISCLAIMER = "Estimates from cached data — always verify times, prices and entry rules before booking."


@lru_cache
def _visa_zones() -> dict[str, str]:
    text = files("layoverlab.engine").joinpath("data", "visa_zones.csv").read_text(encoding="utf-8")
    return {row["country_code"]: row["zone"] for row in csv.DictReader(io.StringIO(text))}


def build_warnings(itin: Itinerary, fslice: FareSlice, origin_country: str | None) -> list[str]:
    warnings: list[str] = []
    flight_legs = [leg for leg in itin.legs if leg.mode == "flight"]
    ground_legs = [leg for leg in itin.legs if leg.mode == "ground"]

    if len(itin.legs) > 1:
        warnings.append(
            "Self-transfer: separate tickets. No airline protection if you miss a connection — "
            "you carry the risk."
        )
    if len(flight_legs) > 1:
        warnings.append("Checked baggage must be collected and re-checked at every stopover.")
    for prev, nxt in itertools.pairwise(itin.legs):
        if (nxt.dep_date - prev.dep_date).days == 0:
            warnings.append(
                f"Tight same-day self-transfer in {prev.dest}: verify actual flight times "
                f"(recommended buffer: 3h+ same airport, 6h+ with airport change)."
            )
    for leg in ground_legs:
        warnings.append(
            f"Ground segment {leg.origin}→{leg.dest} ({leg.source}): buy this ticket separately."
        )

    zones = _visa_zones()
    origin_zone = zones.get(origin_country or "", None)
    seen: set[str] = set()
    for stop in itin.stopovers:
        country = fslice.airport_country.get(stop.iata)
        if not country or country in seen:
            continue
        seen.add(country)
        if zones.get(country) is None or zones.get(country) != origin_zone:
            warnings.append(
                f"Stopover in {stop.iata} ({country}, {stop.nights} night(s)): "
                f"check visa/entry requirements for your passport."
            )
    warnings.append(DISCLAIMER)
    return warnings
