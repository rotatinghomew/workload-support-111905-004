"""记录更正的影响：事实变化、归属变化、已发布比较与未执行计划重核。

已完成的施工不能撤销重演，仅就更正注记；
未执行的复验安排要看更正后的事实是否仍允许；
已发布的质量比较中失去可比观察的项要重新标出。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .attribution import Incident
from .history import ServiceHistory
from .model import Tables


@dataclass
class CorrectionImpact:
    facts: list[str] = field(default_factory=list)
    door_facts: dict[str, list[str]] = field(default_factory=dict)
    contradicted_repairs: list[str] = field(default_factory=list)
    attribution_changes: list[str] = field(default_factory=list)
    invalidated_comparisons: list[str] = field(default_factory=list)
    plan_rechecks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def correction_impacts(
    tables: Tables, as_of: int, incidents: list[Incident]
) -> CorrectionImpact:
    now = ServiceHistory(tables.placements, as_of)
    original = ServiceHistory(tables.placements, 0)
    impact = CorrectionImpact()

    for corr in now.corrections:
        old, new = corr.old, corr.new
        fact = (
            f"{new.id}（{new.received_day} 日收到）更正 {old.id}：部件 {new.part} "
            f"自 {new.from_day} 日起实际在 {new.place}"
            f"（原记录为 {old.place} {old.from_day}–{old.until_day or '今'} 日）"
        )
        impact.facts.append(fact)
        for place in {new.place, old.place}:
            if place in tables.doors:
                impact.door_facts.setdefault(place, []).append(fact)

    # 与有效服役关系矛盾的施工记录：已完成，不可撤销重演，仅注记
    for r in tables.repairs:
        if r.part_in:
            placement = now.at(r.door, r.closed)
            if not (
                placement
                and placement.part == r.part_in
                and placement.from_day == r.closed
            ):
                actual = now.timeline_of(r.part_in)
                where = (
                    "、".join(f"{p.place}（{p.from_day} 日起）" for p in actual)
                    or "无记录"
                )
                impact.contradicted_repairs.append(
                    f"{r.id} 记录换入 {r.part_in}，但 {r.closed} 日 {r.door} "
                    f"实际服役为 {placement.part if placement else '无'}；"
                    f"{r.part_in} 实际在 {where}"
                )
        if r.part_out:
            left = any(
                p.place == r.door and p.part == r.part_out and p.until_day == r.closed
                for p in now.effective
            )
            if not left:
                impact.contradicted_repairs.append(
                    f"{r.id} 记录换出 {r.part_out}，但有效服役关系中 "
                    f"{r.part_out} 未于 {r.closed} 日离开 {r.door}"
                )

    # 归属变化（候选被更正后的事实排除）
    for inc in incidents:
        for h, basis in inc.excluded:
            impact.attribution_changes.append(
                f"{inc.id} 候选 {h.label()} 被排除（{basis}），"
                f"剩余候选：{'、'.join(x.label() for x in inc.candidates) or '无'}"
            )

    # 已发布质量比较中失去可比观察的项
    for corr in now.corrections:
        part = corr.new.part
        impact.invalidated_comparisons.append(
            f"部件 {part} 的服役暴露史：原记录 {corr.old.place} 段不实，"
            f"以其为依据的部件级复发比较失去可比观察"
        )
    for repair_id in sorted(
        {note.split(" ")[0] for note in impact.contradicted_repairs}
    ):
        impact.invalidated_comparisons.append(
            f"{repair_id} 按换入/换出件分组的维修方式比较：部件身份已更正，"
            f"观察窗内承载部件需重算"
        )
    if now.corrections:
        parts = "、".join(c.new.part for c in now.corrections)
        impact.notes.append(
            f"批次合计的成员归属不变（{parts} 均为同批），但部件级拆分反转，"
            f"部件级结论以更正后为准"
        )

    # 未执行的复验安排按更正后事实重核；已动工及事实不可被修订抹去
    started = {
        c.job for c in tables.checks if c.kind in ("started", "removed", "failed")
    }
    for plan in tables.plans:
        if plan.id in started:
            continue
        before = original.at(plan.door, as_of)
        after = now.at(plan.door, as_of)
        if before and after and before.part != after.part:
            impact.plan_rechecks.append(
                f"{plan.id}（{plan.door} {plan.option}）：{plan.door} 实际服役部件由 "
                f"{before.part} 更正为 {after.part}（批次 {now.batch_of(after.part)}），"
                f"假设「{plan.hypothesis}」仍可检验，对象以更正后为准"
            )
    if impact.contradicted_repairs:
        impact.notes.append(
            "与更正矛盾的施工已完成，不可撤销重演，仅注记；"
            "未执行的复验安排已按更正后事实重核"
        )
    return impact
