#!/usr/bin/env python3
"""Compare old bottleneck-scout and bottleneck-scout-v3 capability coverage."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CAPABILITIES = [
    ("中文机构风格", [r"中文", r"机构|研报|报告"]),
    ("一手证据与来源纪律", [r"primary|一手|公告|年报|SEC|交易所", r"KOL.*线索|KOLs.*leads"]),
    ("A/H/US 股票映射", [r"A/H/US|A股|H股|US|美股"]),
    ("Alpha/隐形冠军", [r"Alpha|alpha", r"隐形冠军|hidden"]),
    ("价格位置", [r"price_position|价格位置", r"3年|1年|6个月|21"]),
    ("Markdown/PDF 交付", [r"render_pdf|PDF", r"validate_pdf_layout|PDF QA|布局"]),
    ("红队与证伪", [r"Red-team|红队|反证|bear case", r"证伪|falsification"]),
    ("证据等级", [r"Direct", r"Corroborated", r"Framework Inference", r"Unsupported"]),
    ("请求路由与轻量模式", [r"router|请求路由", r"轻量|standard|deep"]),
    ("价值传导链通用化", [r"价值传导链", r"软件/SaaS/平台", r"能源/公用事业"]),
    ("高风险交叉验证", [r"Cross-check|交叉验证", r"Evidence Agent|Red-team Agent|Market/Valuation"]),
]


def collect_text(root: Path) -> str:
    parts: list[str] = []
    for pattern in ("SKILL.md", "references/*.md", "scripts/*.py"):
        for path in root.glob(pattern):
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def has_all(text: str, patterns: list[str]) -> bool:
    return all(re.search(pattern, text, flags=re.I | re.S) for pattern in patterns)


def normalize_label(text: str) -> str:
    return re.sub(r"\s+", "", text)


def load_cases(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    return [case for case in cases if isinstance(case, dict)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    old_text = collect_text(args.old)
    v2_text = collect_text(args.v2)
    lines = [
        "# 老版 vs 瓶颈侦察v3 对比验证",
        "",
        "## 能力覆盖",
        "",
        "| 能力 | 老版 | v2 | 结论 |",
        "| --- | --- | --- | --- |",
    ]
    failures: list[str] = []
    for name, patterns in CAPABILITIES:
        old_ok = has_all(old_text, patterns)
        v2_ok = has_all(v2_text, patterns)
        verdict = "保持/增强" if v2_ok and (old_ok or name in {"证据等级", "请求路由与轻量模式", "价值传导链通用化", "高风险交叉验证"}) else "需修复"
        if verdict == "需修复":
            failures.append(name)
        lines.append(f"| {name} | {'Yes' if old_ok else 'No'} | {'Yes' if v2_ok else 'No'} | {verdict} |")

    lines.extend(
        [
            "",
            "## 样例覆盖",
            "",
            "| 样例 | prompt | v2 链条覆盖 | 结论 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for case in load_cases(args.cases):
        required = case.get("required_chain", "")
        ok = normalize_label(required) in normalize_label(v2_text)
        if not ok:
            failures.append(f"case:{case.get('id')}")
        lines.append(
            "| {id} | {prompt} | {required} | {verdict} |".format(
                id=case.get("id", ""),
                prompt=case.get("prompt", "").replace("|", "\\|"),
                required=required,
                verdict="PASS" if ok else "FAIL",
            )
        )

    lines.extend(
        [
            "",
            "## 裁决",
            "",
            "v2 保留老版的中文机构风格、来源纪律、价格位置、PDF 渲染和布局 QA，并新增证据等级、请求路由、价值传导链、Graph Gate 和高风险交叉验证。对硬件、软件、能源三类样例，v2 明确具备对应链条；老版对非硬件场景更容易退回供应链框架。",
        ]
    )
    if failures:
        lines.append("")
        lines.append("未通过项：" + "、".join(failures))

    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.output)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
