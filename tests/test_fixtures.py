import csv
from pathlib import Path
import unittest


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HEADERS = {'activities': ['id', 'case_id', 'visit', 'worker', 'reported_team', 'day', 'begin', 'end'], 'adjudications': ['id', 'activity_id', 'recorded', 'finding', 'confirmed_team', 'new_end'], 'amendment_requests': ['id', 'pledge', 'raised', 'new_begin', 'new_end', 'source_confirmed', 'dest_confirmed'], 'backlog_windows': ['id', 'case_id', 'team', 'day', 'begin', 'end', 'duration_min', 'skills', 'kind'], 'benchmarks': ['id', 'scene', 'steps_low', 'steps_high', 'prereq'], 'cases': ['id', 'assigned_team', 'scene', 'steps', 'prereq', 'opened'], 'coverage_assignments': ['id', 'window', 'shifts', 'begin', 'end', 'state'], 'historical_roster': ['id', 'worker', 'team', 'day', 'begin', 'end', 'skills', 'coverage'], 'loans': ['id', 'worker', 'source', 'dest', 'day', 'begin', 'end'], 'outcomes': ['case_id', 'kind', 'day'], 'pledges': ['id', 'shift', 'source', 'dest', 'day', 'begin', 'end', 'status'], 'policy': ['min_cases', 'gap_min', 'open_count'], 'shifts': ['id', 'worker', 'team', 'day', 'begin', 'end', 'skill'], 'teams': ['id', 'min_staff_min']}
LINKS = [('activities', 'case_id', 'cases', 'id'), ('outcomes', 'case_id', 'cases', 'id'), ('adjudications', 'activity_id', 'activities', 'id'), ('pledges', 'shift', 'shifts', 'id'), ('backlog_windows', 'case_id', 'cases', 'id'), ('backlog_windows', 'team', 'teams', 'id'), ('amendment_requests', 'pledge', 'pledges', 'id'), ('coverage_assignments', 'window', 'backlog_windows', 'id')]


def read(name):
    with (FIXTURES / (name + ".csv")).open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return reader.fieldnames, list(reader)


class SourceRecords(unittest.TestCase):
    def test_records_match_source_columns(self):
        for name, expected in HEADERS.items():
            with self.subTest(table=name):
                header, rows = read(name)
                self.assertEqual(header, expected)
                self.assertTrue(rows)
                self.assertTrue(all(None not in row and None not in row.values() for row in rows))
                if "id" in header:
                    ids = [row["id"] for row in rows]
                    self.assertTrue(all(ids))
                    self.assertEqual(len(ids), len(set(ids)))

    def test_record_references_exist(self):
        for source, field, target, key in LINKS:
            with self.subTest(table=source, column=field):
                _, source_rows = read(source)
                _, target_rows = read(target)
                keys = {row[key] for row in target_rows}
                self.assertTrue(all(row[field] in keys for row in source_rows))
