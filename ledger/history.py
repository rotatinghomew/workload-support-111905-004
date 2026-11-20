"""设备服役关系：故障史随件走、点位史留点位、沿用件保留、更正留痕。"""
from __future__ import annotations

from dataclasses import dataclass

from .model import Placement


@dataclass(frozen=True)
class Correction:
    new: Placement
    old: Placement


class ServiceHistory:
    """某 as_of 日视角下的有效服役关系。

    已应用当日及之前收到的更正；被更正的旧装配保留在源表中，
    只是不再进入有效视图。as_of=0 表示更正前的原始视图。
    """

    def __init__(self, placements: list[Placement], as_of: int):
        self.as_of = as_of
        superseded = {
            p.supersedes for p in placements if p.supersedes and p.received_day <= as_of
        }
        self.effective = [p for p in placements if p.id not in superseded]
        self.corrections = [
            Correction(new=p, old=next(o for o in placements if o.id == p.supersedes))
            for p in placements
            if p.supersedes and p.received_day <= as_of
        ]
        self._batch_of: dict[str, str] = {}
        for p in placements:
            self._batch_of.setdefault(p.part, p.batch)

    def at(self, place: str, day: int) -> Placement | None:
        for p in self.effective:
            if p.place == place and p.covers(day):
                return p
        return None

    def batch_of(self, part: str) -> str | None:
        return self._batch_of.get(part)

    def timeline_of(self, part: str) -> list[Placement]:
        """部件的服役轨迹；故障史随件走，不随点位。"""
        return sorted(
            (p for p in self.effective if p.part == part), key=lambda p: p.from_day
        )
