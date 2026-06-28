#!/usr/bin/env python3
"""Validate bottleneck-scout-v3 PDF typography and render page previews."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

from pypdf import PdfReader

CJK = r"\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
EXPECTED_AUTHOR = "瓶颈侦察 v3"


FORBIDDEN_LITERAL = [
    "ExecutiveSummary",
    "SpaceX上市",
    "SpaceX募集",
    "SpaceX IPO事实",
    "霍莱沃2025年",
    "2026中报",
    "PE/PB偏高",
    "ST风险",
    "ST/问询",
    "T/R芯片",
    "收入/客户",
    "A 股",
    "H 股",
    "B 股",
    "2025 年收入",
    "20260605161500",
    " .  .  .  . ",
    "Graph Gate",
    "edge 记录",
    "edges.json",
    "\"edges\"",
    "\"source\"",
    "\"target\"",
    "```mermaid",
    "```json",
    "flowchart",
    "source, target",
    "source、target",
    "relationship",
    "evidence_level",
    "bypass_risk",
    "directional_bias",
    "research_rating",
    "expected_price_reaction",
    "invalidation_condition",
    "target_price_range",
    "target_time_horizon",
    "target_price_basis",
    "price_position.py",
    ".py",
]

FORBIDDEN_REGEX = {
    "latin_cjk_sticky": re.compile(rf"[A-Za-z][A-Za-z0-9.:%+\-_]*[{CJK}]"),
    "cjk_latin_sticky": re.compile(rf"[{CJK}][A-Za-z][A-Za-z0-9.:%+\-_]*"),
    "year_report_sticky": re.compile(r"20\d{2}(?:中报|年报|一季报|半年报|三季报)"),
    "numeric_slash_no_space": re.compile(r"\d(?:\.\d+)?(?:%|亿元|万元|元)?/[+-]?\d"),
    "stock_code_split": re.compile(r"\b(?:\d{6}\.(?:S\n[HZ]|B\nJ)|\d{4}\.H\nK)\b"),
    "missing_glyph_box": re.compile(r"[\u25A1\uFFFD]"),
}


# 这些只是 ReportLab 文本预处理（插细空格）的提取伪影检查；WeasyPrint 用真正的
# 排版引擎，CJK/拉丁不会视觉粘连，pypdf 提取出的"粘连"是假阳性，按后端跳过。
WEASY_SKIP_REGEX = {
    "latin_cjk_sticky", "cjk_latin_sticky", "year_report_sticky",
    "numeric_slash_no_space", "stock_code_split",
}
WEASY_SKIP_LITERAL = {"收入/客户"}


def is_allowed_exception(fragment: str) -> bool:
    return any(token in fragment for token in ("A股", "B股", "H股", "A 股", "B 股", "H 股", "ST股"))


def is_allowed_numeric_slash(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}/\d{1,2}", value))


def extract_text(pdf: Path) -> tuple[str, list[str], dict[str, object]]:
    reader = PdfReader(str(pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(page_texts)
    producer = getattr(reader.metadata, "producer", None) or ""
    meta = {
        "pages": len(reader.pages),
        "author": getattr(reader.metadata, "author", None),
        "chars": len(text),
        "producer": producer,
        "backend": "weasyprint" if "weasyprint" in producer.lower() else "reportlab",
    }
    return text, page_texts, meta


def check_text(text: str, page_texts: list[str], is_weasy: bool = False) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if "结论" not in text[:1200]:
        failures.append({"kind": "layout", "pattern": "missing_homepage_conclusion", "sample": "结论 not found near the first page opening"})
    for literal in FORBIDDEN_LITERAL:
        if literal in {"A 股", "B 股", "H 股"}:
            continue
        if is_weasy and literal in WEASY_SKIP_LITERAL:
            continue
        if literal in text:
            failures.append({"kind": "literal", "pattern": literal, "sample": literal})

    for name, pattern in FORBIDDEN_REGEX.items():
        if is_weasy and name in WEASY_SKIP_REGEX:
            continue
        for match in pattern.finditer(text):
            start = max(0, match.start() - 24)
            end = min(len(text), match.end() + 24)
            sample = text[start:end].replace("\n", " ")
            if is_allowed_exception(sample):
                continue
            if name == "numeric_slash_no_space" and ("http" in sample or is_allowed_numeric_slash(match.group(0))):
                continue
            failures.append({"kind": "regex", "pattern": name, "sample": sample})
            break

    toc_pages = [page for page in page_texts if "正文目录" in page]
    for toc_text in toc_pages:
        if re.search(r"\([0-9]{6}\.(?:SH|SZ|BJ)\)|\([0-9]{4}\.HK\)", toc_text):
            failures.append({"kind": "toc", "pattern": "stock_heading_in_toc", "sample": "TOC contains stock-code heading"})
        if " .  .  . " in toc_text:
            failures.append({"kind": "toc", "pattern": "dot_leader_artifact", "sample": "TOC contains dotted leaders"})
    for idx, page_text in enumerate(page_texts, start=1):
        meaningful = [
            line.strip()
            for line in page_text.splitlines()
            if line.strip()
            and "瓶颈侦察" not in line
            and "公开资料验证" not in line
            and "不构成投资建议" not in line
        ]
        if meaningful[:3] == ["模块", "指标", "数据"]:
            failures.append(
                {
                    "kind": "layout",
                    "pattern": "split_stock_data_card",
                    "sample": f"page {idx} starts with a stock data-card continuation",
                }
            )
        diagram_ids = [line for line in meaningful if re.fullmatch(r"[A-Z]", line)]
        if "依赖链路" in page_text and len(diagram_ids) >= 3:
            failures.append(
                {
                    "kind": "diagram",
                    "pattern": "unresolved_mermaid_node_ids",
                    "sample": f"page {idx}: isolated node ids {', '.join(diagram_ids[:6])}",
                }
            )
    return failures


def check_metadata_and_cover(meta: dict[str, object], page_texts: list[str]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    author = str(meta.get("author") or "")
    if author != EXPECTED_AUTHOR:
        failures.append({"kind": "metadata", "pattern": "unexpected_author", "sample": author})
    first_page = page_texts[0] if page_texts else ""
    if re.search(r"作者\s*[:：]\s*Lh\b", first_page):
        failures.append({"kind": "metadata", "pattern": "legacy_author_lh", "sample": "作者：Lh"})
    return failures


def check_renderer_spacing() -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    render_path = Path(__file__).with_name("render_pdf.py")
    spec = importlib.util.spec_from_file_location("bottleneck_render_pdf", render_path)
    if spec is None or spec.loader is None:
        return [{"kind": "renderer", "pattern": "import", "sample": f"cannot import {render_path}"}]
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - validation surface
        return [{"kind": "renderer", "pattern": "import", "sample": str(exc)}]

    normalize_cases = {
        "SpaceX上市与中国低轨星座重估": "SpaceX 上市与中国低轨星座重估",
        "42.9/43.7亿元/43.7亿元": "42.9 / 43.7亿元 / 43.7亿元",
        "巨潮资讯：霍莱沃2025年年度报告": "巨潮资讯：霍莱沃 2025年年度报告",
        "2026中报": "2026 中报",
        "T/R芯片": "T/R 芯片",
    }
    for raw, expected in normalize_cases.items():
        actual = module.normalize_report_spacing(raw)
        if actual != expected:
            failures.append({"kind": "renderer", "pattern": raw, "sample": actual})

    inline = module.inline_markdown("42.9/43.7亿元/43.7亿元")
    if "\u2009/\u2009" not in inline:
        failures.append({"kind": "renderer", "pattern": "slash_visual_spacing", "sample": inline})
    if "<font name='Helvetica'>43.7</font>亿元" not in inline:
        failures.append({"kind": "renderer", "pattern": "decimal_font_split", "sample": inline})
    if "<font name='Helvetica'>43</font>.7" in inline:
        failures.append({"kind": "renderer", "pattern": "decimal_font_split", "sample": inline})

    title_inline = module.inline_markdown("SpaceX上市")
    if "SpaceX</font>\u2009上市" not in title_inline:
        failures.append({"kind": "renderer", "pattern": "latin_cjk_visual_spacing", "sample": title_inline})
    return failures


def check_latin_font_runs(pdf: Path) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    try:
        import fitz
    except Exception:
        return failures

    alpha_run = re.compile(r"[A-Za-z]{2,}")
    allowed_fonts = ("Helvetica", "Courier")
    doc = fitz.open(pdf)
    for page_idx, page in enumerate(doc, start=1):
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    font = span.get("font", "")
                    if alpha_run.search(text) and not any(name in font for name in allowed_fonts):
                        failures.append(
                            {
                                "kind": "font",
                                "pattern": "latin_run_not_helvetica",
                                "sample": f"page {page_idx}: {line_text} [{font}]",
                            }
                        )
                        return failures
    return failures


def render_pages(pdf: Path, output_dir: Path | None) -> list[str]:
    if output_dir is None:
        return []
    import fitz

    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    paths: list[str] = []
    for idx, page in enumerate(doc):
        path = output_dir / f"page_{idx + 1:02d}.png"
        page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False).save(path)
        paths.append(str(path))
    return paths


def make_contact_sheet(paths: list[str], output_dir: Path | None) -> str | None:
    if not paths or output_dir is None:
        return None
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    thumbs = []
    for raw in paths:
        image = Image.open(raw).convert("RGB")
        image.thumbnail((360, 520))
        canvas = Image.new("RGB", (380, 560), "white")
        canvas.paste(image, ((380 - image.width) // 2, 20))
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 530), Path(raw).stem, fill=(0, 0, 0))
        thumbs.append(canvas)

    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 380, rows * 560), (245, 247, 250))
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((idx % cols) * 380, (idx // cols) * 560))
    path = output_dir / "contact_sheet.png"
    sheet.save(path)
    return str(path)


_UNSAFE_FONT_HINTS = ("pingfang", "hiragino", "songti", "stheiti", "stkaiti", "applesd")


def check_unsafe_fonts(pdf: Path) -> list[dict[str, str]]:
    """嵌入 macOS 系统 CJK 或 OTF/CFF 字体 → PDF 预览易乱码/掉字，判失败。"""
    failures: list[dict[str, str]] = []
    try:
        reader = PdfReader(str(pdf))
        for page in reader.pages:
            res = page.get("/Resources")
            fonts = res.get("/Font") if res else None
            if not fonts:
                continue
            for ref in fonts.values():
                try:
                    obj = ref.get_object()
                except Exception:
                    continue
                faces = [obj] + [d.get_object() for d in (obj.get("/DescendantFonts") or [])]
                for fnt in faces:
                    base = str(fnt.get("/BaseFont", "")).lower()
                    fd = fnt.get("/FontDescriptor")
                    embedded = False
                    cff_embedded = False
                    if fd is not None:
                        try:
                            fdo = fd.get_object()
                            embedded = any(k in fdo for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                            cff_embedded = "/FontFile3" in fdo
                        except Exception:
                            embedded = False
                            cff_embedded = False
                    if embedded and cff_embedded:
                        failures.append({"kind": "font", "pattern": "cff_cjk_font_embedding",
                                         "sample": base[:50]})
                        return failures
                    if embedded and any(h in base for h in _UNSAFE_FONT_HINTS):
                        failures.append({"kind": "font", "pattern": "unsafe_cjk_font_embedding",
                                         "sample": base[:50]})
                        return failures
    except Exception:
        return []
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--render-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    text, page_texts, meta = extract_text(args.pdf)
    is_weasy = meta.get("backend") == "weasyprint"
    failures = check_text(text, page_texts, is_weasy=is_weasy)
    failures.extend(check_metadata_and_cover(meta, page_texts))
    failures.extend(check_unsafe_fonts(args.pdf))
    failures.extend(check_renderer_spacing())
    if not is_weasy:
        # 这条强制拉丁用 Helvetica，是 ReportLab 约定；WeasyPrint 用 Noto/DejaVu，跳过。
        failures.extend(check_latin_font_runs(args.pdf))
    rendered = render_pages(args.pdf, args.render_dir)
    contact_sheet = make_contact_sheet(rendered, args.render_dir)
    result = {
        "pdf": str(args.pdf),
        "meta": meta,
        "failures": failures,
        "rendered": rendered,
        "contact_sheet": contact_sheet,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{args.pdf}")
        print(f"pages={meta['pages']} author={meta['author']} chars={meta['chars']} backend={meta.get('backend')}")
        if rendered:
            print(f"rendered={len(rendered)} pages -> {args.render_dir}")
        if contact_sheet:
            print(f"contact_sheet={contact_sheet}")
        if failures:
            print("FAIL")
            for item in failures:
                print(f"- {item['kind']} {item['pattern']}: {item['sample']}")
        else:
            print("PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
