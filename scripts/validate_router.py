#!/usr/bin/env python3
"""Validate bottleneck-scout-v3 routing examples."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PDF_TERMS = [
    "PDF",
    "正式研报",
    "深度报告",
    "可保存",
    "核心推荐",
    "核心研究",
    "投资标的分析",
    "中国投资标的分析",
    "可投标的分析",
    "深度分析",
    "付费级分析",
]

EXIT_TERMS = ["快速", "简单", "初筛", "先聊聊", "不要 PDF", "不要PDF", "只要结论"]
EVENT_TERMS = ["新闻利好谁", "这条新闻", "突发", "政策怎么看", "事件快评", "这个政策怎么看"]
REVIEW_TERMS = ["财报后验证", "财报出来", "观点复盘", "有没有被证伪", "催化日历", "接下来要跟踪"]
LIGHT_TERMS = ["帮我想想", "怎么看", "值得继续查", "先聊聊"]

QUESTION_REWRITES = [
    (r"能不能?买|能买吗|可以买", "研究评级、证据强度、价格位置、失效条件"),
    (r"什么时候买|买点", "观察区间、验证窗口、催化节点"),
    (r"卖出价|什么时候卖|卖点", "目标价框架、上修/下修条件、证伪条件"),
    (r"仓位|几成仓", "风险等级、波动风险、组合暴露提醒"),
    (r"无脑买", "明确禁止无脑买，列出必须验证的问题"),
    (r"哪个最值得看|最值得看", "评分排序、核心理由、最大反证"),
    (r"新闻利好谁|利好谁", "事件性质、核心价格变量、受益/受损链路和证据等级"),
]

FORBIDDEN_REWRITE_TERMS = [
    "建议买",
    "买入",
    "加仓",
    "减仓",
    "仓位比例",
    "止损",
    "无脑买入",
]


def classify(prompt: str) -> dict[str, str]:
    normalized = prompt.strip()
    has_exit = any(term in normalized for term in EXIT_TERMS)
    has_pdf_intent = any(term in normalized for term in PDF_TERMS)
    if has_pdf_intent and not has_exit:
        return {"depth": "deep_pdf", "mode": "深度瓶颈研报"}
    if any(term in normalized for term in EVENT_TERMS) and not has_pdf_intent:
        return {"depth": "light", "mode": "事件快评"}
    if any(term in normalized for term in REVIEW_TERMS) and not has_pdf_intent:
        return {"depth": "light", "mode": "复盘验证"}
    if any(term in normalized for term in LIGHT_TERMS) and not has_pdf_intent:
        return {"depth": "light", "mode": "事件快评" if "新闻" in normalized else "复盘验证" if "复盘" in normalized else "研究伙伴对话"}
    if re.search(r"股票|标的|排序|候选|公司|ticker|收入|订单|估值", normalized, re.I):
        return {"depth": "standard", "mode": "深度瓶颈研报" if "瓶颈" in normalized else "标准研究"}
    return {"depth": "standard", "mode": "标准研究"}


def route(prompt: str) -> str:
    return classify(prompt)["depth"]


def rewrite(prompt: str) -> str:
    matches = []
    for pattern, replacement in QUESTION_REWRITES:
        if re.search(pattern, prompt):
            matches.append(replacement)
    if matches:
        return "；".join(dict.fromkeys(matches))
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    args = parser.parse_args()

    data = json.loads(args.cases.read_text(encoding="utf-8"))
    errors: list[str] = []
    for idx, case in enumerate(data.get("cases", []), start=1):
        prompt = str(case.get("prompt", ""))
        expected = str(case.get("expected_depth", ""))
        actual = classify(prompt)
        if expected and actual["depth"] != expected:
            errors.append(f"case {idx}: expected {expected}, got {actual['depth']}: {prompt}")
        expected_mode = str(case.get("expected_mode", ""))
        if expected_mode and actual["mode"] != expected_mode:
            errors.append(f"case {idx}: expected mode {expected_mode}, got {actual['mode']}: {prompt}")
        expected_rewrite = str(case.get("expected_rewrite_contains", ""))
        actual_rewrite = rewrite(prompt)
        if expected_rewrite and expected_rewrite not in actual_rewrite:
            errors.append(f"case {idx}: rewrite missing {expected_rewrite}: {actual_rewrite or prompt}")
        if case.get("must_rewrite"):
            if not actual_rewrite:
                errors.append(f"case {idx}: expected research-language rewrite: {prompt}")
            forbidden = [term for term in FORBIDDEN_REWRITE_TERMS if term in actual_rewrite]
            if forbidden:
                errors.append(f"case {idx}: rewrite includes forbidden terms {forbidden}: {actual_rewrite}")

    if errors:
        print("VALIDATE_ROUTER_FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("VALIDATE_ROUTER_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
