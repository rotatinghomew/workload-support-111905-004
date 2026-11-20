"""质量台账的核心计算测试：观察窗、暴露、复发、归属、安排、更正、决定。"""
from pathlib import Path
import unittest

from ledger.assessment import assess_repairs, breakdown, observation_window
from ledger.attribution import build_incidents, shared_cause_groups
from ledger.audit import (
    CLEARED,
    CORRECTED,
    FAILED_CHECK,
    INSUFFICIENT,
    NO_RESERVE,
    OFF_SIGNATURE,
    RECURRENCE,
    RESERVE_READY,
    door_decisions,
)
from ledger.corrections import correction_impacts
from ledger.history import ServiceHistory
from ledger.model import load_tables
from ledger.planning import (
    compare_arrangements,
    deactivation_set,
    door_statuses,
    evaluate_options,
    missing_whereabouts,
    suspect_parts,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AS_OF = 16


class LedgerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables(FIXTURES)
        cls.history = ServiceHistory(cls.tables.placements, AS_OF)
        cls.original = ServiceHistory(cls.tables.placements, 0)
        cls.incidents = build_incidents(cls.tables, cls.history, cls.original)
        cls.shared = shared_cause_groups(cls.incidents, cls.tables)
        cls.assessments = assess_repairs(cls.tables, cls.incidents, cls.shared)
        cls.by_repair = {a.repair_id: a for a in cls.assessments}
        cls.by_incident = {i.id: i for i in cls.incidents}
        cls.evals = evaluate_options(cls.tables, cls.incidents)
        cls.by_plan = {e.plan_id: e for e in cls.evals}
        cls.impacts = correction_impacts(cls.tables, AS_OF, cls.incidents)


class TestWindows(LedgerCase):
    def test_window_starts_day_after_close_and_last_window_days(self):
        rule = self.tables.rules[0]
        r2 = next(r for r in self.tables.repairs if r.id == "R2")
        w = observation_window(r2, rule, self.tables.repairs)
        self.assertEqual((w.start, w.end, w.truncated_by), (5, 11, None))

    def test_window_truncated_by_next_repair_same_door(self):
        rule = self.tables.rules[0]
        r1 = next(r for r in self.tables.repairs if r.id == "R1")
        w = observation_window(r1, rule, self.tables.repairs)
        self.assertEqual((w.start, w.end, w.truncated_by), (4, 8, "R5"))
        r3 = next(r for r in self.tables.repairs if r.id == "R3")
        w3 = observation_window(r3, rule, self.tables.repairs)
        self.assertEqual((w3.start, w3.end, w3.truncated_by), (5, 8, "R6"))


class TestExposure(LedgerCase):
    def test_bypass_and_out_do_not_count_as_open_days(self):
        r4 = self.by_repair["R4"]  # C1：绕行 1、关机 1、部分 1
        self.assertEqual(r4.exposure.full_open_days, 0)
        self.assertEqual(r4.exposure.bypass_days, 1)
        self.assertEqual(r4.exposure.out_days, 1)
        self.assertEqual(r4.exposure.open_days, 1)
        self.assertEqual(r4.exposure.sufficiency, "insufficient")

    def test_missing_days_are_not_observation(self):
        r5 = self.by_repair["R5"]  # A1：窗内仅 10、11 两日有记录
        self.assertEqual(r5.exposure.open_days, 2)
        self.assertEqual(r5.exposure.missing_days, 5)
        self.assertEqual(r5.exposure.sufficiency, "insufficient")

    def test_uses_bounds_straddling_threshold_make_uncertain(self):
        r6 = self.by_repair["R6"]  # B1：58–74 横跨门槛 60
        self.assertEqual((r6.exposure.uses_low, r6.exposure.uses_high), (58, 74))
        self.assertEqual(r6.exposure.sufficiency, "uncertain")

    def test_sufficient_window(self):
        r1 = self.by_repair["R1"]
        self.assertEqual(r1.exposure.open_days, 4)
        self.assertEqual((r1.exposure.uses_low, r1.exposure.uses_high), (61, 91))
        self.assertEqual(r1.exposure.sufficiency, "sufficient")


class TestRecurrence(LedgerCase):
    def test_repeat_reports_fold_into_one_incident(self):
        r1 = self.by_repair["R1"]
        self.assertEqual(r1.confirmed, ["X1"])
        self.assertEqual(r1.repeats_folded, 1)

    def test_gap_gives_supportable_range(self):
        r1 = self.by_repair["R1"]
        self.assertEqual(r1.gap_days, [7])
        self.assertEqual((r1.count_low, r1.count_high), (1, 2))
        self.assertAlmostEqual(r1.rate_low, 0.25)
        self.assertAlmostEqual(r1.rate_high, 0.5)
        self.assertIs(r1.at_risk, True)
        self.assertEqual(r1.status, "recurrence_evidence")

    def test_cleared_only_when_sufficient_and_no_evidence(self):
        self.assertEqual(self.by_repair["R3"].status, "cleared")
        self.assertEqual(self.by_repair["R7"].status, "cleared")

    def test_off_rule_signature_not_counted(self):
        r7 = self.by_repair["R7"]  # X4 为无法合闸，不在失读比较内
        self.assertNotIn("X4", r7.confirmed)
        self.assertEqual(r7.count_low, 0)

    def test_insufficient_exposure_is_not_health(self):
        self.assertEqual(self.by_repair["R4"].status, "insufficient_exposure")
        self.assertEqual(self.by_repair["R5"].status, "insufficient_exposure")

    def test_recurrence_evidence_despite_uncertain_exposure(self):
        r6 = self.by_repair["R6"]
        self.assertEqual(r6.confirmed, ["X3"])
        self.assertEqual(r6.status, "recurrence_evidence")

    def test_shared_controller_not_independent_evidence(self):
        self.assertEqual(len(self.shared), 1)
        group = self.shared[0]
        self.assertEqual(group.power, "K1")
        self.assertEqual(sorted(group.incident_ids), ["X1", "X2"])
        r1_notes = " ".join(self.by_repair["R1"].notes)
        self.assertIn("不作独立复发证据", r1_notes)


class TestAttribution(LedgerCase):
    def test_correction_excludes_part_candidate(self):
        x3 = self.by_incident["X3"]
        remaining = {(h.kind, h.target) for h in x3.candidates}
        self.assertEqual(remaining, {("part", "P4"), ("point", "B1")})
        excluded = {h.target for h, _ in x3.excluded}
        self.assertIn("P1", excluded)

    def test_open_incident_stays_undecided_not_double_counted(self):
        for inc_id in ("X1", "X2", "X3", "X5"):
            self.assertEqual(self.by_incident[inc_id].bucket(), "undecided")
        # 单候选事件才落入确认桶
        self.assertEqual(self.by_incident["X4"].bucket(), "construction")

    def test_breakdown_never_counts_one_incident_twice(self):
        for key in ("method", "team", "family"):
            for group in breakdown(self.assessments, self.incidents, key):
                total = sum(len(v) for v in group["buckets"].values())
                self.assertEqual(total, len(set(group["incidents"])))
                self.assertEqual(len(group["buckets"]["undecided"]), total)


class TestServiceHistory(LedgerCase):
    def test_fault_history_follows_part(self):
        timeline = self.history.timeline_of("P1")
        self.assertEqual(timeline[-1].place, "store")  # 更正后 P1 在库
        x1 = self.by_incident["X1"]
        self.assertIn(("part", "P1"), {(h.kind, h.target) for h in x1.candidates})

    def test_point_history_stays(self):
        # P1 已离开 A1，但 X1 的点位候选仍挂在 A1
        x1 = self.by_incident["X1"]
        self.assertIn(("point", "A1"), {(h.kind, h.target) for h in x1.candidates})

    def test_corrected_rows_kept_but_not_effective(self):
        ids = {p.id for p in self.history.effective}
        self.assertNotIn("C05", ids)
        self.assertNotIn("C06", ids)
        self.assertIn("C11", ids)
        self.assertIn("C12", ids)
        self.assertEqual(len(self.history.corrections), 2)


class TestPlanning(LedgerCase):
    def test_failed_job_leaves_door_down(self):
        statuses = door_statuses(self.tables)
        self.assertFalse(statuses["A1"].up)
        self.assertTrue(statuses["A3"].up)

    def test_executed_option_states(self):
        self.assertEqual(self.by_plan["T1"].execution, "failed")
        self.assertEqual(self.by_plan["T4"].execution, "completed")
        self.assertEqual(self.by_plan["T2"].execution, "requested")
        self.assertEqual(self.by_plan["T6"].execution, "planned")

    def test_reserve_must_be_usable(self):
        t2 = self.by_plan["T2"]  # 替代门 A1 已停用
        self.assertEqual(t2.verdict, "blocked")
        self.assertTrue(any("A1" in b for b in t2.blocks))

    def test_reserve_must_match_access_requirement(self):
        t5 = self.by_plan["T5"]  # C1 无障碍，替代 C2 普通
        self.assertEqual(t5.verdict, "blocked")
        self.assertTrue(any("无障碍" in b for b in t5.blocks))
        self.assertTrue(any("北院" in b for b in t5.blocks))

    def test_reserve_needs_same_session_receipt(self):
        t6 = self.by_plan["T6"]
        self.assertEqual(t6.verdict, "conditional")
        self.assertTrue(any("16PM" in c and "A3" in c for c in t6.conditions))
        t3 = self.by_plan["T3"]
        self.assertTrue(any("B2" in c for c in t3.conditions))

    def test_executed_job_had_valid_receipt(self):
        t1 = self.by_plan["T1"]
        self.assertTrue(any("Y1" in r for r in t1.results))

    def test_power_measurement_deactivates_shared_controller_doors(self):
        plan = next(p for p in self.tables.plans if p.id == "T6")
        self.assertEqual(deactivation_set(plan, self.tables), ["A1", "A2"])

    def test_suspect_spare_and_shared_part_not_independent(self):
        self.assertIn("P9", suspect_parts(self.tables))
        t3 = self.by_plan["T3"]
        self.assertTrue(any("P9" in c and "独立证据" in c for c in t3.conditions))
        self.assertTrue(any("待复核" in b for b in t3.blind_spots))

    def test_swap_cannot_separate_point_from_power(self):
        t1 = self.by_plan["T1"]
        self.assertTrue(any("point" in b and "power" in b for b in t1.blind_spots))

    def test_removed_part_whereabouts_unreported(self):
        missing = missing_whereabouts(self.tables, self.history)
        self.assertTrue(any("P5" in m for m in missing))

    def test_arrangement_comparison(self):
        arrangements = compare_arrangements(self.tables, self.evals)
        first = arrangements[0]
        self.assertEqual(first.option_ids, ["T3", "T6"])
        self.assertTrue(any("K1" in q for q in first.questions))
        self.assertTrue(any("B1" in r and "16AM" in r for r in first.restrictions))
        self.assertTrue(any("东院" in a and "无障碍" in a for a in first.affected))
        self.assertTrue(any("西院" in a and "普通" in a for a in first.affected))
        last = arrangements[-1]
        self.assertTrue(any("T2" in b for b in last.blocked))
        self.assertTrue(any("T5" in b for b in last.blocked))


class TestCorrections(LedgerCase):
    def test_contradicted_repairs_found_but_not_undone(self):
        text = " ".join(self.impacts.contradicted_repairs)
        self.assertIn("R6", text)
        self.assertNotIn("R5", text)
        self.assertTrue(any("不可撤销重演" in n for n in self.impacts.notes))

    def test_invalidated_comparisons_listed(self):
        text = " ".join(self.impacts.invalidated_comparisons)
        self.assertIn("P1", text)
        self.assertIn("R6", text)
        # 换入、换出两条矛盾合并为一条维修级重判
        r6_marks = [c for c in self.impacts.invalidated_comparisons if "R6" in c]
        self.assertEqual(len(r6_marks), 1)

    def test_unexecuted_plan_rechecked_against_facts(self):
        text = " ".join(self.impacts.plan_rechecks)
        self.assertIn("T3", text)
        self.assertIn("P4", text)

    def test_attribution_change_recorded(self):
        text = " ".join(self.impacts.attribution_changes)
        self.assertIn("X3", text)
        self.assertIn("P1", text)


class TestAudit(LedgerCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.decisions = door_decisions(
            cls.tables, cls.assessments, cls.incidents, cls.evals, cls.impacts
        )
        cls.by_door = {d.door: d for d in cls.decisions}

    def categories(self, door):
        return {r.category for r in self.by_door[door].reasons}

    def test_c1_shows_insufficient_exposure_and_no_reserve_separately(self):
        cats = self.categories("C1")
        self.assertIn(INSUFFICIENT, cats)
        self.assertIn(NO_RESERVE, cats)
        self.assertEqual(self.by_door["C1"].decision, "不可结论")

    def test_a1_pause_lists_failure_and_recurrence(self):
        cats = self.categories("A1")
        self.assertIn(FAILED_CHECK, cats)
        self.assertIn(RECURRENCE, cats)
        self.assertIn(INSUFFICIENT, cats)
        self.assertEqual(self.by_door["A1"].decision, "暂停使用")

    def test_b2_release_with_off_signature_case(self):
        cats = self.categories("B2")
        self.assertIn(CLEARED, cats)
        self.assertIn(OFF_SIGNATURE, cats)
        self.assertEqual(self.by_door["B2"].decision, "放行（就约定签名）")

    def test_a3_reserve_ready_but_recurrence_open(self):
        cats = self.categories("A3")
        self.assertIn(RESERVE_READY, cats)
        self.assertIn(RECURRENCE, cats)

    def test_b1_correction_visible(self):
        self.assertIn(CORRECTED, self.categories("B1"))

    def test_correction_not_misattached_by_record_id_substring(self):
        # C11/C12 记录编号含 "C1"，但更正涉及的门是 B1，不是 C1
        self.assertNotIn(CORRECTED, self.categories("C1"))

    def test_c2_no_records(self):
        self.assertEqual(self.by_door["C2"].decision, "无观测记录")


if __name__ == "__main__":
    unittest.main()
