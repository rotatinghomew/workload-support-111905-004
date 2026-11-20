"""台账 CLI：python3 -m ledger [--fixtures DIR] [--as-of DAY] [--json]"""
from __future__ import annotations

import argparse
import json

from .report import build_ledger, render_text, to_jsonable


def main() -> None:
    parser = argparse.ArgumentParser(prog="ledger", description="维修复验质量台账")
    parser.add_argument("--fixtures", default="fixtures", help="源记录目录")
    parser.add_argument("--as-of", type=int, default=None, help="台账日期（10 月日号）")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    args = parser.parse_args()
    ledger = build_ledger(args.fixtures, args.as_of)
    if args.json:
        print(json.dumps(to_jsonable(ledger), ensure_ascii=False, indent=2))
    else:
        print(render_text(ledger))


if __name__ == "__main__":
    main()
