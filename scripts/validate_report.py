#!/usr/bin/env python3
"""Validate a bottleneck-scout-v3 Markdown/PDF report."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


BASE_SECTIONS = [
    "结论",
    "报告摘要",
    "提问背景",
    "叙事逻辑",
    "投资者答案",
    "价值传导链",
    "Chokepoint Quick Filter",
    "公司证据与财务传导",
    "红队与硬性否决",
    "附录：来源清单",
]

FORMAL_SECTIONS = [
    "评分分层与证据封顶",
    "高风险交叉验证",
    "股价位置与交易赔率",
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

EVIDENCE_TERMS = [
    "Direct",
    "Corroborated",
    "Framework Inference",
    "Unsupported",
    "直接证据",
    "交叉印证",
    "框架推演",
    "框架推断",
    "待核验",
    "线索级",
    "无支撑",
    "无支持",
]

VERIFIED_EVIDENCE_LEVELS = {"直接证据", "交叉印证", "框架推演"}
CORE_EVIDENCE_LEVELS = {"直接证据", "交叉印证"}
UNVERIFIED_EVIDENCE_LEVELS = {"待核验/线索级", "无支撑"}

INTERNAL_MARKERS = [
    "Graph Gate",
    "edge 记录",
    "edges.json",
    "source, target",
    "source、target",
    "relationship",
    "evidence_level",
    "bypass_risk",
    '"edges"',
    '"source"',
    '"target"',
]

UNVERIFIED_SOURCE_MARKERS = [
    "待核验",
    "未核验",
    "线索级",
    "仅线索",
    "待补",
    "待查",
    "Unsupported",
    "无支持",
    "无支撑",
    "无来源",
]

FORBIDDEN_TRADING_TERMS = [
    "建议买",
    "买入",
    "加仓",
    "减仓",
    "仓位",
    "止损",
    "无脑买",
    "卖出",
]

ALLOWED_TRADING_CONTEXT = [
    "不输出",
    "不构成",
    "不得",
    "禁止",
    "不是",
    "非本报告建议",
    "引用",
    "称",
    "表示",
    "KOL",
    "未验证",
    "否定",
    "合规",
    "反例",
    "用户问法",
    "禁止输出",
    "报告性质",
    "不替代",
]


def normalize_evidence(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return EVIDENCE_ALIASES.get(text.lower(), EVIDENCE_ALIASES.get(text, text))


def evidence_levels_in(text: str) -> set[str]:
    levels: set[str] = set()
    for term in EVIDENCE_TERMS:
        if term in text:
            levels.add(normalize_evidence(term))
    return {level for level in levels if level}


def section_present(text: str, section: str) -> bool:
    if section == "结论":
        return bool(re.search(r"^##\s+结论\s*$", text, flags=re.M))
    return bool(re.search(rf"^##+\s+[^\n]*{re.escape(section)}", text, flags=re.M))


def first_section(text: str) -> str:
    match = re.search(r"^##\s+(.+)$", text, flags=re.M)
    return match.group(1).strip() if match else ""


def extract_section(text: str, section: str) -> str:
    pattern = rf"^##\s+[^\n]*{re.escape(section)}[^\n]*\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, flags=re.M | re.S)
    return match.group(1) if match else ""


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def iter_tables(text: str):
    rows: list[list[str]] = []
    for raw in text.splitlines() + [""]:
        line = raw.strip()
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 2:
            rows.append(split_table_row(line))
            continue
        if len(rows) >= 2:
            header = rows[0]
            body = [row for row in rows[1:] if not is_separator_row(row)]
            yield header, body
        rows = []


def count_sources(text: str) -> int:
    ids: set[str] = set()
    for line in text.splitlines():
        cells = split_table_row(line) if line.strip().startswith("|") else []
        if len(cells) < 2 or not re.fullmatch(r"S\d{2,}", cells[0]):
            continue
        joined = "|".join(cells)
        levels = evidence_levels_in(joined)
        if not levels.intersection(VERIFIED_EVIDENCE_LEVELS):
            continue
        if any(marker in joined for marker in UNVERIFIED_SOURCE_MARKERS):
            continue
        ids.add(cells[0])
    return len(ids)


def has_quick_filter(text: str) -> bool:
    return all(term in text for term in ["Demand", "Transmission", "Bottleneck", "Elasticity"])


def has_structured_edges(text: str) -> bool:
    return any(label in text for label in ["链路证据表", "价值传导链", "供应链地图"]) and all(
        term in text for term in ["起点", "传导到", "证据等级"]
    )


def has_directional_fields(text: str) -> bool:
    fields = [
        "directional_bias",
        "research_rating",
        "expected_price_reaction",
        "invalidation_condition",
    ]
    return all(field in text for field in fields)


def has_target_price_fields(text: str) -> bool:
    field_sets = [
        ["target_price_range", "target_price_basis", "target_time_horizon"],
        ["目标价区间", "目标价依据", "目标时间窗口"],
    ]
    return any(all(field in text for field in fields) for fields in field_sets)


def has_pdf_qa(text: str) -> bool:
    lines = [line for line in text.splitlines() if "PDF" in line or "版式检查" in line]
    if not lines:
        return False
    for line in lines:
        if any(marker in line for marker in ["FAIL", "FAILED", "失败", "未通过"]):
            if not any(ok in line for ok in ["失败/不适用", "完成/失败"]):
                return False
        if any(ok in line for ok in ["PASS", "通过"]):
            return True
    return False


def raw_mermaid_visible(text: str) -> bool:
    fenced = re.findall(r"```(?:mermaid)?\n(.*?)```", text, flags=re.S)
    return any("flowchart" in block or "graph " in block for block in fenced)


def internal_markers(text: str) -> list[str]:
    return [marker for marker in INTERNAL_MARKERS if marker in text]


def parse_score(value: str) -> int | None:
    match = re.search(r"\b(\d{1,3})(?:\.\d+)?\b", value)
    if not match:
        return None
    score = int(match.group(1))
    if 0 <= score <= 100:
        return score
    return None


def find_column(header: list[str], patterns: list[str]) -> int | None:
    for idx, cell in enumerate(header):
        normalized = cell.replace(" ", "")
        if any(pattern in normalized for pattern in patterns):
            return idx
    return None


def validate_score_caps(text: str) -> list[str]:
    errors: list[str] = []
    for header, rows in iter_tables(text):
        score_idx = find_column(header, ["封顶后评分", "综合评分", "评分"])
        evidence_idx = find_column(header, ["最强证据", "证据等级", "证据"])
        tier_idx = find_column(header, ["分层", "评级"])
        if score_idx is None or evidence_idx is None:
            continue
        for row in rows:
            if len(row) <= max(score_idx, evidence_idx):
                continue
            levels = evidence_levels_in(row[evidence_idx])
            if not levels:
                levels = evidence_levels_in("|".join(row))
            score = parse_score(row[score_idx])
            row_text = "|".join(row)
            if "框架推演" in levels and score is not None and score > 64:
                errors.append(f"framework inference score cap exceeded: {score} > 64")
            if "待核验/线索级" in levels and score is not None and score > 49:
                errors.append(f"lead/unverified score cap exceeded: {score} > 49")
            if "无支撑" in levels and score is not None:
                errors.append("unsupported evidence must not receive a numeric score")
            if tier_idx is not None and len(row) > tier_idx:
                tier = row[tier_idx]
                if "框架推演" in levels and ("核心研究" in tier or "核心推荐" in tier):
                    errors.append("framework inference cannot be tiered as core research")
                if levels.intersection(UNVERIFIED_EVIDENCE_LEVELS) and not any(token in tier for token in ["剔除", "待验证"]):
                    errors.append(f"unverified/unsupported row must be downgraded: {row_text}")
    return errors


def validate_conclusion_gate(text: str) -> list[str]:
    errors: list[str] = []
    conclusion = extract_section(text, "结论")
    if not conclusion:
        return ["missing conclusion body"]
    for header, rows in iter_tables(conclusion):
        evidence_idx = find_column(header, ["证据等级", "证据"])
        tier_idx = find_column(header, ["分层", "分级", "评级"])
        if evidence_idx is None:
            continue
        for row in rows:
            if len(row) <= evidence_idx:
                continue
            levels = evidence_levels_in(row[evidence_idx])
            row_text = "|".join(row)
            if levels.intersection(UNVERIFIED_EVIDENCE_LEVELS):
                errors.append("lead/unverified or unsupported evidence cannot enter homepage conclusion")
            if tier_idx is not None and len(row) > tier_idx:
                tier = row[tier_idx]
                if ("核心研究" in tier or "核心推荐" in tier) and not levels.intersection(CORE_EVIDENCE_LEVELS):
                    errors.append(f"core homepage row lacks direct/corroborated evidence: {row_text}")
    return errors


def allowed_trading_line(line: str) -> bool:
    return any(marker in line for marker in ALLOWED_TRADING_CONTEXT)


def validate_trading_language(text: str) -> list[str]:
    errors: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or allowed_trading_line(stripped):
            continue
        matched = [term for term in FORBIDDEN_TRADING_TERMS if term in stripped]
        if matched:
            errors.append(f"forbidden trading directive near line {line_no}: {', '.join(matched)}")
    return errors


def validate_number_sources(text: str) -> list[str]:
    section = extract_section(text, "建议拆解图") or extract_section(text, "价值传导剖解图")
    if not section:
        return []
    errors: list[str] = []
    for header, rows in iter_tables(section):
        number_idx = find_column(header, ["关键数字", "数字", "成本", "毛利", "产能", "份额"])
        source_idx = find_column(header, ["来源", "来源/日期"])
        evidence_idx = find_column(header, ["证据等级", "证据"])
        if number_idx is None:
            continue
        for row in rows:
            if len(row) <= number_idx:
                continue
            number_cell = row[number_idx]
            if not re.search(r"\d", number_cell) or any(token in number_cell for token in ["N/A", "待验证"]):
                continue
            row_text = "|".join(row)
            has_source = source_idx is not None and len(row) > source_idx and re.search(r"S\d{2,}|20\d{2}", row[source_idx])
            has_date = re.search(r"20\d{2}[-/年]\d{1,2}", row_text)
            has_evidence = evidence_idx is not None and len(row) > evidence_idx and bool(evidence_levels_in(row[evidence_idx]))
            if not (has_source and has_date and has_evidence):
                errors.append(f"number lacks source/date/evidence in diagram table: {number_cell}")
    return errors


def validate_qa_sidecar(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"QA sidecar not found: {path}"
    if not re.search(r"交付QA_\d{8}\.md$", path.name):
        return False, "QA sidecar filename must be 交付QA_YYYYMMDD.md"
    text = path.read_text(encoding="utf-8")
    required = ["交付状态", "核心闸门", "QA 问题清单", "PDF 检查摘要"]
    missing = [item for item in required if item not in text]
    if missing:
        return False, "QA sidecar missing sections: " + ", ".join(missing)
    return True, "QA sidecar passed"


def validate_pdf(pdf: Path) -> tuple[bool, str]:
    if not pdf:
        return True, ""
    script = Path(__file__).with_name("validate_pdf_layout.py")
    if not pdf.exists():
        return False, f"PDF not found: {pdf}"
    result = subprocess.run(
        ["python3", str(script), str(pdf), "--json"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return False, result.stdout.strip() or result.stderr.strip()
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, result.stdout.strip()
    failures = data.get("failures") or []
    if failures:
        return False, json.dumps(failures, ensure_ascii=False)
    return True, "PDF layout validator passed"


def has_cjk_filename(path: Path) -> bool:
    return bool(re.search(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]", path.name))


def report_mode(args: argparse.Namespace) -> str:
    if args.mode:
        return args.mode
    return {"light": "light", "standard": "standard", "deep": "formal"}[args.depth]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--depth", choices=["light", "standard", "deep"], default="standard")
    parser.add_argument("--mode", choices=["event", "review", "standard", "formal"], default=None)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--qa", type=Path)
    parser.add_argument("--min-sources", type=int)
    args = parser.parse_args()

    text = args.report.read_text(encoding="utf-8")
    mode = report_mode(args)
    formal = mode == "formal"
    light = mode in {"event", "review", "light"} or args.depth == "light"
    errors: list[str] = []

    sections: list[str] = []
    if not light:
        sections.extend(BASE_SECTIONS)
    if formal:
        sections.extend(FORMAL_SECTIONS)
    for section in sections:
        if not section_present(text, section):
            errors.append(f"missing section: {section}")

    if not light:
        if first_section(text) != "结论":
            errors.append("first section must be: 结论")
        if not has_quick_filter(text):
            errors.append("missing Quick Filter terms")
        if not has_structured_edges(text):
            errors.append("missing investor-facing chain evidence table or value transmission graph")
        if not has_directional_fields(text):
            errors.append("missing directional fields: directional_bias/research_rating/expected_price_reaction/invalidation_condition")
        if not has_target_price_fields(text):
            errors.append("missing target price fields: target_price_range/target_price_basis/target_time_horizon")
        leaked = internal_markers(text)
        if leaked:
            errors.append("internal process markers leaked into report: " + ", ".join(leaked))
        if raw_mermaid_visible(text):
            errors.append("raw Mermaid code must not appear in formal report body")

    if not light and not evidence_levels_in(text):
        errors.append("missing evidence levels")

    if formal:
        errors.extend(validate_conclusion_gate(text))
        errors.extend(validate_score_caps(text))
        errors.extend(validate_number_sources(text))

    errors.extend(validate_trading_language(text))

    min_sources = args.min_sources
    if min_sources is None:
        min_sources = 0 if light else {"standard": 10, "formal": 10}.get(mode, 10)
    sources = count_sources(text)
    if sources < min_sources:
        errors.append(f"verified source count too low: {sources} < {min_sources}")

    if formal and not args.pdf and not args.qa and not has_pdf_qa(text):
        errors.append("formal deep report must include PDF QA PASS/通过 marker or --qa sidecar")

    if args.qa:
        ok, detail = validate_qa_sidecar(args.qa)
        if not ok:
            errors.append(f"QA sidecar validation failed: {detail}")

    if args.pdf:
        if formal and not has_cjk_filename(args.pdf):
            errors.append("formal PDF filename must contain Chinese characters")
        ok, detail = validate_pdf(args.pdf)
        if not ok:
            errors.append(f"PDF validation failed: {detail}")

    if errors:
        print("VALIDATE_REPORT_FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("VALIDATE_REPORT_PASSED")
    print(f"mode={mode}")
    print(f"verified_sources={sources}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
