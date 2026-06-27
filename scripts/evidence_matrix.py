#!/usr/bin/env python3
"""Render a scored evidence matrix from JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DIMENSIONS = [
    "scarcity",
    "scaling_time",
    "substitutability",
    "verification_strength",
    "demand_linkage",
    "policy_geopolitical",
    "public_market_purity",
]

RESEARCH_DIMENSIONS = [
    ("bottleneck_scarcity", "瓶颈稀缺度", 30),
    ("financial_transmission", "财务传导", 30),
    ("valuation_odds", "估值/赔率", 25),
    ("catalyst_window", "催化与验证", 15),
]

EVIDENCE_ALIASES = {
    "direct": "直接证据",
    "直接证据": "直接证据",
    "corroborated": "交叉印证",
    "多源佐证": "交叉印证",
    "交叉印证": "交叉印证",
    "framework inference": "框架推演",
    "framework": "框架推演",
    "框架推断": "框架推演",
    "框架推演": "框架推演",
    "lead": "待核验/线索级",
    "unverified": "待核验/线索级",
    "待核验": "待核验/线索级",
    "线索级": "待核验/线索级",
    "待核验/线索级": "待核验/线索级",
    "unsupported": "无支撑",
    "无支持": "无支撑",
    "无支撑": "无支撑",
}

SCORE_CAPS = {
    "直接证据": None,
    "交叉印证": None,
    "框架推演": 64,
    "待核验/线索级": 49,
    "无支撑": None,
}

TIERS = [
    (80, "核心研究"),
    (65, "弹性关注"),
    (50, "观察跟踪"),
    (0, "剔除/待验证"),
]


def as_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def clamp_score(value: int, maximum: int) -> int:
    return max(0, min(value, maximum))


def normalize_evidence(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "无支撑"
    return EVIDENCE_ALIASES.get(text.lower(), EVIDENCE_ALIASES.get(text, text))


def score_cap(level: str) -> int | None:
    normalized = normalize_evidence(level)
    return SCORE_CAPS.get(normalized)


def capped_score(raw_score: int, level: str) -> int | None:
    normalized = normalize_evidence(level)
    if normalized == "无支撑":
        return None
    cap = score_cap(normalized)
    return raw_score if cap is None else min(raw_score, cap)


def tier_for(score: int | None) -> str:
    if score is None:
        return "剔除/待验证"
    for threshold, tier in TIERS:
        if score >= threshold:
            return tier
    return "剔除/待验证"


def research_score(item: dict[str, Any]) -> tuple[int, str, int | None, str]:
    if any(key in item for key, _, _ in RESEARCH_DIMENSIONS):
        raw = sum(clamp_score(as_int(item.get(key)), weight) for key, _, weight in RESEARCH_DIMENSIONS)
    else:
        raw = min(sum(as_int(item.get(dim)) for dim in DIMENSIONS), 100)
    level = normalize_evidence(
        item.get("evidence_level")
        or item.get("evidence")
        or item.get("strongest_evidence")
        or item.get("最强证据")
    )
    capped = capped_score(raw, level)
    return raw, level, capped, tier_for(capped)


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

    rows = []
    for item in load_items(args.input):
        raw, level, capped, tier = research_score(item)
        rows.append((capped if capped is not None else -1, raw, level, capped, tier, item))
    rows.sort(key=lambda row: row[0], reverse=True)

    lines = [
        "| Rank | Bottleneck | Raw Score | Strongest Evidence | Capped Score | Tier | Counter-evidence | Verdict |",
        "| ---: | --- | ---: | --- | ---: | --- | --- | --- |",
    ]
    for idx, (_, raw, level, capped, tier, item) in enumerate(rows, start=1):
        lines.append(
            "| {rank} | {bottleneck} | {raw} | {level} | {capped} | {tier} | {counter} | {verdict} |".format(
                rank=idx,
                bottleneck=escape_cell(item.get("bottleneck", "")),
                raw=raw,
                level=escape_cell(level),
                capped="N/A" if capped is None else capped,
                tier=escape_cell(tier),
                counter=escape_cell(item.get("counter_evidence", "")),
                verdict=escape_cell(item.get("verdict", "")),
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
