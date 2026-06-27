#!/usr/bin/env python3
"""Render a Chinese stock rating table from JSON inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


POSITIVE_FIELDS = ["evidence", "purity", "valuation", "elasticity", "catalyst", "balance_sheet"]
NEGATIVE_FIELDS = ["crowding", "dilution"]


def as_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0


def score(item: dict[str, Any]) -> float:
    return sum(as_float(item.get(field)) for field in POSITIVE_FIELDS) - sum(
        as_float(item.get(field)) for field in NEGATIVE_FIELDS
    )


def auto_rating(item: dict[str, Any], total: float) -> str:
    if item.get("rating"):
        return str(item["rating"])
    evidence = as_float(item.get("evidence"))
    valuation = as_float(item.get("valuation"))
    elasticity = as_float(item.get("elasticity"))
    catalyst = as_float(item.get("catalyst"))
    crowding = as_float(item.get("crowding"))
    if evidence < 3:
        return "证据不足剔除"
    strong_enough_to_break_out = evidence >= 4 and catalyst >= 4 and (valuation >= 3 or elasticity >= 4)
    if total >= 18 and (valuation >= 3 or elasticity >= 4) and (crowding <= 3 or strong_enough_to_break_out):
        return "核心研究"
    if total >= 14 and elasticity >= 4:
        return "弹性关注"
    return "观察跟踪"


def escape_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def load_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        raise ValueError("Expected a JSON list or an object with an 'items' list")
    return [item for item in data if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    ranked = []
    for item in load_items(args.input):
        total = score(item)
        ranked.append((total, auto_rating(item, total), item))
    ranked.sort(key=lambda row: row[0], reverse=True)

    lines = [
        "| 排名 | 评级 | 公司 | 代码 | 综合分 | Alpha 类型 | 市场误判/低估点 | 弹性触发器 | 关键证据 | 主要风险 |",
        "| ---: | --- | --- | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for idx, (total, rating, item) in enumerate(ranked, start=1):
        lines.append(
            "| {rank} | {rating} | {company} | {ticker} | {score:.1f} | {alpha_type} | {mispricing} | {trigger} | {evidence} | {risk} |".format(
                rank=idx,
                rating=escape_cell(rating),
                company=escape_cell(item.get("company", "")),
                ticker=escape_cell(item.get("ticker", "")),
                score=total,
                alpha_type=escape_cell(item.get("alpha_type", "")),
                mispricing=escape_cell(item.get("market_mispricing", item.get("valuation_elasticity_reason", ""))),
                trigger=escape_cell(item.get("alpha_trigger", item.get("catalyst_reason", ""))),
                evidence=escape_cell(item.get("key_evidence", "")),
                risk=escape_cell(item.get("risk", "")),
            )
        )

    output = "\n".join(lines) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(args.output)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
