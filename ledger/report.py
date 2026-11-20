"""台账汇总与展示。"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .assessment import (
    STATUS_LABEL,
    RepairAssessment,
    assess_repairs,
    breakdown,
)
from .attribution import (
    BUCKET_LABEL,
    Incident,
    build_incidents,
    shared_cause_groups,
)
from .audit import DoorDecision, door_decisions
from .corrections import CorrectionImpact, correction_impacts
from .history import ServiceHistory
from .model import Tables, load_tables
from .planning import (
    Arrangement,
    OptionEval,
    compare_arrangements,
    evaluate_options,
    missing_whereabouts,
    suspect_parts,
    unaccounted_parts,
)


def _part_histories(tables: Tables, history: ServiceHistory, incidents, unaccounted):
    """部件故障史随件走：部件 -> 服役轨迹 + 相关事件 + 当前位置。"""
    rows = []
    parts = sorted({p.part for p in tables.placements})
    for part in parts:
        timeline = history.timeline_of(part)
        places = " → ".join(
            f"{p.place}（{p.from_day}–{p.until_day or '今'}）" for p in timeline
        )
        related = [
            i.id
            for i in incidents
            if any(h.kind == "part" and h.target == part for h in i.candidates)
        ]
        current = timeline[-1].place if timeline else "无记录"
        if part in unaccounted:
            current += "（回执显示已拆卸，去向未回报）"
        rows.append(
            {
                "part": part,
                "batch": history.batch_of(part),
                "timeline": places,
                "current": current,
                "incidents": related,
            }
        )
    return rows


def _point_histories(tables: Tables, incidents):
    """点位故障史留点位：不随部件迁移。"""
    rows = []
    for door_id in sorted(tables.doors):
        related = [
            i.id
            for i in incidents
            if any(h.kind == "point" and h.target == door_id for h in i.candidates)
        ]
        if related:
            rows.append({"door": door_id, "incidents": related})
    return rows


def _kept_parts(tables: Tables):
    """成套换件沿用部件：沿用件故障史随件保留，新整机其余部件不继承旧机历史。"""
    notes = []
    for r in tables.repairs:
        if r.part_kept:
            notes.append(
                f"{r.id}（{r.door} {r.method}）沿用部件 {r.part_kept}："
                f"其故障史随件保留，新整机其余部件不继承旧机历史"
            )
    return notes


def _reversal_points(
    tables: Tables,
    incidents: list[Incident],
    shared,
    evals: list[OptionEval],
    impacts: CorrectionImpact,
) -> list[str]:
    """哪几条现场辨识会反转批次、施工方式或点位的处置选择。"""
    flips: list[str] = []
    for g in shared:
        flips.append(
            f"断电测量 {g.power}：若确认为一次停用，{'、'.join(g.incident_ids)} "
            f"并为一起电源事件（不作独立复发证据），批次与点位的施工嫌疑解除；"
            f"若排除，则维持点位/部件未定——批次下架与点位返工的选择随之反转"
        )
    for part, note in suspect_parts(tables).items():
        flips.append(
            f"备件 {part} 复核（{note}）：若实为不良，以其为已知良好件的复验结论"
            f"需重述，批次假设回升；若良好，部件假设削弱，余点位/电源假设"
        )
    for change in impacts.attribution_changes:
        flips.append(f"记录更正：{change}——批次与点位的处置对象随之更正")
    plans = {p.id: p for p in tables.plans}
    for e in evals:
        plan = plans[e.plan_id]
        if e.verdict == "conditional" and plan.option in ("换读头", "交叉试用"):
            flips.append(
                f"{plan.id}（{plan.door} {plan.option}）结果将反转处置："
                f"复发则指向点位 {plan.door}（返工），未复发则指向批次（下架评估）"
            )
    reserve_doors = {p.reserve_door for p in tables.plans if p.reserve_door}
    for inc in incidents:
        if inc.door in reserve_doors and inc.candidates:
            flips.append(
                f"{inc.id} 落在替代门 {inc.door}：若归为点位 {inc.door}，"
                f"依赖该门的复验安排之替代选择需重核"
            )
    return flips


def build_ledger(fixtures_dir: str = "fixtures", as_of: int | None = None) -> dict:
    tables = load_tables(fixtures_dir)
    if as_of is None:
        as_of = max(
            [p.day for p in tables.plans]
            + [p.received_day for p in tables.placements]
        )
    history = ServiceHistory(tables.placements, as_of)
    original = ServiceHistory(tables.placements, 0)
    incidents = build_incidents(tables, history, original)
    shared = shared_cause_groups(incidents, tables)
    assessments = assess_repairs(tables, incidents, shared)
    breakdowns = {
        key: breakdown(assessments, incidents, key)
        for key in ("method", "team", "family")
    }
    evals = evaluate_options(tables, incidents)
    arrangements = compare_arrangements(tables, evals)
    impacts = correction_impacts(tables, as_of, incidents)
    decisions = door_decisions(tables, assessments, incidents, evals, impacts)
    off_rule = [i for i in incidents if tables.rule_for(i.signature) is None]
    return {
        "as_of": as_of,
        "tables": tables,
        "history": history,
        "assessments": assessments,
        "breakdowns": breakdowns,
        "incidents": incidents,
        "shared_groups": shared,
        "off_rule_incidents": off_rule,
        "part_histories": _part_histories(
            tables, history, incidents, unaccounted_parts(tables, history)
        ),
        "point_histories": _point_histories(tables, incidents),
        "kept_parts": _kept_parts(tables),
        "option_evals": evals,
        "arrangements": arrangements,
        "corrections": impacts,
        "decisions": decisions,
        "flips": _reversal_points(tables, incidents, shared, evals, impacts),
        "missing_whereabouts": missing_whereabouts(tables, history),
    }


def to_jsonable(ledger: dict) -> Any:
    def conv(o):
        if is_dataclass(o) and not isinstance(o, type):
            return {k: conv(v) for k, v in asdict(o).items()}
        if isinstance(o, dict):
            return {k: conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [conv(v) for v in o]
        return o

    return conv({k: v for k, v in ledger.items() if k not in ("tables", "history")})


def render_text(ledger: dict) -> str:
    tables: Tables = ledger["tables"]
    lines: list[str] = []
    out = lines.append
    out(f"维修复验质量台账（截至 10 月 {ledger['as_of']} 日）")
    out("")

    out("一、维修观察台账（不以关单后无报修认定修好）")
    for a in ledger["assessments"]:
        door = tables.doors[a.door]
        out(
            f"  {a.repair_id} {a.door}（{door.site}/{a.family} 族）"
            f"{a.method}·{a.team}队 关单 {tables_repairs_closed(tables, a.repair_id)} 日，"
            f"观察窗 {a.window.label()}"
        )
        out(
            f"    暴露：{a.exposure.state_counts_label()}；"
            f"有效通行 {a.exposure.uses_low}–{a.exposure.uses_high} 次"
        )
        if a.exposure.reasons:
            out(f"    暴露缺口：{'；'.join(a.exposure.reasons)}")
        rec = f"    复发：确认 {a.count_label()}"
        if a.repeats_folded:
            rec += f"（重复通报已归并 {a.repeats_folded} 条）"
        if a.gap_days:
            rec += f"；漏报区间 {a.gap_days}"
        rec += f"；复发率 {a.rate_label()}（约定线 {tables.rules[0].at_risk_rate}）"
        out(rec)
        out(f"    结论：{STATUS_LABEL[a.status]}")
        for note in a.notes:
            out(f"    注：{note}")
    out("")

    out("二、拆解（维修方式 / 施工队 / 设备族；未定归属不双计）")
    titles = {"method": "维修方式", "team": "施工队", "family": "设备族"}
    for key, groups in ledger["breakdowns"].items():
        out(f"  按{titles[key]}：")
        for g in groups:
            stat = "，".join(
                f"{STATUS_LABEL[s]} {n}" for s, n in sorted(g["statuses"].items())
            )
            out(f"    {g['key']}：{len(g['repairs'])} 项维修（{stat}）")
            for bucket, ids in g["buckets"].items():
                if ids:
                    out(f"      {BUCKET_LABEL[bucket]}：{'、'.join(ids)}")
    out("")

    out("三、通报归属与共享成因")
    for inc in ledger["incidents"]:
        cands = "、".join(h.label() for h in inc.candidates) or "无剩余候选"
        out(
            f"  {inc.id}（{inc.door} {inc.day} 日 {inc.signature}，"
            f"通报 {'、'.join(inc.report_ids)}）：未排除 {cands}"
        )
        for h, basis in inc.excluded:
            out(f"    已排除 {h.label()}：{basis}")
    for g in ledger["shared_groups"]:
        out(f"  共享成因：{g.label()}，不当作独立复发证据")
    for i in ledger["off_rule_incidents"]:
        out(f"  非约定签名：{i.id}（{i.signature}）不参与失读复发比较，另案")
    out("")

    out("四、部件服役与故障史（随件走 / 留点位 / 沿用件）")
    for row in ledger["part_histories"]:
        inc = f"；相关事件 {'、'.join(row['incidents'])}" if row["incidents"] else ""
        out(
            f"  {row['part']}（批次 {row['batch']}）：{row['timeline']}"
            f"；当前在 {row['current']}{inc}"
        )
    for row in ledger["point_histories"]:
        out(f"  点位 {row['door']}：候选事件 {'、'.join(row['incidents'])} 随点位保留")
    for note in ledger["kept_parts"]:
        out(f"  {note}")
    out("")

    out("五、复验安排评估")
    plans = {p.id: p for p in tables.plans}
    for e in ledger["option_evals"]:
        p = plans[e.plan_id]
        out(f"  {e.plan_id} {p.door} {p.slot} {p.option}（{p.worker}）：{e.verdict}")
        for r in e.results:
            out(f"    结果：{r}")
        for q in e.discriminates:
            out(f"    可区分：{q}")
        for b in e.blind_spots:
            out(f"    盲点：{b}")
        for c in e.conditions:
            out(f"    前提：{c}")
        for b in e.blocks:
            out(f"    阻塞：{b}")
    for m in ledger["missing_whereabouts"]:
        out(f"  去向未回报：{m}")
    out("")

    out("六、方案比较（消除的疑问 / 仍受限制的时段 / 受影响的使用方）")
    for arr in ledger["arrangements"]:
        out(f"  【{arr.name}】{'、'.join(arr.option_ids) or '（空）'}")
        for q in arr.questions:
            out(f"    消除疑问：{q}")
        for r in arr.restrictions:
            out(f"    受限：{r}")
        for a in arr.affected:
            out(f"    受影响：{a}")
        for b in arr.blocked:
            out(f"    {b}")
        for n in arr.notes:
            out(f"    {n}")
    out("")

    out("七、记录更正的影响")
    for f_ in ledger["corrections"].facts:
        out(f"  事实：{f_}")
    for c in ledger["corrections"].contradicted_repairs:
        out(f"  矛盾施工（不可撤销重演，仅注记）：{c}")
    for c in ledger["corrections"].attribution_changes:
        out(f"  归属：{c}")
    for c in ledger["corrections"].invalidated_comparisons:
        out(f"  已发布比较需重判：{c}")
    for c in ledger["corrections"].plan_rechecks:
        out(f"  未执行计划重核：{c}")
    for n in ledger["corrections"].notes:
        out(f"  注：{n}")
    out("")

    out("八、可反转处置选择的现场辨识")
    for f_ in ledger["flips"]:
        out(f"  - {f_}")
    out("")

    out("九、放行／暂停决定（院管员视图：原因分列，不并成一个故障率）")
    for d in ledger["decisions"]:
        out(f"  {d.door}（{d.site}「{d.access}」）：{d.decision}")
        for r in d.reasons:
            out(f"    [{r.category}] {r.detail}")
    return "\n".join(lines)


def tables_repairs_closed(tables: Tables, repair_id: str) -> int:
    return next(r.closed for r in tables.repairs if r.id == repair_id)
