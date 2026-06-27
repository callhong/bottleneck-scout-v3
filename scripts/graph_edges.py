#!/usr/bin/env python3
"""Validate value-chain edges and render a Mermaid flowchart."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EVIDENCE_ALIASES = {
    "Direct": "直接证据",
    "Corroborated": "交叉印证",
    "Framework Inference": "框架推演",
    "Unsupported": "无支撑",
    "直接证据": "直接证据",
    "交叉印证": "交叉印证",
    "框架推演": "框架推演",
    "框架推断": "框架推演",
    "待核验": "待核验/线索级",
    "线索级": "待核验/线索级",
    "待核验/线索级": "待核验/线索级",
    "无支撑": "无支撑",
    "无支持": "无支撑",
}
EVIDENCE = set(EVIDENCE_ALIASES)
NORMALIZED_EVIDENCE = set(EVIDENCE_ALIASES.values())
STRONG_EVIDENCE = {"直接证据", "交叉印证"}
CONFIDENCE = {"high", "medium", "low"}
STATUS = {"confirmed", "inferred", "hypothesis", "lead"}
BYPASS = {"low", "medium", "high"}


def node_id(label: str, mapping: dict[str, str]) -> str:
    if label not in mapping:
        mapping[label] = f"N{len(mapping) + 1}"
    return mapping[label]


def esc(label: str) -> str:
    return label.replace('"', "'").replace("\n", " ")


def normalize_evidence(value: Any) -> str:
    text = str(value or "").strip()
    return EVIDENCE_ALIASES.get(text, text)


def load_edges(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("edges", [])
    if not isinstance(data, list):
        raise ValueError("Expected a JSON list or object with edges")
    return [edge for edge in data if isinstance(edge, dict)]


def validate_edges(edges: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    required = {"source", "target", "relationship", "evidence_level", "confidence", "citation", "status", "bypass_risk"}
    for idx, edge in enumerate(edges, start=1):
        missing = required - set(edge)
        if missing:
            errors.append(f"edge {idx} missing: {', '.join(sorted(missing))}")
        evidence_level = normalize_evidence(edge.get("evidence_level"))
        if evidence_level not in NORMALIZED_EVIDENCE:
            errors.append(f"edge {idx} invalid evidence_level: {edge.get('evidence_level')}")
        if edge.get("confidence") not in CONFIDENCE:
            errors.append(f"edge {idx} invalid confidence: {edge.get('confidence')}")
        if edge.get("status") not in STATUS:
            errors.append(f"edge {idx} invalid status: {edge.get('status')}")
        if edge.get("bypass_risk") not in BYPASS:
            errors.append(f"edge {idx} invalid bypass_risk: {edge.get('bypass_risk')}")
        if evidence_level == "无支撑" and edge.get("status") == "confirmed":
            errors.append(f"edge {idx} cannot be confirmed with Unsupported evidence")
        if evidence_level == "待核验/线索级" and edge.get("status") == "confirmed":
            errors.append(f"edge {idx} cannot be confirmed with lead/unverified evidence")
        for number_idx, number in enumerate(edge.get("numbers", []) or [], start=1):
            if not isinstance(number, dict):
                errors.append(f"edge {idx} number {number_idx} must be an object")
                continue
            value = str(number.get("value", "")).strip()
            if not value or value in {"N/A", "待验证"}:
                continue
            if re.search(r"\d", value):
                missing = [key for key in ("source", "date", "evidence_level") if not number.get(key)]
                if missing:
                    errors.append(f"edge {idx} number {number_idx} missing source/date/evidence_level: {', '.join(missing)}")
                if number.get("date") and not re.search(r"20\d{2}[-/]\d{1,2}|20\d{2}年\d{1,2}月", str(number.get("date"))):
                    errors.append(f"edge {idx} number {number_idx} date is not explicit: {number.get('date')}")
                if number.get("evidence_level") and normalize_evidence(number.get("evidence_level")) not in NORMALIZED_EVIDENCE:
                    errors.append(f"edge {idx} number {number_idx} invalid evidence_level: {number.get('evidence_level')}")
    return errors


def render_mermaid(edges: list[dict[str, Any]]) -> str:
    mapping: dict[str, str] = {}
    lines = ["```mermaid", "flowchart LR"]
    for edge in edges:
        source = node_id(str(edge["source"]), mapping)
        target = node_id(str(edge["target"]), mapping)
        label = f"{edge['relationship']} / {normalize_evidence(edge['evidence_level'])} / bypass:{edge['bypass_risk']}"
        lines.append(f'  {source}["{esc(str(edge["source"]))}"] -->|"{esc(label)}"| {target}["{esc(str(edge["target"]))}"]')
    lines.append("```")
    return "\n".join(lines) + "\n"


def escape_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_table(edges: list[dict[str, Any]]) -> str:
    lines = [
        "| 起点 | 传导到 | 关系 | 证据等级 | 来源 | 绕开风险 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for edge in edges:
        lines.append(
            "| {source} | {target} | {relationship} | {evidence} | {citation} | {bypass} |".format(
                source=escape_cell(edge.get("source")),
                target=escape_cell(edge.get("target")),
                relationship=escape_cell(edge.get("relationship")),
                evidence=escape_cell(normalize_evidence(edge.get("evidence_level"))),
                citation=escape_cell(edge.get("citation")),
                bypass=escape_cell(edge.get("bypass_risk")),
            )
        )
    return "\n".join(lines) + "\n"


def diagram_gate_passed(edges: list[dict[str, Any]]) -> bool:
    has_strong_evidence = any(normalize_evidence(edge.get("evidence_level")) in STRONG_EVIDENCE for edge in edges)
    has_bottleneck_hint = any(
        re.search(r"瓶颈|卡点|产能|工艺|认证|客户|资源|标准|监管|数据优势|供应|价值传导", " ".join(str(edge.get(key, "")) for key in ("source", "target", "relationship")))
        for edge in edges
    )
    return has_strong_evidence and has_bottleneck_hint


def render_text_fallback(edges: list[dict[str, Any]]) -> str:
    if not edges:
        return "证据不足，建议省略拆解图，改用文字链路：当前没有可验证的价值传导边。\n"
    first = edges[0]
    last = edges[-1]
    return (
        "证据不足，建议省略拆解图，改用文字链路："
        f"{first.get('source', '需求/事件')} 可能传导至 {last.get('target', '公开标的映射')}，"
        "但瓶颈节点尚未达到交叉印证或直接证据，正式报告应标为待验证。\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-unsupported-core", action="store_true")
    parser.add_argument("--format", choices=["mermaid", "table"], default="mermaid")
    parser.add_argument("--require-diagram-gate", action="store_true")
    args = parser.parse_args()

    edges = load_edges(args.input)
    errors = validate_edges(edges)
    if args.fail_on_unsupported_core:
        for idx, edge in enumerate(edges, start=1):
            text = " ".join(str(edge.get(key, "")) for key in ("source", "target", "relationship"))
            evidence_level = normalize_evidence(edge.get("evidence_level"))
            if re.search(r"核心|core", text, re.I) and evidence_level in {"无支撑", "待核验/线索级"}:
                errors.append(f"edge {idx} core path uses unverified/unsupported evidence")
    if errors:
        print("GRAPH_EDGES_FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    if args.require_diagram_gate and not diagram_gate_passed(edges):
        output = render_text_fallback(edges)
    elif args.format == "table":
        output = render_table(edges)
    else:
        output = render_mermaid(edges)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(args.output)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
