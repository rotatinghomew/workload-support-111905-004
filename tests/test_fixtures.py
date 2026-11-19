import csv
from pathlib import Path
import unittest


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HEADERS = {'teams': ['id', 'min_staff_min'], 'shifts': ['id', 'worker', 'team', 'day', 'begin', 'end', 'skill'], 'loans': ['id', 'worker', 'source', 'dest', 'day', 'begin', 'end'], 'pledges': ['id', 'shift', 'source', 'dest', 'day', 'begin', 'end', 'status'], 'adjudications': ['id', 'activity_id', 'recorded', 'finding', 'confirmed_team', 'new_end'], 'benchmarks': ['id', 'scene', 'steps_low', 'steps_high', 'prereq'], 'policy': ['min_cases', 'gap_min', 'open_count'], 'cases': ['id', 'assigned_team', 'scene', 'steps', 'prereq', 'opened'], 'activities': ['id', 'case_id', 'visit', 'worker', 'reported_team', 'day', 'begin', 'end'], 'outcomes': ['case_id', 'kind', 'day']}
LINKS = [('activities', 'case_id', 'cases', 'id'), ('outcomes', 'case_id', 'cases', 'id'), ('adjudications', 'activity_id', 'activities', 'id'), ('pledges', 'shift', 'shifts', 'id')]


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
