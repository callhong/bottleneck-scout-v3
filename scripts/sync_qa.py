#!/usr/bin/env python3
"""渲染后把 PDF 实际元数据回填进交付 QA，并提供一致性校验，防止 QA 陈旧。

用法：
    python3 scripts/sync_qa.py <pdf> <交付QA.md>           # 回填页数/作者/后端/时间
    python3 scripts/sync_qa.py --check <pdf> <交付QA.md>   # 一致性校验，不一致退出 1

回填会更新已存在的 `| 页数 | ... |` 行，并在文末追加一行"自动校验"戳记。
校验在 QA 声明页数与 PDF 实际不一致、或 QA 未反映 PDF 作者时失败（可接入交付闸门）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

from pypdf import PdfReader

STAMP_RE = re.compile(r"\n> 自动校验（render 后回填）：.*\n?", re.S)


def pdf_facts(pdf: Path) -> dict:
    reader = PdfReader(str(pdf))
    meta = reader.metadata
    producer = (getattr(meta, "producer", None) or "")
    backend = "weasyprint" if "weasyprint" in producer.lower() else "reportlab"
    return {
        "pages": len(reader.pages),
        "author": getattr(meta, "author", None) or "",
        "backend": backend,
    }


def _set_row(text: str, name: str, value: str) -> str:
    pat = re.compile(r"(\|\s*" + re.escape(name) + r"\s*\|)[^|\n]*(\|)")
    if pat.search(text):
        return pat.sub(r"\1 " + value + r" \2", text, count=1)
    return text


def fill(pdf: Path, qa: Path) -> int:
    facts = pdf_facts(pdf)
    text = qa.read_text(encoding="utf-8")
    text = _set_row(text, "页数", str(facts["pages"]))
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    text = STAMP_RE.sub("\n", text).rstrip() + (
        f"\n\n> 自动校验（render 后回填）：页数 {facts['pages']} · 作者 {facts['author']} "
        f"· 后端 {facts['backend']} · {now}\n"
    )
    qa.write_text(text, encoding="utf-8")
    print(f"synced pages={facts['pages']} author={facts['author']} "
          f"backend={facts['backend']} time={now}")
    return 0


def check(pdf: Path, qa: Path) -> int:
    facts = pdf_facts(pdf)
    text = qa.read_text(encoding="utf-8")
    errs: list[str] = []
    m = re.search(r"\|\s*页数\s*\|\s*(\d+)", text)
    if m and int(m.group(1)) != facts["pages"]:
        errs.append(f"QA 页数 {m.group(1)} ≠ PDF 实际 {facts['pages']}")
    if facts["author"] and facts["author"] not in text:
        errs.append(f"QA 未反映 PDF 作者「{facts['author']}」")
    if errs:
        print("QA_PDF_MISMATCH")
        for e in errs:
            print(f"- {e}")
        return 1
    print("QA_PDF_CONSISTENT")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只校验一致性，不修改")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("qa", type=Path)
    args = parser.parse_args()
    if not args.pdf.exists():
        print(f"PDF 不存在: {args.pdf}", file=sys.stderr)
        return 2
    if not args.qa.exists():
        print(f"QA 不存在: {args.qa}", file=sys.stderr)
        return 2
    return check(args.pdf, args.qa) if args.check else fill(args.pdf, args.qa)


if __name__ == "__main__":
    raise SystemExit(main())
