"""City generation parameters. Passed from outside (debug screen / game), generator details
hidden behind this simple contract.

Key functions
-------------
CityParams : dataclass for city generation parameters (seed, size, key_buildings, flags).
normalized(self) -> CityParams : validate and clamp parameters to safe ranges."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CityParams:
    seed: int = 1
    width: int = 980
    height: int = 700
    key_buildings: int = 8          # how many key buildings to place (in uniformly spaced houses)
    river: bool = True              # does a river divide the city (→ bridges)
    walls: bool = True              # is it walled (→ gates)
    wards: int | None = None        # number of wards (None — generator's choice)
    segment: float | None = None    # target street segment length (None — auto by median)

    def normalized(self) -> CityParams:
        """Protection from garbage values."""
        return CityParams(
            seed=int(self.seed),
            width=max(320, min(2000, int(self.width))),
            height=max(240, min(2000, int(self.height))),
            key_buildings=max(0, min(64, int(self.key_buildings))),
            river=bool(self.river),
            walls=bool(self.walls),
            wards=(None if self.wards is None else max(1, min(12, int(self.wards)))),
            segment=(None if self.segment is None else max(8.0, min(80.0, float(self.segment)))),
        )
