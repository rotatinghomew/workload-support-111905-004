"""放行/暂停决定：原因分类可查。

院管员查一条决定时，应看得到是暴露不足、仍有复发证据，
还是没有可用的替代门——三者分列，不并成一个故障率。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .assessment import RepairAssessment
from .attribution import Incident
from .corrections import CorrectionImpact
from .model import Tables
from .planning import OptionEval, door_statuses

INSUFFICIENT = "暴露不足"
RECURRENCE = "仍有复发证据"
NO_RESERVE = "没有可用的替代门"
FAILED_CHECK = "复验失败"
CLEARED = "充分观察无复发"
OFF_SIGNATURE = "非约定签名另案"
RESERVE_READY = "替代门已确认"
CORRECTED = "部件身份已更正"
NO_DATA = "无观测记录"


@dataclass
class Reason:
    category: str
    detail: str


@dataclass
class DoorDecision:
    door: str
    site: str
    access: str
    decision: str
    reasons: list[Reason] = field(default_factory=list)


def door_decisions(
    tables: Tables,
    assessments: list[RepairAssessment],
    incidents: list[Incident],
    evals: list[OptionEval],
    impacts: CorrectionImpact,
) -> list[DoorDecision]:
    statuses = door_statuses(tables)
    assess_by_door: dict[str, list[RepairAssessment]] = {}
    for a in assessments:
        assess_by_door.setdefault(a.door, []).append(a)
    incidents_by_id = {i.id: i for i in incidents}
    eval_by_plan = {e.plan_id: e for e in evals}
    decisions: list[DoorDecision] = []
    for door_id in sorted(tables.doors):
        door = tables.doors[door_id]
        reasons: list[Reason] = []
        status = statuses[door_id]
        if not status.up:
            reasons.append(Reason(FAILED_CHECK, status.note))
        door_assess = assess_by_door.get(door_id, [])
        for a in door_assess:
            if a.status == "recurrence_evidence":
                for inc_id in a.confirmed:
                    inc = incidents_by_id[inc_id]
                    cands = "、".join(h.label() for h in inc.candidates) or "无剩余候选"
                    reasons.append(
                        Reason(
                            RECURRENCE,
                            f"{inc_id}（{inc.day} 日，{a.repair_id} 观察窗内）"
                            f"归属未定：{cands}",
                        )
                    )
            elif a.status == "insufficient_exposure":
                why = "；".join(a.exposure.reasons) or "暴露不足"
                reasons.append(
                    Reason(INSUFFICIENT, f"{a.repair_id} 观察窗 {a.window.label()}：{why}")
                )
            elif a.status == "inconclusive_gap":
                reasons.append(
                    Reason(
                        INSUFFICIENT,
                        f"{a.repair_id} 存在漏报区间 {a.gap_days}，不能排除复发",
                    )
                )
            elif a.status == "cleared":
                reasons.append(
                    Reason(CLEARED, f"{a.repair_id} 充分观察无「{a.signature}」复发")
                )
        confirmed_ids = {i for a in door_assess for i in a.confirmed}
        for inc in incidents:
            if (
                inc.door == door_id
                and inc.id not in confirmed_ids
                and tables.rule_for(inc.signature) is None
            ):
                reasons.append(
                    Reason(
                        OFF_SIGNATURE,
                        f"{inc.id}（{inc.signature}）不在约定复发比较内，另案处理",
                    )
                )
        for plan in tables.plans:
            if plan.door != door_id:
                continue
            for b in eval_by_plan[plan.id].blocks:
                if "替代门" in b:
                    reasons.append(Reason(NO_RESERVE, f"{plan.id}：{b}"))
        for c in tables.checks:
            if c.kind == "ready" and c.related_door == door_id:
                reasons.append(
                    Reason(RESERVE_READY, f"{c.id}：本场通行回执确认可作替代门")
                )
        for note in impacts.door_facts.get(door_id, []):
            reasons.append(Reason(CORRECTED, note))
        if not status.up:
            decision = "暂停使用"
        elif any(r.category == RECURRENCE for r in reasons):
            decision = "限制：不得作「已修好」结论"
        elif any(r.category == INSUFFICIENT for r in reasons):
            decision = "不可结论"
        elif any(r.category == CLEARED for r in reasons):
            decision = "放行（就约定签名）"
        else:
            decision = "无观测记录"
            reasons.append(Reason(NO_DATA, "无维修、通报与暴露记录"))
        decisions.append(
            DoorDecision(door_id, door.site, door.access, decision, reasons)
        )
    return decisions
