"""源记录模型与装载。

均为合成运营记录；空值表示没有声明事实，不等于零；时段左闭右开。
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Door:
    id: str
    site: str
    family: str
    access: str
    power: str


@dataclass(frozen=True)
class Placement:
    """读头服役记录（左闭右开）；supersedes 指向被更正的旧记录。"""

    id: str
    place: str
    part: str
    batch: str
    from_day: int
    until_day: int | None
    received_day: int
    supersedes: str

    def covers(self, day: int) -> bool:
        return self.from_day <= day and (self.until_day is None or day < self.until_day)


@dataclass(frozen=True)
class Repair:
    id: str
    door: str
    method: str
    team: str
    closed: int
    part_kept: str
    part_in: str
    part_out: str


@dataclass(frozen=True)
class Exposure:
    id: str
    door: str
    day: int
    state: str  # open / partial / bypass / out
    uses_low: int
    uses_high: int


@dataclass(frozen=True)
class Report:
    id: str
    door: str
    day: int
    incident: str  # 空 = 漏报区间记录
    kind: str  # reported / gap
    signature: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    id: str
    signature: str
    window_days: int
    min_uses: int
    min_days: int
    at_risk_rate: float


@dataclass(frozen=True)
class PlanOption:
    id: str
    door: str
    slot: str
    option: str
    worker: str
    target: str  # part 列：备件或控制器等待测对象
    hypothesis: str
    reserve_door: str

    @property
    def day(self) -> int:
        m = re.fullmatch(r"(\d+)(AM|PM)", self.slot)
        if not m:
            raise ValueError(f"无法解析排班 slot：{self.slot!r}")
        return int(m.group(1))

    @property
    def session(self) -> str:
        m = re.fullmatch(r"(\d+)(AM|PM)", self.slot)
        if not m:
            raise ValueError(f"无法解析排班 slot：{self.slot!r}")
        return m.group(2)

    @property
    def test_object(self) -> str:
        """待测对象：part 列的备件；断电测量时为假设列中的控制器。"""
        if self.target:
            return self.target
        if self.hypothesis.startswith("K"):
            return self.hypothesis
        return ""


@dataclass(frozen=True)
class Check:
    id: str
    job: str
    seq: int
    kind: str
    related_door: str


@dataclass
class Tables:
    doors: dict[str, Door]
    placements: list[Placement]
    repairs: list[Repair]
    exposure: list[Exposure]
    reports: list[Report]
    rules: list[Rule]
    plans: list[PlanOption]
    checks: list[Check]

    def rule_for(self, signature: str) -> Rule | None:
        for rule in self.rules:
            if rule.signature == signature:
                return rule
        return None


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as src:
        return list(csv.DictReader(src))


def load_tables(fixtures_dir: str | Path) -> Tables:
    base = Path(fixtures_dir)
    doors = {r["id"]: Door(**r) for r in _rows(base / "doors.csv")}
    placements = [
        Placement(
            id=r["id"],
            place=r["place"],
            part=r["part"],
            batch=r["batch"],
            from_day=int(r["from_day"]),
            until_day=int(r["until_day"]) if r["until_day"] else None,
            received_day=int(r["received_day"]),
            supersedes=r["supersedes"],
        )
        for r in _rows(base / "components.csv")
    ]
    repairs = [
        Repair(
            id=r["id"],
            door=r["door"],
            method=r["method"],
            team=r["team"],
            closed=int(r["closed"]),
            part_kept=r["part_kept"],
            part_in=r["part_in"],
            part_out=r["part_out"],
        )
        for r in _rows(base / "repairs.csv")
    ]
    exposure = [
        Exposure(
            id=r["id"],
            door=r["door"],
            day=int(r["day"]),
            state=r["state"],
            uses_low=int(r["uses_low"]),
            uses_high=int(r["uses_high"]),
        )
        for r in _rows(base / "exposure.csv")
    ]
    reports = [
        Report(
            id=r["id"],
            door=r["door"],
            day=int(r["day"]),
            incident=r["incident"],
            kind=r["kind"],
            signature=r["signature"],
            candidates=tuple(t for t in r["candidate"].split(";") if t),
        )
        for r in _rows(base / "reports.csv")
    ]
    rules = [
        Rule(
            id=r["id"],
            signature=r["signature"],
            window_days=int(r["window_days"]),
            min_uses=int(r["min_uses"]),
            min_days=int(r["min_days"]),
            at_risk_rate=float(r["at_risk_rate"]),
        )
        for r in _rows(base / "rules.csv")
    ]
    plans = [
        PlanOption(
            id=r["id"],
            door=r["door"],
            slot=r["slot"],
            option=r["option"],
            worker=r["worker"],
            target=r["part"],
            hypothesis=r["hypothesis"],
            reserve_door=r["reserve_door"],
        )
        for r in _rows(base / "maintenance.csv")
    ]
    checks = [
        Check(
            id=r["id"],
            job=r["job"],
            seq=int(r["seq"]),
            kind=r["kind"],
            related_door=r["related_door"],
        )
        for r in _rows(base / "checks.csv")
    ]
    return Tables(doors, placements, repairs, exposure, reports, rules, plans, checks)
