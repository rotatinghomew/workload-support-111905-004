"""复验安排：回执约束、院级通行保障、资源冲突与方案比较。

- 复验必须能区分开放的故障假设；区分不了的组合要指明盲点。
- 任何院在有人通行时不得同时失掉所有符合该院通行要求的门。
- 开始停用前需本场现场回执确认替代门可用；复验失败保住尚可用入口，
  尚未拆的备用门不照原计划置为停用。
- 换件验证若只是把待确认部件移到别处，另一位置按新风险与可通行情况重核；
  依赖同一共同部件的两扇门不当作两个独立证据。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .attribution import Incident, SharedCauseGroup
from .history import ServiceHistory
from .model import PlanOption, Tables

SWAP_OPTIONS = ("换读头", "交叉试用")


@dataclass
class DoorStatus:
    door: str
    up: bool
    note: str


def door_statuses(tables: Tables) -> dict[str, DoorStatus]:
    """由现场回执推断门当前状态：已拆卸或复验失败的门保持停用。"""
    statuses = {d: DoorStatus(d, True, "在役") for d in tables.doors}
    by_job: dict[str, list] = {}
    for c in tables.checks:
        by_job.setdefault(c.job, []).append(c)
    for job, cs in by_job.items():
        kinds = {c.kind for c in cs}
        door = cs[0].related_door
        if "failed" in kinds:
            statuses[door] = DoorStatus(door, False, f"{job} 复验失败，门保持停用")
        elif "removed" in kinds:
            statuses[door] = DoorStatus(door, False, f"{job} 已拆卸未恢复")
    return statuses


def suspect_parts(tables: Tables) -> dict[str, str]:
    """复验失败涉及的待确认备件：part -> 说明。"""
    plans = {p.id: p for p in tables.plans}
    suspects: dict[str, str] = {}
    for c in tables.checks:
        if c.kind == "failed":
            plan = plans[c.job]
            if plan.target:
                suspects[plan.target] = (
                    f"{c.job} 复验失败，备件 {plan.target} 身份待复核"
                )
    return suspects


def unaccounted_parts(tables: Tables, history: ServiceHistory) -> set[str]:
    """回执显示已拆卸、但服役关系中无去向记录的部件。"""
    plans = {p.id: p for p in tables.plans}
    parts: set[str] = set()
    for c in tables.checks:
        if c.kind != "removed":
            continue
        plan = plans[c.job]
        placement = history.at(c.related_door, plan.day)
        if placement is None:
            continue
        part = placement.part
        timeline = history.timeline_of(part)
        still_serving = [
            p for p in timeline if p.place != "store" and p.until_day is None
        ]
        in_store = [p for p in timeline if p.place == "store"]
        if still_serving and not in_store:
            parts.add(part)
    return parts


def missing_whereabouts(tables: Tables, history: ServiceHistory) -> list[str]:
    """已拆卸但去向未回报的部件（班组应逐台回报拆卸与备件实际去向）。"""
    plans = {p.id: p for p in tables.plans}
    missing: list[str] = []
    for c in tables.checks:
        if c.kind != "removed":
            continue
        plan = plans[c.job]
        placement = history.at(c.related_door, plan.day)
        if placement is None:
            continue
        part = placement.part
        if part in unaccounted_parts(tables, history):
            missing.append(
                f"{part} 已于 {c.related_door} 拆卸（{c.job}），"
                f"服役关系中无入库或再装记录，去向未回报"
            )
    return missing


def reserve_receipts(plan: PlanOption, tables: Tables) -> list[str]:
    """替代门在本场（同 slot）且先于本工序的通行回执。"""
    plans = {p.id: p for p in tables.plans}
    first_seq = min((c.seq for c in tables.checks if c.job == plan.id), default=None)
    receipts: list[str] = []
    for c in tables.checks:
        if c.kind != "ready" or c.related_door != plan.reserve_door:
            continue
        if plans[c.job].slot != plan.slot:
            continue
        if first_seq is not None and c.seq >= first_seq:
            continue
        receipts.append(c.id)
    return receipts


def deactivation_set(plan: PlanOption, tables: Tables) -> list[str]:
    """该选项执行期间受限的门。断电测量波及同一控制器的所有门。"""
    if plan.option == "断电测量":
        return sorted(
            d.id for d in tables.doors.values() if d.power == plan.test_object
        )
    if plan.option in SWAP_OPTIONS:
        return [plan.door]
    return []  # 试通行：替代门可用性验证，不停用


def coverage_problems(
    tables: Tables, down: set[str], extra: set[str]
) -> list[str]:
    """院级通行保障：每个院每种通行要求至少保留一扇可用门。"""
    problems: list[str] = []
    by_site: dict[str, list] = {}
    for d in tables.doors.values():
        by_site.setdefault(d.site, []).append(d)
    for site, ds in sorted(by_site.items()):
        for access in sorted({d.access for d in ds}):
            usable = [
                d.id
                for d in ds
                if d.access == access and d.id not in down and d.id not in extra
            ]
            if not usable:
                problems.append(
                    f"{site}将同时失掉所有符合「{access}」通行要求的门"
                )
    return problems


def affected_users(
    tables: Tables, down: set[str], deactivated: set[str], slot: str
) -> list[str]:
    """受限期间可用门减少（但未归零）的使用方。"""
    out: list[str] = []
    by_site: dict[str, list] = {}
    for d in tables.doors.values():
        by_site.setdefault(d.site, []).append(d)
    for site, ds in sorted(by_site.items()):
        for access in sorted({d.access for d in ds}):
            doors_acc = [d.id for d in ds if d.access == access]
            before = [d for d in doors_acc if d not in down]
            after = [d for d in before if d not in deactivated]
            if after and len(after) < len(before):
                out.append(
                    f"{slot} {site}「{access}」使用方：可用门 "
                    f"{'、'.join(before)} → {'、'.join(after)}"
                )
    return out


def discrimination(
    plan: PlanOption,
    tables: Tables,
    incidents: list[Incident],
    suspects: dict[str, str],
) -> tuple[list[str], list[str]]:
    """该选项能区分哪些开放假设、不能区分哪些（复验必须能区分开放的故障假设）。"""
    discriminates: list[str] = []
    blind: list[str] = []
    if plan.option in SWAP_OPTIONS:
        open_here = [i for i in incidents if i.door == plan.door and i.candidates]
        kinds_open = {h.kind for i in open_here for h in i.candidates}
        if not open_here:
            blind.append(
                f"{plan.door} 无未决归属事件；其缺口是暴露观察，换件不能替代开放观察"
            )
        else:
            if "part" in kinds_open:
                discriminates.append(
                    "部件 ↔ 其余：换装已知良好备件后观察是否复发"
                )
            rest = kinds_open - {"part"}
            if len(rest) >= 2:
                blind.append(
                    "不能区分 "
                    + "、".join(sorted(rest))
                    + "（部件之外的因素未隔离，需配合对应测量）"
                )
        if plan.target in suspects:
            blind.append(f"备件 {plan.target} 身份待复核，区分效力以其复核为前提")
    elif plan.option == "断电测量":
        target = plan.test_object
        related = [
            i
            for i in incidents
            if tables.doors[i.door].power == target
            and any(h.kind == "power" and h.target == target for h in i.candidates)
        ]
        if related:
            ids = "、".join(i.id for i in related)
            discriminates.append(
                f"电源 {target} ↔ 其余：直接测量共享控制器（涉及 {ids}；"
                f"若成立则并为一次共享停用，不作独立复发证据）"
            )
        else:
            blind.append(f"无候选含 {target} 的未决事件")
    elif plan.option == "试通行":
        discriminates.append("替代门本场可用性（不隔离故障假设）")
    return discriminates, blind


@dataclass
class OptionEval:
    plan_id: str
    execution: str  # completed / failed / requested / planned
    deactivates: list[str]
    discriminates: list[str]
    blind_spots: list[str]
    conditions: list[str]
    blocks: list[str]
    results: list[str]
    verdict: str  # completed / failed / executable / conditional / blocked


def evaluate_options(
    tables: Tables, incidents: list[Incident]
) -> list[OptionEval]:
    statuses = door_statuses(tables)
    down = {d for d, s in statuses.items() if not s.up}
    suspects = suspect_parts(tables)
    kinds_by_job: dict[str, set] = {}
    for c in tables.checks:
        kinds_by_job.setdefault(c.job, set()).add(c.kind)
    evals: list[OptionEval] = []
    for plan in tables.plans:
        kinds = kinds_by_job.get(plan.id, set())
        if "failed" in kinds:
            execution = "failed"
        elif plan.option == "试通行" and "ready" in kinds:
            execution = "completed"
        elif kinds:
            execution = "requested"
        else:
            execution = "planned"
        deactivates = deactivation_set(plan, tables)
        discriminates, blind_spots = discrimination(plan, tables, incidents, suspects)
        conditions: list[str] = []
        blocks: list[str] = []
        results: list[str] = []
        if execution == "failed":
            results.append(
                f"复验失败：在备件 {plan.target} 为良好件的前提下指向点位/电源；"
                f"{plan.target} 转为待确认，尚未拆的备用门不照原计划置为停用"
            )
        if execution == "completed" and plan.option == "试通行":
            results.append(f"{plan.door} 本场（{plan.slot}）可作替代门")
        if plan.target in suspects and execution != "failed":
            conditions.append(suspects[plan.target])
        if plan.reserve_door:
            reserve = tables.doors[plan.reserve_door]
            door = tables.doors[plan.door]
            if reserve.access != door.access:
                blocks.append(
                    f"替代门 {plan.reserve_door}（{reserve.access}）不符合 "
                    f"{door.site}「{door.access}」通行要求"
                )
            elif not statuses[plan.reserve_door].up:
                blocks.append(
                    f"替代门 {plan.reserve_door} 不可用："
                    f"{statuses[plan.reserve_door].note}"
                )
            else:
                receipts = reserve_receipts(plan, tables)
                if receipts:
                    results.append(
                        f"替代门 {plan.reserve_door} 本场回执：{'、'.join(receipts)}"
                    )
                else:
                    conditions.append(
                        f"替代门 {plan.reserve_door} 需 {plan.slot} 本场通行回执"
                    )
        if execution in ("requested", "planned"):
            blocks.extend(coverage_problems(tables, down, set(deactivates)))
        if plan.target:
            same = sorted(
                q.id for q in tables.plans if q.id != plan.id and q.target == plan.target
            )
            if same:
                conditions.append(
                    f"{plan.target} 同为 {'、'.join(same)} 的待测件，"
                    f"结果不互为独立证据"
                )
        if execution in ("failed", "completed"):
            verdict = execution
        elif blocks:
            verdict = "blocked"
        elif conditions:
            verdict = "conditional"
        else:
            verdict = "executable"
        evals.append(
            OptionEval(
                plan.id,
                execution,
                deactivates,
                discriminates,
                blind_spots,
                conditions,
                blocks,
                results,
                verdict,
            )
        )
    return evals


@dataclass
class Arrangement:
    name: str
    option_ids: list[str]
    questions: list[str]  # 可消除的疑问
    restrictions: list[str]  # 仍受限制的时段
    affected: list[str]  # 受影响的使用方
    blocked: list[str]  # 被阻塞的选项及原因
    notes: list[str] = field(default_factory=list)


def compare_arrangements(
    tables: Tables, evals: list[OptionEval]
) -> list[Arrangement]:
    """比较几个复验安排：消除的疑问、仍受限制的时段、受影响的使用方。"""
    by_id = {e.plan_id: e for e in evals}
    plans = {p.id: p for p in tables.plans}
    statuses = door_statuses(tables)
    down = {d for d, s in statuses.items() if not s.up}

    def compose(name: str, ids: list[str]) -> Arrangement:
        questions: list[str] = []
        restrictions: list[str] = [
            f"{d} 自回执记录起停用（{statuses[d].note}），恢复时间未定"
            for d in sorted(down)
        ]
        affected: list[str] = []
        blocked: list[str] = []
        notes: list[str] = []
        deactivated_by_slot: dict[str, set] = {}
        for pid in ids:
            e = by_id[pid]
            p = plans[pid]
            if e.blocks:
                blocked.append(f"{pid} 不可执行：{'；'.join(e.blocks)}")
                continue
            questions.extend(f"{pid}：{q}" for q in e.discriminates)
            notes.extend(f"{pid} 前提：{c}" for c in e.conditions)
            for d in e.deactivates:
                if d not in down:
                    restrictions.append(f"{d} {p.slot} 受限（{p.option}）")
                deactivated_by_slot.setdefault(p.slot, set()).add(d)
        for slot in sorted(deactivated_by_slot):
            affected.extend(
                affected_users(tables, down, deactivated_by_slot[slot], slot)
            )
        return Arrangement(
            name, ids, questions, restrictions, affected, blocked, notes
        )

    live = [
        p.id
        for p in tables.plans
        if by_id[p.id].execution in ("requested", "planned")
    ]
    feasible = [pid for pid in live if not by_id[pid].blocks]
    arrangements = [compose("推进全部可执行项", feasible)]
    power_only = [pid for pid in feasible if plans[pid].option == "断电测量"]
    if power_only and power_only != feasible:
        arrangements.append(compose("仅断电测量", power_only))
    if set(live) != set(feasible):
        arrangements.append(compose("全部未执行项（含被阻塞）", live))
    return arrangements
