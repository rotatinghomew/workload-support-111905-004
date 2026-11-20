"""通报归属：事件归并、候选假设与服役事实校验、共享成因。

归属可以未定，但同一起通报不能既认作批次故障又认作施工故障；
共享控制器一次停用引起的多条通报不能当作独立的复发证据。
"""
from __future__ import annotations

from dataclasses import dataclass

from .history import ServiceHistory
from .model import Tables

KIND_LABEL = {"part": "部件", "point": "点位", "power": "电源"}
BUCKET_LABEL = {
    "construction": "施工",
    "batch": "批次",
    "power": "电源",
    "undecided": "未定",
}


@dataclass(frozen=True)
class Hypothesis:
    kind: str  # part / point / power
    target: str

    def label(self) -> str:
        return f"{KIND_LABEL[self.kind]}{self.target}"


def parse_hypothesis(token: str) -> Hypothesis:
    if token.startswith("P"):
        return Hypothesis("part", token)
    if token.startswith("K"):
        return Hypothesis("power", token)
    return Hypothesis("point", token)


@dataclass
class Incident:
    id: str
    door: str
    day: int
    signature: str
    report_ids: list[str]
    candidates: list[Hypothesis]  # 与服役事实一致后的未排除范围
    excluded: list[tuple[Hypothesis, str]]  # (假设, 排除依据)

    @property
    def repeats(self) -> int:
        """被归并的重复通报条数。"""
        return len(self.report_ids) - 1

    def bucket(self) -> str:
        """归属桶：仅当候选收敛为单一假设时才落入确认桶，否则未定。

        未定事件只进"未定"桶，绝不同时计入批次与施工。
        """
        if len(self.candidates) != 1:
            return "undecided"
        return {"part": "batch", "point": "construction", "power": "power"}[
            self.candidates[0].kind
        ]


def _consistent(
    h: Hypothesis, door: str, day: int, tables: Tables, history: ServiceHistory
) -> bool:
    if h.kind == "point":
        return h.target == door
    if h.kind == "power":
        return tables.doors[door].power == h.target
    placement = history.at(door, day)
    return placement is not None and placement.part == h.target


def build_incidents(
    tables: Tables, history: ServiceHistory, original: ServiceHistory
) -> list[Incident]:
    """按 incident 归并重复通报，并用服役关系校验候选假设。

    候选与有效服役关系矛盾时排除；若矛盾来自更正，注明更正依据。
    """
    grouped: dict[str, list] = {}
    for rep in tables.reports:
        if rep.kind == "reported":
            grouped.setdefault(rep.incident, []).append(rep)
    incidents: list[Incident] = []
    for inc_id in sorted(grouped):
        reps = grouped[inc_id]
        door, day, signature = reps[0].door, reps[0].day, reps[0].signature
        candidates: list[Hypothesis] = []
        excluded: list[tuple[Hypothesis, str]] = []
        for token in reps[0].candidates:
            h = parse_hypothesis(token)
            if _consistent(h, door, day, tables, history):
                candidates.append(h)
            else:
                basis = (
                    "部件身份更正后该部件当日不在此点位"
                    if _consistent(h, door, day, tables, original)
                    else "当日服役关系不支持该候选"
                )
                excluded.append((h, basis))
        incidents.append(
            Incident(
                inc_id, door, day, signature, [r.id for r in reps], candidates, excluded
            )
        )
    return incidents


@dataclass
class SharedCauseGroup:
    power: str
    day: int
    signature: str
    incident_ids: list[str]

    def label(self) -> str:
        return (
            f"{self.day} 日 {self.power} 下的 {'、'.join(self.incident_ids)}"
            f" 可能为同一次停用"
        )


def shared_cause_groups(
    incidents: list[Incident], tables: Tables
) -> list[SharedCauseGroup]:
    """同日同签名、共享控制器且候选均含该电源的事件，不当作独立复发证据。"""
    groups: list[SharedCauseGroup] = []
    by_key: dict[tuple[int, str], list[Incident]] = {}
    for inc in incidents:
        by_key.setdefault((inc.day, inc.signature), []).append(inc)
    for (day, signature), members in sorted(by_key.items()):
        by_power: dict[str, list[Incident]] = {}
        for inc in members:
            power = tables.doors[inc.door].power
            if any(h.kind == "power" and h.target == power for h in inc.candidates):
                by_power.setdefault(power, []).append(inc)
        for power, incs in sorted(by_power.items()):
            if len(incs) > 1:
                groups.append(
                    SharedCauseGroup(power, day, signature, [i.id for i in incs])
                )
    return groups
