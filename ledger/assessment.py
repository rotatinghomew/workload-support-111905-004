"""风险暴露与可比较的复发指标。

- 观察窗：关单次日起 window_days 日；同门下一次施工截断；封控与迁移不重启计数。
- 暴露：只数实际开放观察日（open/partial）；绕行、关机日不互相替代；
  漏读日给通行次数上下界；窗口内无记录日为缺观测。
- 复发：重复通报按 incident 归并；漏报区间给可支持的复发范围；
  低于门槛但已证实复发可报告复发证据，不报告未复发。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .attribution import BUCKET_LABEL, Incident, SharedCauseGroup
from .model import Repair, Rule, Tables

OPEN, PARTIAL, BYPASS, OUT, MISSING = "open", "partial", "bypass", "out", "missing"
OBSERVED_STATES = {OPEN, PARTIAL}
STATE_LABEL = {
    OPEN: "开放",
    PARTIAL: "部分开放",
    BYPASS: "绕行",
    OUT: "关机",
    MISSING: "缺观测",
}
STATUS_LABEL = {
    "recurrence_evidence": "有复发证据",
    "cleared": "充分观察无复发",
    "inconclusive_gap": "充分观察但存在漏报区间",
    "insufficient_exposure": "暴露不足不能结论",
}


@dataclass(frozen=True)
class DayObs:
    day: int
    state: str
    uses_low: int
    uses_high: int


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    truncated_by: str | None

    def days(self):
        return range(self.start, self.end + 1)

    def label(self) -> str:
        note = f"（被 {self.truncated_by} 截断）" if self.truncated_by else ""
        return f"{self.start}–{self.end} 日{note}"


def observation_window(repair: Repair, rule: Rule, repairs: list[Repair]) -> Window:
    """关单次日起 window_days 日；同门下一次施工截断（配置已变，观察对象不再相同）。"""
    start = repair.closed + 1
    end = repair.closed + rule.window_days
    truncated_by = None
    later = [r for r in repairs if r.door == repair.door and r.closed > repair.closed]
    if later:
        nxt = min(later, key=lambda r: r.closed)
        if nxt.closed - 1 < end:
            end = nxt.closed - 1
            truncated_by = nxt.id
    return Window(start, end, truncated_by)


@dataclass
class ExposureSummary:
    days: list[DayObs]
    open_days: int  # 实际开放观察日（open + partial）
    full_open_days: int
    partial_days: int
    bypass_days: int
    out_days: int
    missing_days: int
    uses_low: int
    uses_high: int
    sufficiency: str  # sufficient / uncertain / insufficient
    reasons: list[str]

    def state_counts_label(self) -> str:
        parts = [f"开放 {self.full_open_days}"]
        if self.partial_days:
            parts.append(f"部分开放 {self.partial_days}")
        if self.bypass_days:
            parts.append(f"绕行 {self.bypass_days}")
        if self.out_days:
            parts.append(f"关机 {self.out_days}")
        if self.missing_days:
            parts.append(f"缺观测 {self.missing_days}")
        return "，".join(parts) + " 日"


def summarize_exposure(
    window: Window, rule: Rule, tables: Tables, door: str
) -> ExposureSummary:
    by_day = {e.day: e for e in tables.exposure if e.door == door}
    days: list[DayObs] = []
    for d in window.days():
        e = by_day.get(d)
        if e is None:
            days.append(DayObs(d, MISSING, 0, 0))
        else:
            days.append(DayObs(d, e.state, e.uses_low, e.uses_high))
    full_open = sum(1 for x in days if x.state == OPEN)
    partial = sum(1 for x in days if x.state == PARTIAL)
    bypass = sum(1 for x in days if x.state == BYPASS)
    out = sum(1 for x in days if x.state == OUT)
    missing = sum(1 for x in days if x.state == MISSING)
    open_days = full_open + partial
    uses_low = sum(x.uses_low for x in days if x.state in OBSERVED_STATES)
    uses_high = sum(x.uses_high for x in days if x.state in OBSERVED_STATES)

    reasons: list[str] = []
    days_ok = open_days >= rule.min_days
    if uses_low >= rule.min_uses:
        uses_state = "ok"
    elif uses_high < rule.min_uses:
        uses_state = "short"
    else:
        uses_state = "uncertain"
    if not days_ok:
        reasons.append(f"实际开放观察 {open_days}/{rule.min_days} 日")
    if uses_state == "short":
        reasons.append(f"有效通行 {uses_low}–{uses_high} 次低于门槛 {rule.min_uses}")
    elif uses_state == "uncertain":
        reasons.append(
            f"漏读日使有效通行 {uses_low}–{uses_high} 次横跨门槛 {rule.min_uses}，充分性不确定"
        )
    if days_ok and uses_state == "ok":
        sufficiency = "sufficient"
    elif not days_ok or uses_state == "short":
        sufficiency = "insufficient"
    else:
        sufficiency = "uncertain"
    return ExposureSummary(
        days,
        open_days,
        full_open,
        partial,
        bypass,
        out,
        missing,
        uses_low,
        uses_high,
        sufficiency,
        reasons,
    )


@dataclass
class RepairAssessment:
    repair_id: str
    door: str
    method: str
    team: str
    family: str
    rule_id: str
    signature: str
    window: Window
    exposure: ExposureSummary
    confirmed: list[str]  # 窗内已证实事件（重复通报已归并）
    repeats_folded: int
    gap_days: list[int]  # 窗内漏报区间
    count_low: int
    count_high: int
    rate_low: float | None
    rate_high: float | None
    at_risk: bool | None
    status: str
    notes: list[str] = field(default_factory=list)

    def count_label(self) -> str:
        if self.count_low == self.count_high:
            return f"{self.count_low} 起"
        return f"{self.count_low}–{self.count_high} 起"

    def rate_label(self) -> str:
        if self.rate_low is None:
            return "无开放观察日，率不可计"
        lo, hi = f"{self.rate_low:.2f}", f"{self.rate_high:.2f}"
        return lo if lo == hi else f"{lo}–{hi}"


def assess_repairs(
    tables: Tables, incidents: list[Incident], shared: list[SharedCauseGroup]
) -> list[RepairAssessment]:
    gap_by_door: dict[str, list] = {}
    for rep in tables.reports:
        if rep.kind == "gap":
            gap_by_door.setdefault(rep.door, []).append(rep)
    shared_of = {
        inc_id: group for group in shared for inc_id in group.incident_ids
    }
    assessments: list[RepairAssessment] = []
    for repair in tables.repairs:
        for rule in tables.rules:
            window = observation_window(repair, rule, tables.repairs)
            exposure = summarize_exposure(window, rule, tables, repair.door)
            confirmed = [
                i
                for i in incidents
                if i.door == repair.door
                and i.signature == rule.signature
                and i.day in window.days()
            ]
            repeats = sum(i.repeats for i in confirmed)
            gaps = sorted(
                r.day
                for r in gap_by_door.get(repair.door, [])
                if r.signature == rule.signature and r.day in window.days()
            )
            count_low = len(confirmed)
            count_high = count_low + len(gaps)
            if exposure.open_days:
                rate_low: float | None = count_low / exposure.open_days
                rate_high: float | None = count_high / exposure.open_days
                if rate_low >= rule.at_risk_rate:
                    at_risk: bool | None = True
                elif rate_high < rule.at_risk_rate:
                    at_risk = False
                else:
                    at_risk = None
            else:
                rate_low = rate_high = at_risk = None
            if confirmed:
                status = "recurrence_evidence"
            elif exposure.sufficiency == "sufficient" and not gaps:
                status = "cleared"
            elif exposure.sufficiency == "sufficient":
                status = "inconclusive_gap"
            else:
                status = "insufficient_exposure"
            notes: list[str] = []
            if window.truncated_by:
                notes.append(f"观察窗被同门后续施工 {window.truncated_by} 截断")
            if gaps:
                notes.append(
                    f"漏报区间 {gaps}：缺观测期间复发可支持范围取 "
                    f"{count_low}–{count_high} 起"
                )
            for inc in confirmed:
                if inc.id in shared_of:
                    g = shared_of[inc.id]
                    others = "、".join(x for x in g.incident_ids if x != inc.id)
                    notes.append(
                        f"{inc.id} 与 {others} 可能同源于 {g.power} 一次停用，"
                        f"不作独立复发证据"
                    )
            if exposure.sufficiency == "uncertain":
                notes.append("暴露充分性不确定，不能称已充分观察")
            assessments.append(
                RepairAssessment(
                    repair_id=repair.id,
                    door=repair.door,
                    method=repair.method,
                    team=repair.team,
                    family=tables.doors[repair.door].family,
                    rule_id=rule.id,
                    signature=rule.signature,
                    window=window,
                    exposure=exposure,
                    confirmed=[i.id for i in confirmed],
                    repeats_folded=repeats,
                    gap_days=gaps,
                    count_low=count_low,
                    count_high=count_high,
                    rate_low=rate_low,
                    rate_high=rate_high,
                    at_risk=at_risk,
                    status=status,
                    notes=notes,
                )
            )
    return assessments


def breakdown(
    assessments: list[RepairAssessment], incidents: list[Incident], key: str
) -> list[dict]:
    """按维修方式 / 施工队 / 设备族拆解。

    未定归属的事件只计入"未定"桶，绝不同时计入批次与施工。
    """
    by_incident = {i.id: i for i in incidents}
    groups: dict[str, dict] = {}
    for a in assessments:
        k = getattr(a, key)
        g = groups.setdefault(
            k,
            {
                "key": k,
                "repairs": [],
                "statuses": {},
                "incidents": [],
                "buckets": {b: [] for b in BUCKET_LABEL},
            },
        )
        g["repairs"].append(a.repair_id)
        g["statuses"][a.status] = g["statuses"].get(a.status, 0) + 1
        for inc_id in a.confirmed:
            if inc_id not in g["incidents"]:
                g["incidents"].append(inc_id)
                g["buckets"][by_incident[inc_id].bucket()].append(inc_id)
    return [groups[k] for k in sorted(groups)]
