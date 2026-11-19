import csv
import unittest
from pathlib import Path


class FixtureTests(unittest.TestCase):
    def test_work_rows_link_multiple_teams_to_cases(self):
        path = Path(__file__).parents[1] / "fixtures" / "work.csv"
        with path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        case_teams = {}
        for row in rows:
            case_teams.setdefault(row["case_id"], set()).add(row["team"])
        self.assertGreaterEqual(len(rows), 10)
        self.assertTrue(any(len(teams) > 1 for teams in case_teams.values()))
        self.assertTrue(all(row["row_id"] for row in rows))


if __name__ == "__main__":
    unittest.main()
