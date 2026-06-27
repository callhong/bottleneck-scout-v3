#!/usr/bin/env python3
"""Check source and market-data freshness for a Bottleneck Scout report."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            if fmt.endswith("Z"):
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).date()
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def load_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("sources") or data.get("items") or []
    if not isinstance(data, list):
        raise ValueError("Expected a JSON list or an object with 'sources' or 'items'")
    return [record for record in data if isinstance(record, dict)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--market-max-days", type=int, default=2)
    parser.add_argument("--source-max-days", type=int, default=370)
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date()
    failures: list[str] = []

    for idx, record in enumerate(load_records(args.input), start=1):
        kind = str(record.get("kind", record.get("type", "source"))).lower()
        label = record.get("name") or record.get("source") or f"record {idx}"
        date_value = record.get("retrieved") or record.get("date") or record.get("timestamp")
        parsed = parse_date(date_value)
        if parsed is None:
            failures.append(f"{label}: missing or unparsable date")
            continue
        age = (today - parsed).days
        max_days = args.market_max_days if "market" in kind or "price" in kind else args.source_max_days
        if age < 0:
            failures.append(f"{label}: date is in the future ({parsed})")
        elif age > max_days:
            failures.append(f"{label}: stale by policy ({age} days old, max {max_days})")

    if failures:
        print("FRESHNESS_CHECK_FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("FRESHNESS_CHECK_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
