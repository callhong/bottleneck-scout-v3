#!/usr/bin/env python3
"""Render a Chinese bottleneck-scout-v3 investment report to a polished PDF."""

from __future__ import annotations

import argparse
import glob
import html
import os
import re
import sys
import tempfile
from pathlib import Path


def _bootstrap_deps() -> None:
    """首次运行自动安装缺失的 Python 依赖，使 skill 自带渲染能力、不要求用户手动装。

    只处理 pip 可装的纯 Python 依赖；WeasyPrint 的系统库（pango）无法 pip 安装，
    缺它时会自动回退 ReportLab（纯 pip、随处可用）。设 BOTTLENECK_NO_AUTOINSTALL 可关闭。
    """
    import importlib.util
    import os
    import subprocess
    import sys

    def module_available(name: str) -> bool:
        if name in sys.modules:
            return True
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    if os.environ.get("BOTTLENECK_NO_AUTOINSTALL"):
        return
    need = [pkg for pkg, mod in (
        ("reportlab", "reportlab"), ("pypdf", "pypdf"),
        ("markdown", "markdown"), ("weasyprint", "weasyprint"),
    ) if not module_available(mod)]
    if need:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", *need],
            check=False,
        )


_bootstrap_deps()

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


FONT_FALLBACK = "STSong-Light"
FONT = FONT_FALLBACK  # register_fonts() 探测到可内嵌的现代 CJK 字体后会改写此全局
_FONTS_READY = False
_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
_ASSET_FONT_DIR = _SKILL_DIR / "assets" / "fonts"

# 优先级：只选可稳定嵌入的 TrueType/TTC 字体。
# 不再把 macOS 系统 CJK（PingFang/Hiragino/Songti/STHeiti）或 CFF/OTF
# 作为候选；它们曾在 Apple Preview / Poppler 预览链路里造成中文乱码或掉字。
_CJK_FONT_CANDIDATES = [
    # (注册名, [候选文件路径或 glob], 该文件在 .ttc 中的子字体序号)
    ("BundledCJK", [
        str(_ASSET_FONT_DIR / "cjk.ttf"),
        str(_ASSET_FONT_DIR / "cjk.ttc"),
    ], 0),
    ("ArialUnicode", [
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ], 0),
    ("MicrosoftYaHei", ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf"], 0),
    ("MicrosoftJhengHei", ["C:/Windows/Fonts/msjh.ttc", "C:/Windows/Fonts/msjh.ttf"], 0),
    ("SimSun", ["C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/simsun.ttf"], 0),
    ("SimHei", ["C:/Windows/Fonts/simhei.ttf"], 0),
    ("NotoSansCJKsc", [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ], 0),
    ("WenQuanYiZenHei", [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    ], 0),
    ("DroidSansFallback", [
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/system/fonts/DroidSansFallback.ttf",
    ], 0),
    # 兜底 glob：只收 TrueType/TTC，不收 OTF/CFF。
    ("CJKFallbackGlob", [
        "/usr/share/fonts/**/*SourceHanSans*SC*.ttf",
        "/usr/share/fonts/**/*NotoSansCJK*.ttc",
        "/usr/local/share/fonts/**/*SourceHanSans*.ttf",
    ], 0),
]

AUTHOR = "瓶颈侦察 v3"
DEFAULT_SUBTITLE = "研究分析 · 不构成投资建议"
TOC_MIN_PAGES = 8
EXECUTIVE_SECTIONS = {"结论", "一页结论", "首屏结论", "执行摘要"}
EXECUTIVE_CARD_PREFIXES = (
    "结果",
    "原因",
    "过程",
    "核心结论",
    "推荐标的",
    "核心推荐",
    "核心研究",
    "弹性关注",
    "方向",
    "期限风格",
    "理由",
    "失效条件",
    "证据等级",
    "结论",
)
ACCENT = colors.HexColor("#9F1D20")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#667085")
GRID = colors.HexColor("#D8DEE6")
HEADER_BG = colors.HexColor("#F3F5F8")
ZEBRA = colors.HexColor("#F8FAFC")
CORE_BG = colors.HexColor("#EAF4FF")
ELASTIC_BG = colors.HexColor("#ECFDF3")
NEUTRAL_BG = colors.HexColor("#F2F4F7")
RISK_BG = colors.HexColor("#FEF3F2")
WARNING_BG = colors.HexColor("#FFF7E6")
EXECUTIVE_BG = colors.HexColor("#FFF8E8")
CORE_TEXT = colors.HexColor("#124C7C")
ELASTIC_TEXT = colors.HexColor("#027A48")
RISK_TEXT = colors.HexColor("#B42318")
PENDING_TEXT = colors.HexColor("#B54708")
CJK_RE = r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]"
VISUAL_SPACE = "\u2009"
LINE_BREAK_MARKER = "\uE000"
STOCK_CODE_PATTERN = r"(?:\d{6}\.(?:SH|SZ|BJ)|\d{4}\.HK|[A-Z]{1,6}\.(?:US|AX))"
HTML_BREAK_RE = re.compile(r"<br\b[^>]*/?>", re.I)
HTML_BLOCK_CLOSE_RE = re.compile(r"</(?:p|div)>", re.I)
HTML_TAG_RE = re.compile(r"</?(?:span|font|strong|b|em|i|u|a|sup|sub|small|p|div)\b[^>]*>", re.I)


class TitleBand(Flowable):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.padding_x = 0.14 * inch
        self.padding_y = 0.09 * inch
        self.gap = 0.04 * inch
        self.height = 0.92 * inch
        self._title_para = None
        self._subtitle_para = None
        self._title_height = 0
        self._subtitle_height = 0

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        content_width = max(avail_width - self.padding_x * 2 - 0.58 * inch, 1 * inch)
        title_style = ParagraphStyle(
            name="TitleBandTitle",
            fontName=FONT,
            fontSize=15.2,
            leading=19,
            textColor=INK,
            alignment=TA_LEFT,
            wordWrap="CJK",
            splitLongWords=True,
        )
        subtitle_style = ParagraphStyle(
            name="TitleBandSubtitle",
            fontName=FONT,
            fontSize=7.6,
            leading=9.8,
            textColor=MUTED,
            alignment=TA_LEFT,
            wordWrap="CJK",
            splitLongWords=True,
        )
        self._title_para = Paragraph(inline_markdown(self.title), title_style)
        _, self._title_height = self._title_para.wrap(content_width, avail_height)
        if self.subtitle:
            self._subtitle_para = Paragraph(inline_markdown(self.subtitle), subtitle_style)
            _, self._subtitle_height = self._subtitle_para.wrap(content_width, avail_height)
        else:
            self._subtitle_para = None
            self._subtitle_height = 0
        subtitle_block = self._subtitle_height + (self.gap if self._subtitle_para else 0)
        self.height = max(0.82 * inch, self.padding_y * 2 + self._title_height + subtitle_block + 0.12 * inch)
        return avail_width, self.height

    def draw(self):
        strip_w = 0.24 * inch
        self.canv.setStrokeColor(ACCENT)
        self.canv.setLineWidth(1.2)
        self.canv.line(0, self.height - 0.02 * inch, self.width, self.height - 0.02 * inch)
        self.canv.setFillColor(ACCENT)
        self.canv.rect(0, 0, strip_w, self.height, fill=1, stroke=0)

        x = strip_w + self.padding_x
        self.canv.setFillColor(ACCENT)
        self.canv.setFont(FONT, 7.2)
        self.canv.drawString(x, self.height - 0.17 * inch, "瓶颈侦察 v3")

        y = self.height - self.padding_y - 0.22 * inch - self._title_height
        if self._title_para:
            self._title_para.drawOn(self.canv, x, y)
        if self._subtitle_para:
            y -= self.gap + self._subtitle_height
            self._subtitle_para.drawOn(self.canv, x, y)

        self.canv.setStrokeColor(GRID)
        self.canv.setLineWidth(0.5)
        self.canv.line(x, 0.03 * inch, self.width, 0.03 * inch)


class ScoutDocTemplate(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if not isinstance(flowable, Paragraph):
            return
        style_name = getattr(flowable.style, "name", "")
        if style_name not in {"ScoutH1", "ScoutH2"}:
            return
        text = flowable.getPlainText()
        normalized_text = toc_label(normalize_report_spacing(text))
        if normalized_text in {"正文目录", "图表目录", "报告摘要"}:
            return
        if style_name == "ScoutH2" and is_ticker_heading(normalized_text):
            return
        text = normalized_text
        toc_text = inline_markdown(normalized_text)
        level = 0 if style_name == "ScoutH1" else 1
        key = f"heading-{self.seq.nextf('toc')}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=False)
        self.notify("TOCEntry", (level, toc_text, self.page, key))


class DependencyDiagram(Flowable):
    def __init__(self, code: str):
        super().__init__()
        self.code = code
        self.nodes, self.edges = parse_mermaid_graph(code)
        self.width = 0
        self.height = 0
        self.positions: dict[str, tuple[float, float, float, float]] = {}

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        levels = graph_levels(self.nodes, self.edges)
        row_count = sum(max(1, (len(level) + 2) // 3) for level in levels)
        self.height = max(1.8 * inch, 0.48 * inch + row_count * 0.72 * inch + max(0, len(levels) - 1) * 0.18 * inch)
        self.positions = compute_diagram_positions(levels, avail_width, self.height)
        return avail_width, self.height

    def draw(self):
        self.canv.setFillColor(colors.HexColor("#FBFCFD"))
        self.canv.roundRect(0, 0, self.width, self.height, 3, fill=1, stroke=0)
        self.canv.setStrokeColor(colors.HexColor("#E5E7EB"))
        self.canv.rect(0, 0, self.width, self.height, fill=0, stroke=1)
        self.canv.setFillColor(ACCENT)
        self.canv.setFont(FONT, 8.2)
        self.canv.drawString(0.12 * inch, self.height - 0.22 * inch, "依赖链路")

        for source, target in self.edges:
            if source in self.positions and target in self.positions:
                sx, sy, sw, sh = self.positions[source]
                tx, ty, tw, th = self.positions[target]
                draw_arrow(self.canv, sx + sw / 2, sy, tx + tw / 2, ty + th, colors.HexColor("#98A2B3"))

        style = ParagraphStyle(
            name="DiagramNode",
            fontName=FONT,
            fontSize=6.7,
            leading=8.2,
            textColor=INK,
            alignment=TA_CENTER,
            wordWrap="CJK",
        )
        for node_id, (x, y, w, h) in self.positions.items():
            fill = colors.white
            if not any(node_id == target for _, target in self.edges):
                fill = colors.HexColor("#FFF7E6")
            elif not any(node_id == source for source, _ in self.edges):
                fill = colors.HexColor("#ECFDF3")
            self.canv.setFillColor(fill)
            self.canv.setStrokeColor(colors.HexColor("#D0D5DD"))
            self.canv.roundRect(x, y, w, h, 4, fill=1, stroke=1)
            label = self.nodes.get(node_id, node_id)
            para = Paragraph(inline_markdown(label), style)
            _, ph = para.wrap(max(w - 8, 10), h)
            para.drawOn(self.canv, x + 4, y + max((h - ph) / 2, 2))


def _resolve_paths(patterns: list[str]) -> list[str]:
    found: list[str] = []
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            found.extend(sorted(glob.glob(pat, recursive=True)))
        elif os.path.exists(pat):
            found.append(pat)
    return found


def register_fonts() -> None:
    """优先注册可内嵌的现代 CJK 字体；找不到则回退到 STSong-Light CID 字体。

    探测到的字体名写入全局 FONT，并在 stderr 打印，便于 QA 记录最终字体，
    避免不同机器字体差异导致版式漂移或缺字方块。
    """
    global FONT, _FONTS_READY
    if _FONTS_READY:
        return
    for name, patterns, idx in _CJK_FONT_CANDIDATES:
        for path in _resolve_paths(patterns):
            try:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=idx))
                FONT = name
                _FONTS_READY = True
                print(f"[render_pdf] CJK 字体: {name} <- {path}", file=sys.stderr)
                return
            except Exception:
                continue
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_FALLBACK))
    except Exception:
        pass
    FONT = FONT_FALLBACK
    _FONTS_READY = True
    print(f"[render_pdf] CJK 字体: 回退 {FONT_FALLBACK}（未找到可内嵌的现代 CJK 字体）",
          file=sys.stderr)


def toc_label(text: str) -> str:
    if " / " in text:
        right = text.split(" / ", 1)[1].strip()
        if re.search(CJK_RE, right):
            return right
    return text


def is_ticker_heading(text: str) -> bool:
    return bool(re.search(r"\([0-9]{6}\.(?:SH|SZ|BJ)\)|\([0-9]{4}\.HK\)", text))


def make_styles():
    register_fonts()
    base = getSampleStyleSheet()
    for style in base.byName.values():
        style.fontName = FONT
        style.wordWrap = "CJK"
    base.add(
        ParagraphStyle(
            name="ScoutTitle",
            parent=base["Title"],
            fontName=FONT,
            fontSize=20,
            leading=27,
            alignment=TA_LEFT,
            textColor=ACCENT,
            spaceAfter=10,
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutH1",
            parent=base["Heading1"],
            fontName=FONT,
            fontSize=12.8,
            leading=17,
            textColor=ACCENT,
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutH2",
            parent=base["Heading2"],
            fontName=FONT,
            fontSize=10.8,
            leading=15,
            textColor=INK,
            spaceBefore=9,
            spaceAfter=4,
            keepWithNext=1,
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutBody",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.9,
            leading=13.0,
            alignment=TA_LEFT,
            spaceAfter=3,
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutLead",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=10.2,
            leading=15.5,
            textColor=colors.HexColor("#101828"),
            alignment=TA_LEFT,
            spaceAfter=4,
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutBullet",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9,
            leading=13,
            leftIndent=12,
            firstLineIndent=-8,
            spaceAfter=3,
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutSmall",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=7.0,
            leading=9.1,
            wordWrap="CJK",
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutCard",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.5,
            leading=12,
            wordWrap="CJK",
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutTOCTitle",
            parent=base["Heading1"],
            fontName=FONT,
            fontSize=16,
            leading=22,
            textColor=ACCENT,
            spaceBefore=0,
            spaceAfter=10,
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutTOCSub",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.2,
            leading=11,
            textColor=MUTED,
            spaceAfter=10,
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutTOC0",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9.6,
            leading=15,
            leftIndent=0,
            firstLineIndent=0,
            textColor=INK,
            wordWrap="CJK",
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutTOC1",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.5,
            leading=12,
            leftIndent=18,
            firstLineIndent=0,
            textColor=MUTED,
            wordWrap="CJK",
        )
    )
    base.add(
        ParagraphStyle(
            name="ScoutFooter",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=7,
            leading=9,
            textColor=MUTED,
            alignment=TA_CENTER,
        )
    )
    return base


def strip_inline_html(text: str) -> str:
    """Remove raw inline HTML that Markdown allows but ReportLab prints literally.

    The WeasyPrint path can render HTML spans. ReportLab parses only its own small
    XML-like subset, so user-authored `<span style="color:red">偏多</span>` must be
    normalized before escaping or it leaks into the PDF.
    """
    if "<" not in text or ">" not in text:
        return html.unescape(text)
    text = HTML_BREAK_RE.sub(LINE_BREAK_MARKER, text)
    text = HTML_BLOCK_CLOSE_RE.sub(LINE_BREAK_MARKER, text)
    text = HTML_TAG_RE.sub("", text)
    return html.unescape(text)


def inline_markdown(text: str) -> str:
    text = strip_inline_html(text)
    text = normalize_report_spacing(text)
    escaped = html.escape(text)
    escaped = preserve_visual_spacing(escaped)
    escaped = style_latin_runs(escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`(.+?)`", style_code_span, escaped)
    escaped = style_directional_terms(escaped)
    escaped = escaped.replace(" | ", " |<br/>")
    escaped = escaped.replace(LINE_BREAK_MARKER, "<br/>")
    return escaped


def style_code_span(match: re.Match[str]) -> str:
    """中文代码片段继续用中文字体，避免 Courier 缺字退到 ZapfDingbats。"""
    content = match.group(1)
    if re.search(CJK_RE, content):
        return content
    return f"<font name='Courier'>{content}</font>"


def style_directional_terms(escaped: str) -> str:
    replacements = [
        (r"(?<![\w>])(?:看多|偏多|利多|正相关|偏正面)(?![\w<])", "#B42318"),
        (r"(?<![\w>])(?:看空|偏空|利空|负相关|偏负面)(?![\w<])", "#027A48"),
        (r"(?<![\w>])(?:中性)(?![\w<])", "#667085"),
        (r"(?<![\w>])(?:待验证|双向)(?![\w<])", "#B54708"),
    ]
    for pattern, color in replacements:
        escaped = re.sub(pattern, lambda m: f"<font color='{color}'><b>{m.group(0)}</b></font>", escaped)
    return escaped


def preserve_visual_spacing(escaped: str) -> str:
    """Keep semantic spaces visible after ReportLab parses XML-like markup."""
    cjk = CJK_RE.strip("[]")
    escaped = escaped.replace(" / ", f"{VISUAL_SPACE}/{VISUAL_SPACE}")
    escaped = re.sub(rf"([A-Za-z0-9][A-Za-z0-9./:%+\-_]*?) (?=[{cjk}])", rf"\1{VISUAL_SPACE}", escaped)
    escaped = re.sub(rf"([{cjk}]) ([A-Za-z0-9][A-Za-z0-9./:%+\-_]*)", rf"\1{VISUAL_SPACE}\2", escaped)
    escaped = re.sub(r"(20\d{2}) (中报|年报|一季报|半年报|三季报)", rf"\1{VISUAL_SPACE}\2", escaped)
    return escaped


def style_latin_runs(escaped: str) -> str:
    """Use a Latin font for numbers/tickers without disturbing CJK text."""
    chunks = re.split(r"(&[#A-Za-z0-9]+;)", escaped)
    pattern = re.compile(
        r"(?<![&;A-Za-z0-9])(?![ABH]股)([+-]?\d+(?:\.\d+)?[A-Za-z]*(?:[./:%+\-_][A-Za-z0-9]+)*|[A-Za-z][A-Za-z0-9]*(?:[./:%+\-_][A-Za-z0-9]+)*)(?![A-Za-z0-9])"
    )
    styled: list[str] = []
    for chunk in chunks:
        if chunk.startswith("&") and chunk.endswith(";"):
            styled.append(chunk)
        else:
            styled.append(pattern.sub(r"<font name='Helvetica'>\g<0></font>", chunk))
    return "".join(styled)


def normalize_report_spacing(text: str) -> str:
    parts = re.split(r"(https?://\S+)", text)
    spaced: list[str] = []
    for part in parts:
        if part.startswith(("http://", "https://")):
            spaced.append(part)
            continue
        part = re.sub(r"\s+", " ", part)
        part = re.sub(
            r"\b(20\d{2})([01]\d)([0-3]\d)([0-2]\d)([0-5]\d)([0-5]\d)\b",
            r"\1-\2-\3 \4:\5",
            part,
        )
        part = re.sub(r"（\s*([0-9]{6}\.(?:SH|SZ|BJ)|[0-9]{4}\.HK)\s*）", r"(\1)", part)
        part = re.sub(r"（\s+", "（", part)
        part = re.sub(r"\s+）", "）", part)
        part = re.sub(r"\b(PE|PB|PS|TTM|Q[1-4])\s*/\s*(PE|PB|PS|TTM|Q[1-4])", r"\1/\2", part)
        part = re.sub(r"\b(PE/PB|PE/PB/PS)\s*/\s*(PE|PB|PS)", r"\1/\2", part)

        # First add readable boundaries around mixed Latin/CJK/year tokens.
        part = re.sub(r"([A-Za-z][A-Za-z0-9./:%+\-_]*)(?=" + CJK_RE + r")", r"\1 ", part)
        part = re.sub(r"(" + CJK_RE + r")([A-Za-z][A-Za-z0-9./:%+\-_]*)", r"\1 \2", part)
        part = re.sub(r"([A-Za-z][A-Za-z0-9./:%+\-_]*)(20\d{2}(?:-\d{2}-\d{2})?)", r"\1 \2", part)
        part = re.sub(r"(" + CJK_RE + r")(20\d{2}年)", r"\1 \2", part)
        part = re.sub(r"(?<!\d)(20\d{2})(中报|年报|一季报|半年报|三季报)", r"\1 \2", part)
        part = re.sub(r"(" + CJK_RE + r")(20\d{2}\s+(?:中报|年报|一季报|半年报|三季报))", r"\1 \2", part)
        part = re.sub(r"(" + CJK_RE + r")\s*/\s*(" + CJK_RE + r")", r"\1 / \2", part)
        part = re.sub(r"(" + CJK_RE + r")\s*/\s*([A-Za-z*])", r"\1 / \2", part)
        part = re.sub(r"([A-Za-z0-9*]+)\s*/\s*(" + CJK_RE + r")", r"\1 / \2", part)
        part = space_numeric_slash_sequences(part)

        # Then recover compact finance/date forms that should not be split.
        part = re.sub(r"(\d{4})\s+年\s*(\d{1,2})\s+月\s*(\d{1,2})\s+日", r"\1年\2月\3日", part)
        part = re.sub(r"(\d{1,2})\s+月\s*(\d{1,2})\s+日", r"\1月\2日", part)
        part = re.sub(r"(\d+(?:\.\d+)?)\s+(亿元|万元|元|万美元|亿美元|万股|亿股|股|倍|页|个|次|家|颗|pct)", r"\1\2", part)
        part = re.sub(r"(\d+(?:\.\d+)?)\s+%", r"\1%", part)
        part = re.sub(r"(?<![A-Za-z0-9])([ABH])\s*股(?=" + CJK_RE + r"|$|[，。；、,.:\s“”‘’\"'（）()])", r"\1股", part)
        part = re.sub(r"(" + CJK_RE + r")\s+([ABH]股)", r"\1\2", part)
        part = re.sub(r"(20\d{2})\s+年(收入|营收|利润|亏损|净利润|毛利|毛利率|订单)", r"\1年\2", part)
        part = re.sub(r"(\d{4}-\d{2}-\d{2})\s*至\s*(\d{4}-\d{2}-\d{2})", r"\1 至 \2", part)
        part = re.sub(
            r"(?<=\d)\s+(?=亿元|万元|元|万美元|亿美元|万股|亿股|股|倍|页|个|次|家|颗|pct)",
            "",
            part,
        )
        part = re.sub(r"(?<=\d)\s+(?=%)", "", part)
        part = re.sub(r"\s{2,}", " ", part)
        spaced.append(part)
    return "".join(spaced)


def normalize_report_metadata(markdown: str) -> str:
    """Canonicalize cover metadata at render time so stale drafts cannot leak old authors."""
    lines = markdown.splitlines()
    if not lines:
        return markdown
    first_section_idx = next((idx for idx, line in enumerate(lines) if line.startswith("## ")), len(lines))
    title_idx = next((idx for idx, line in enumerate(lines[:first_section_idx]) if line.startswith("# ")), None)
    if title_idx is None:
        return markdown

    author_idx = None
    for idx in range(title_idx + 1, first_section_idx):
        if re.match(r"\s*作者\s*[:：]", lines[idx]):
            author_idx = idx
            break
    canonical = f"作者：{AUTHOR}  "
    if author_idx is None:
        lines.insert(title_idx + 1, canonical)
    else:
        lines[author_idx] = canonical
    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")


def add_cjk_ascii_spacing(text: str) -> str:
    return normalize_report_spacing(text)


def space_numeric_slash_sequences(text: str) -> str:
    token = r"[+-]?\d+(?:\.\d+)?(?:%|亿元|万元|元)?"
    sequence = re.compile(rf"(?<![\w.-])({token}(?:\s*/\s*{token})+)(?![\w.-])")

    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        parts = [part.strip() for part in raw.split("/")]
        has_finance_signal = any(re.search(r"[+-.%]|亿元|万元|元", part) for part in parts)
        if not has_finance_signal:
            return raw
        return " / ".join(parts)

    return sequence.sub(repl, text)


def normalize_title(title: str) -> str:
    return re.sub(r"^瓶颈侦察报告[:：]\s*", "", title).strip()


def is_mermaid_graph(code: str) -> bool:
    first = next((line.strip() for line in code.splitlines() if line.strip()), "")
    return first.startswith(("flowchart", "graph"))


def parse_mermaid_graph(code: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    nodes: dict[str, str] = {}
    edges: list[tuple[str, str]] = []

    def parse_node(raw_node: str) -> tuple[str | None, str | None]:
        raw_node = re.sub(r"^\|[^|]*\|\s*", "", raw_node.strip())
        raw_node = raw_node.split(":::", 1)[0].strip()
        match = re.match(r"([A-Za-z][\w]*)\s*(?:([\[\(\{])\s*(.*?)\s*([\]\)\}]))?\s*$", raw_node)
        if not match:
            return None, None
        node_id = match.group(1)
        label = match.group(3)
        if label is None:
            return node_id, node_id
        label = label.strip().strip('"').strip("'").strip()
        return node_id, label or node_id

    node_pattern = re.compile(r"([A-Za-z][\w]*)\s*(?:\[\s*(.*?)\s*\]|\(\s*(.*?)\s*\)|\{\s*(.*?)\s*\})")
    edge_pattern = re.compile(r"(.+?)\s*(?:-->|==>|\-.->)\s*(.+)")
    for raw in code.splitlines():
        line = raw.strip()
        if not line or line.startswith(("flowchart", "graph")):
            continue

        for match in node_pattern.finditer(line):
            node_id = match.group(1)
            label = next((group for group in match.groups()[1:] if group is not None), "")
            label = label.strip().strip('"').strip("'").strip()
            if label:
                nodes[node_id] = label

        match = edge_pattern.search(line)
        if not match:
            continue
        source_raw, target_raw = match.groups()
        source_id, source_label = parse_node(source_raw)
        target_id, target_label = parse_node(target_raw)
        if not source_id or not target_id:
            continue
        edges.append((source_id, target_id))
        if source_label:
            nodes.setdefault(source_id, source_label)
        if target_label:
            nodes.setdefault(target_id, target_label)
    if not nodes:
        # Keep the flowable harmless if parsing fails.
        nodes = {"A": "系统起点", "B": "关键瓶颈", "C": "可验证结果"}
        edges = [("A", "B"), ("B", "C")]
    return nodes, edges


def graph_levels(nodes: dict[str, str], edges: list[tuple[str, str]]) -> list[list[str]]:
    incoming = {node: 0 for node in nodes}
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        outgoing.setdefault(source, []).append(target)
        incoming[target] = incoming.get(target, 0) + 1
        incoming.setdefault(source, incoming.get(source, 0))
    roots = [node for node in nodes if incoming.get(node, 0) == 0] or list(nodes)[:1]
    levels: list[list[str]] = []
    assigned: set[str] = set()
    frontier = roots
    while frontier:
        level = [node for node in frontier if node not in assigned]
        if level:
            levels.append(level)
            assigned.update(level)
        next_frontier: list[str] = []
        for node in frontier:
            next_frontier.extend(outgoing.get(node, []))
        frontier = next_frontier
    remaining = [node for node in nodes if node not in assigned]
    if remaining:
        levels.append(remaining)
    return levels


def compute_diagram_positions(levels: list[list[str]], width: float, height: float) -> dict[str, tuple[float, float, float, float]]:
    positions: dict[str, tuple[float, float, float, float]] = {}
    top = height - 0.48 * inch
    row_h = 0.56 * inch
    row_gap = 0.16 * inch
    level_gap = 0.17 * inch
    y = top - row_h
    for level in levels:
        chunks = [level[idx : idx + 3] for idx in range(0, len(level), 3)]
        for chunk in chunks:
            n = len(chunk)
            box_w = min(2.12 * inch, (width - 0.32 * inch - (n - 1) * 0.12 * inch) / max(n, 1))
            total_w = n * box_w + (n - 1) * 0.12 * inch
            x = (width - total_w) / 2
            for node in chunk:
                positions[node] = (x, y, box_w, row_h)
                x += box_w + 0.12 * inch
            y -= row_h + row_gap
        y -= level_gap
    return positions


def draw_arrow(canvas, x1: float, y1: float, x2: float, y2: float, color) -> None:
    mid_y = (y1 + y2) / 2
    canvas.setStrokeColor(color)
    canvas.setLineWidth(0.65)
    canvas.line(x1, y1, x1, mid_y)
    canvas.line(x1, mid_y, x2, mid_y)
    canvas.line(x2, mid_y, x2, y2)
    canvas.setFillColor(color)
    size = 3.2
    canvas.line(x2, y2, x2 - size, y2 + size)
    canvas.line(x2, y2, x2 + size, y2 + size)


def is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def split_table_row(line: str) -> list[str]:
    return [strip_inline_html(cell).strip() for cell in line.strip().strip("|").split("|")]


def format_table_cell_text(cell: str, header_cell: str, *, is_header: bool = False) -> str:
    if is_header:
        return cell
    normalized_header = normalize_report_spacing(header_cell).replace(" ", "")
    if normalized_header == "代码":
        return format_code_table_cell(cell)
    return cell


def format_code_table_cell(cell: str) -> str:
    text = normalize_report_spacing(cell)
    if re.fullmatch(r"N\s*/\s*A", text, flags=re.IGNORECASE):
        return "N/A"
    if re.fullmatch(STOCK_CODE_PATTERN, text):
        return f"`{protect_stock_code(text)}`"
    parts = [part.strip() for part in re.split(r"\s*/\s*", text) if part.strip()]
    if not parts:
        return text
    return LINE_BREAK_MARKER.join(_format_code_cell_part(part) for part in parts)


def _format_code_cell_part(part: str) -> str:
    return re.sub(
        rf"^(.+?)\(({STOCK_CODE_PATTERN})\)$",
        lambda match: f"{match.group(1).strip()}{LINE_BREAK_MARKER}{protect_stock_code(match.group(2))}",
        part.strip(),
    )


def protect_stock_code(text: str) -> str:
    """Keep exchange suffixes together in narrow PDF table cells."""
    return "\u2060".join(text)


def flush_paragraph(buffer: list[str], story: list, style) -> None:
    if not buffer:
        return
    text = " ".join(part.strip() for part in buffer if part.strip())
    if text:
        story.append(Paragraph(inline_markdown(text), style))
        story.append(Spacer(1, 0.04 * inch))
    buffer.clear()


def flush_metadata(lines: list[str], story: list, style, total_width: float) -> None:
    if not lines:
        return
    pairs: list[tuple[str, str]] = []
    for line in lines:
        if "：" in line:
            key, value = line.split("：", 1)
            pairs.append((key.strip(), value.strip()))
    if not pairs:
        lines.clear()
        return
    row = []
    for key, value in pairs:
        row.append(Paragraph(f"<b>{inline_markdown(key)}</b><br/>{inline_markdown(value)}", style))
    while len(row) < 4:
        row.append(Paragraph("", style))
    table = Table([row[:4]], colWidths=[total_width * 0.22, total_width * 0.24, total_width * 0.18, total_width * 0.36])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFBFC")),
                ("BOX", (0, 0), (-1, -1), 0.35, GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ECEFF3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.18 * inch))
    lines.clear()


def conclusion_label(text: str) -> tuple[str, str]:
    if "：" in text:
        label, body = text.split("：", 1)
        return label.strip(), body.strip()
    if text.startswith("主线"):
        return "主线判断", text
    if text.startswith("最硬") or text.startswith("真正"):
        return "核心判断", text
    return "要点", text


def conclusion_bg(label: str):
    if label in {"结果", "原因", "过程", "核心结论"}:
        return EXECUTIVE_BG
    if "核心推荐" in label or "核心研究" in label:
        return CORE_BG
    if "弹性关注" in label:
        return ELASTIC_BG
    if "风险" in label or "反证" in label or "剔除" in label:
        return RISK_BG
    if "中性" in label:
        return NEUTRAL_BG
    return colors.HexColor("#F7FBFF")


def flush_conclusion_cards(buffer: list[str], story: list, style, total_width: float) -> None:
    if not buffer:
        return
    cells = []
    backgrounds = []
    for idx, item in enumerate(buffer):
        label, body = conclusion_label(item)
        paragraph = Paragraph(f"<b>{inline_markdown(label)}</b><br/>{inline_markdown(body)}", style)
        cells.append(paragraph)
        backgrounds.append(conclusion_bg(label))

    rows = []
    for idx in range(0, len(cells), 2):
        row = cells[idx : idx + 2]
        if len(row) == 1:
            row.append(Paragraph("", style))
        rows.append(row)

    table = Table(rows, colWidths=[total_width * 0.49, total_width * 0.49], hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("BOX", (0, 0), (-1, -1), 0.25, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 4, colors.white),
    ]
    for idx, bg in enumerate(backgrounds):
        row = idx // 2
        col = idx % 2
        commands.append(("BACKGROUND", (col, row), (col, row), bg))
        commands.append(("BOX", (col, row), (col, row), 0.35, colors.HexColor("#E4E7EC")))
    table.setStyle(TableStyle(commands))
    story.append(table)
    story.append(Spacer(1, 0.14 * inch))
    buffer.clear()


def flush_summary_points(buffer: list[str], story: list, style, total_width: float) -> None:
    if not buffer:
        return
    rows = []
    for item in buffer:
        label, body = conclusion_label(item)
        text = f"<b>{inline_markdown(label)}</b>：{inline_markdown(body)}" if body else inline_markdown(label)
        rows.append(
            [
                Paragraph("<font color='#9F1D20'>■</font>", style),
                Paragraph(text, style),
            ]
        )
    table = Table(rows, colWidths=[total_width * 0.035, total_width * 0.945], hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (1, 0), (1, -1), 0.25, colors.HexColor("#E5E7EB")),
    ]
    table.setStyle(TableStyle(commands))
    story.append(table)
    story.append(Spacer(1, 0.12 * inch))
    buffer.clear()


def flush_bullets(buffer: list[str], story: list, style, section: str = "", total_width: float | None = None) -> None:
    if section in EXECUTIVE_SECTIONS and total_width is not None:
        flush_conclusion_cards(buffer, story, style, total_width)
        return
    if section in {"报告摘要", "重点内容"} and total_width is not None:
        flush_summary_points(buffer, story, style, total_width)
        return
    if section == "投资结论" and total_width is not None:
        flush_conclusion_cards(buffer, story, style, total_width)
        return
    for idx, item in enumerate(buffer, start=1):
        story.append(Paragraph(f"{idx}. " + inline_markdown(item), style))
    if buffer:
        story.append(Spacer(1, 0.04 * inch))
    buffer.clear()


def table_widths(max_cols: int, total_width: float, header: list[str] | None = None) -> list[float]:
    normalized_header = [normalize_report_spacing(cell).replace(" ", "") for cell in (header or [])]
    if normalized_header == ["分层", "市场", "标的/环节", "代码", "方向", "风格", "综合评分", "证据等级", "核心理由", "失效条件"]:
        return [total_width * x for x in (0.075, 0.055, 0.13, 0.13, 0.055, 0.07, 0.065, 0.095, 0.17, 0.155)]
    if normalized_header == ["分级", "市场", "标的/环节", "代码", "方向", "风格", "证据等级", "核心理由", "失效条件"]:
        return [total_width * x for x in (0.08, 0.06, 0.15, 0.14, 0.06, 0.075, 0.10, 0.17, 0.165)]
    if normalized_header == [
        "公司",
        "代码",
        "directional_bias",
        "research_rating",
        "expected_price_reaction",
        "收入/客户/订单/产能证据",
        "财务传导",
        "估值/赔率",
        "invalidation_condition",
    ]:
        return [total_width * x for x in (0.085, 0.13, 0.085, 0.09, 0.10, 0.18, 0.125, 0.09, 0.115)]
    if any("方向" in cell for cell in normalized_header) and any("证据" in cell for cell in normalized_header):
        if max_cols == 6:
            return [total_width * x for x in (0.13, 0.12, 0.11, 0.14, 0.17, 0.33)]
        if max_cols == 7:
            return [total_width * x for x in (0.12, 0.10, 0.10, 0.13, 0.14, 0.16, 0.25)]
        if max_cols == 8:
            return [total_width * x for x in (0.11, 0.09, 0.09, 0.12, 0.12, 0.13, 0.15, 0.19)]
    if normalized_header == ["公司", "代码", "评级", "股价", "涨跌幅", "总市值", "成交额", "换手率", "PE/PB", "行情时间"]:
        return [total_width * x for x in (0.08, 0.10, 0.085, 0.06, 0.06, 0.085, 0.085, 0.07, 0.12, 0.255)]
    if max_cols <= 3:
        return [total_width * 0.24, total_width * 0.30, total_width * 0.46][:max_cols]
    if max_cols == 5:
        return [total_width * x for x in (0.11, 0.21, 0.16, 0.18, 0.34)]
    if max_cols == 6:
        return [total_width * x for x in (0.08, 0.16, 0.12, 0.14, 0.20, 0.30)]
    if max_cols == 7:
        return [total_width * x for x in (0.06, 0.20, 0.10, 0.11, 0.11, 0.12, 0.30)]
    if max_cols == 8:
        return [total_width * x for x in (0.10, 0.11, 0.10, 0.09, 0.09, 0.10, 0.10, 0.31)]
    if max_cols == 9:
        return [total_width * x for x in (0.10, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08, 0.34)]
    if max_cols == 10:
        return [total_width * x for x in (0.045, 0.07, 0.085, 0.095, 0.055, 0.09, 0.145, 0.135, 0.17, 0.11)]
    if max_cols == 11:
        return [total_width * x for x in (0.11, 0.08, 0.055, 0.055, 0.055, 0.055, 0.055, 0.055, 0.08, 0.08, 0.315)]
    return [total_width / max_cols] * max_cols


def flush_table(rows: list[list[str]], story: list, style, total_width: float) -> None:
    if not rows:
        return
    filtered = [row for row in rows if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)]
    if not filtered:
        rows.clear()
        return
    max_cols = max(len(row) for row in filtered)
    normalized = [row + [""] * (max_cols - len(row)) for row in filtered]
    header = normalized[0] if normalized else []
    data = [
        [
            Paragraph(
                inline_markdown(
                    format_table_cell_text(
                        cell,
                        header[col_idx] if col_idx < len(header) else "",
                        is_header=row_idx == 0,
                    )
                ),
                style,
            )
            for col_idx, cell in enumerate(row)
        ]
        for row_idx, row in enumerate(normalized)
    ]
    keep_small_card = max_cols == 3 and normalized[0] == ["模块", "指标", "数据"] and len(normalized) <= 12
    table = Table(
        data,
        colWidths=table_widths(max_cols, total_width, normalized[0]),
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=0 if keep_small_card else 1,
    )
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.25, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    rating_col = header.index("评级") if "评级" in header else header.index("分级") if "分级" in header else header.index("分层") if "分层" in header else None
    direction_col = next((idx for idx, cell in enumerate(header) if "方向" in cell), None)
    for row_idx in range(1, len(normalized)):
        if row_idx % 2 == 0:
            commands.append(("BACKGROUND", (0, row_idx), (-1, row_idx), ZEBRA))
        if direction_col is not None:
            direction = normalized[row_idx][direction_col]
            if any(token in direction for token in ("利多", "看多", "正相关")):
                commands.append(("TEXTCOLOR", (direction_col, row_idx), (direction_col, row_idx), RISK_TEXT))
            elif any(token in direction for token in ("利空", "看空", "负相关")):
                commands.append(("TEXTCOLOR", (direction_col, row_idx), (direction_col, row_idx), ELASTIC_TEXT))
            elif any(token in direction for token in ("双向", "待验证")):
                commands.append(("TEXTCOLOR", (direction_col, row_idx), (direction_col, row_idx), PENDING_TEXT))
            elif "中性" in direction:
                commands.append(("TEXTCOLOR", (direction_col, row_idx), (direction_col, row_idx), MUTED))
        if rating_col is not None:
            rating = normalized[row_idx][rating_col]
            if rating in {"核心推荐", "核心研究"}:
                commands.append(("BACKGROUND", (0, row_idx), (-1, row_idx), CORE_BG))
                commands.append(("TEXTCOLOR", (rating_col, row_idx), (rating_col, row_idx), CORE_TEXT))
            elif rating == "弹性关注":
                commands.append(("BACKGROUND", (0, row_idx), (-1, row_idx), ELASTIC_BG))
                commands.append(("TEXTCOLOR", (rating_col, row_idx), (rating_col, row_idx), ELASTIC_TEXT))
            elif rating in {"中性跟踪", "观察跟踪"}:
                commands.append(("BACKGROUND", (0, row_idx), (-1, row_idx), NEUTRAL_BG))
                commands.append(("TEXTCOLOR", (rating_col, row_idx), (rating_col, row_idx), MUTED))
            elif rating == "证据不足剔除":
                commands.append(("BACKGROUND", (0, row_idx), (-1, row_idx), RISK_BG))
                commands.append(("TEXTCOLOR", (rating_col, row_idx), (rating_col, row_idx), RISK_TEXT))
    table.setStyle(TableStyle(commands))
    story.append(table)
    story.append(Spacer(1, 0.10 * inch))
    rows.clear()


def append_code_block(code: str, story: list, styles) -> None:
    stripped = code.strip()
    if is_mermaid_graph(stripped):
        story.append(DependencyDiagram(stripped))
        story.append(Spacer(1, 0.12 * inch))
        return
    story.append(Preformatted(stripped, styles["Code"]))
    story.append(Spacer(1, 0.08 * inch))


def insert_toc_page(story: list, styles) -> None:
    toc = TableOfContents(dotsMinLevel=-1)
    toc.levelStyles = [styles["ScoutTOC0"], styles["ScoutTOC1"]]
    story.append(PageBreak())
    story.append(Paragraph("正文目录", styles["ScoutTOCTitle"]))
    story.append(Paragraph(inline_markdown("自动生成章节目录，页码以最终 PDF 为准。"), styles["ScoutTOCSub"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=ACCENT, spaceBefore=0, spaceAfter=10))
    story.append(toc)
    story.append(PageBreak())


def build_story(markdown: str, doc_width: float, include_toc: bool = False) -> list:
    st = make_styles()
    story: list = []
    paragraph: list[str] = []
    bullets: list[str] = []
    table_rows: list[list[str]] = []
    metadata_lines: list[str] = []
    in_code = False
    code_buffer: list[str] = []
    title_seen = False
    report_title = ""
    subtitle = DEFAULT_SUBTITLE
    current_section = ""
    toc_inserted = False
    skip_section = False

    for raw in markdown.splitlines():
        line = raw.rstrip()

        if line.strip().startswith("```"):
            flush_paragraph(paragraph, story, st["ScoutBody"])
            flush_bullets(bullets, story, st["ScoutCard"], current_section, doc_width)
            flush_table(table_rows, story, st["ScoutSmall"], doc_width)
            if in_code:
                append_code_block("\n".join(code_buffer), story, st)
                code_buffer.clear()
            in_code = not in_code
            continue

        if in_code:
            code_buffer.append(line)
            continue

        pre_stripped = line.strip()
        if skip_section and not pre_stripped.startswith("## "):
            continue

        if is_table_line(line):
            flush_paragraph(paragraph, story, st["ScoutBody"])
            flush_bullets(bullets, story, st["ScoutCard"], current_section, doc_width)
            table_rows.append(split_table_row(line))
            continue
        flush_table(table_rows, story, st["ScoutSmall"], doc_width)

        stripped = line.strip()
        if not stripped:
            flush_paragraph(paragraph, story, st["ScoutBody"])
            flush_bullets(bullets, story, st["ScoutCard"], current_section, doc_width)
            continue
        if stripped == "<!-- pagebreak -->":
            flush_paragraph(paragraph, story, st["ScoutBody"])
            story.append(PageBreak())
            continue
        if stripped in {"---", "***", "___"}:
            flush_paragraph(paragraph, story, st["ScoutBody"])
            story.append(HRFlowable(width="100%", thickness=0.7, color=HEADER_BG, spaceBefore=3, spaceAfter=5))
            continue
        if stripped.startswith("# "):
            flush_paragraph(paragraph, story, st["ScoutBody"])
            flush_bullets(bullets, story, st["ScoutCard"], current_section, doc_width)
            report_title = normalize_report_spacing(normalize_title(stripped[2:]))
            story.append(TitleBand(report_title, subtitle))
            story.append(Spacer(1, 0.04 * inch))
            title_seen = True
            continue
        if title_seen and (
            stripped.startswith("作者：")
            or stripped.startswith("生成时间：")
            or stripped.startswith("行情时间：")
            or stripped.startswith("报告性质：")
        ):
            metadata_lines.append(stripped)
            continue
        if stripped.startswith("## "):
            flush_paragraph(paragraph, story, st["ScoutBody"])
            flush_bullets(bullets, story, st["ScoutCard"], current_section, doc_width)
            next_section = stripped[3:]
            flush_metadata(metadata_lines, story, st["ScoutSmall"], doc_width)
            if (
                not toc_inserted
                and include_toc
                and title_seen
                and next_section not in {"结论", "一页结论", "首屏结论", "报告摘要", "重点内容", "正文目录", "目录", "图表目录", "PDF 排版要求"}
                and (current_section in EXECUTIVE_SECTIONS or current_section in {"报告摘要", "重点内容"} or current_section == "")
            ):
                insert_toc_page(story, st)
                toc_inserted = True
            current_section = next_section
            skip_section = current_section == "PDF 排版要求"
            if skip_section:
                continue
            story.append(Spacer(1, 0.03 * inch))
            story.append(Paragraph(inline_markdown(stripped[3:]), st["ScoutH1"]))
            story.append(HRFlowable(width="100%", thickness=0.7, color=HEADER_BG, spaceBefore=0, spaceAfter=5))
            continue
        if stripped.startswith("### "):
            flush_paragraph(paragraph, story, st["ScoutBody"])
            flush_bullets(bullets, story, st["ScoutCard"], current_section, doc_width)
            story.append(Paragraph(inline_markdown(stripped[4:]), st["ScoutH2"]))
            continue
        if stripped.startswith("- "):
            flush_paragraph(paragraph, story, st["ScoutBody"])
            bullets.append(stripped[2:])
            continue
        if current_section in EXECUTIVE_SECTIONS and re.match(rf"^({'|'.join(EXECUTIVE_CARD_PREFIXES)})[:：]", stripped):
            flush_paragraph(paragraph, story, st["ScoutBody"])
            bullets.append(stripped)
            continue
        if stripped.startswith("> "):
            flush_paragraph(paragraph, story, st["ScoutBody"])
            story.append(Paragraph("<b>结论：</b> " + inline_markdown(stripped[2:]), st["ScoutBody"]))
            story.append(Spacer(1, 0.06 * inch))
            continue
        paragraph.append(stripped)

    flush_paragraph(paragraph, story, st["ScoutBody"])
    flush_bullets(bullets, story, st["ScoutCard"], current_section, doc_width)
    flush_table(table_rows, story, st["ScoutSmall"], doc_width)
    flush_metadata(metadata_lines, story, st["ScoutSmall"], doc_width)
    return story


def draw_footer(canvas, doc):
    # 只画底部细页脚（页码 + 免责）；不再画每页顶部重复抬头，避免每页雷同、污染版面。
    canvas.saveState()
    canvas.setStrokeColor(HEADER_BG)
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, 0.42 * inch, doc.pagesize[0] - doc.rightMargin, 0.42 * inch)
    canvas.setFillColor(MUTED)
    canvas.setFont(FONT, 7)
    canvas.drawCentredString(
        doc.pagesize[0] / 2,
        0.25 * inch,
        f"瓶颈侦察 v3 研究报告 · 第 {doc.page} 页 · 不构成投资建议",
    )
    canvas.restoreState()


def render_pdf(markdown: str, output: Path, title: str, include_toc: bool) -> int:
    doc = ScoutDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=0.46 * inch,
        leftMargin=0.46 * inch,
        topMargin=0.58 * inch,
        bottomMargin=0.52 * inch,
        title=title,
        author=AUTHOR,
        subject="Supply-chain bottleneck research",
    )
    doc.multiBuild(build_story(markdown, doc.width, include_toc=include_toc), onFirstPage=draw_footer, onLaterPages=draw_footer)
    return int(getattr(doc, "page", 0) or 0)


def _degrade_blocks_to_tables(text: str) -> str:
    """ReportLab 兜底时，把 WeasyPrint 专用的 ```chain / ```bom 图块降级成普通表格，
    避免在没有 WeasyPrint 的环境里把图块渲成裸代码。"""
    def chain_repl(match: re.Match[str]) -> str:
        out = ["| 层级 | 节点 |", "| --- | --- |"]
        for line in match.group(1).strip().splitlines():
            line = line.strip()
            sep = "：" if "：" in line else (":" if ":" in line else "")
            if not sep:
                continue
            label, rest = line.split(sep, 1)
            items = " → ".join(x.strip() for x in re.split(r"[|｜]", rest) if x.strip())
            out.append(f"| {label.strip()} | {items} |")
        return "\n\n" + "\n".join(out) + "\n\n"

    def bom_repl(match: re.Match[str]) -> str:
        out = ["| 部件 | 成本 | 同比 | A股映射 | 证据 |", "| --- | --- | --- | --- | --- |"]
        for line in match.group(1).strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cells = [c.strip() for c in re.split(r"[|｜]", line)]
            if len(cells) >= 2:
                cells = (cells + ["", "", "", ""])[:5]
                out.append("| " + " | ".join(cells) + " |")
        return "\n\n" + "\n".join(out) + "\n\n"

    text = re.sub(r"```chain\n(.*?)```", chain_repl, text, flags=re.S)
    text = re.sub(r"```bom\n(.*?)```", bom_repl, text, flags=re.S)
    return text


def _looks_like_missing_system_lib(exc: Exception) -> bool:
    s = f"{type(exc).__name__}: {exc}".lower()
    return any(k in s for k in ("pango", "cairo", "gobject", "libffi", "gdk",
                                "cannot load library", "oserror"))


def _weasyprint_hint(exc: Exception) -> str:
    import platform

    s = f"{type(exc).__name__}: {exc}".lower()
    system = platform.system()
    hints: list[str] = []
    if "truetype" in s or "ttc" in s or "ttf" in s or "字体" in s:
        hints.append(
            "提示：新版 PDF 需要稳定可嵌入的中文 TTF/TTC 字体；可放到 "
            "assets/fonts/cjk.ttf 或 assets/fonts/cjk.ttc。OTF/CFF 字体会被拒绝，"
            "避免部分 PDF 预览器中文掉字。"
        )
    if _looks_like_missing_system_lib(exc) or "gtk" in s:
        if system == "Windows":
            hints.append(
                "提示：Windows 上 WeasyPrint 需要 GTK3/Pango 运行库；未安装时会自动降级 "
                "ReportLab。若一定要新版层级版式，请安装 GTK3 Runtime 或改用 WSL/Linux/macOS。"
            )
        elif system == "Darwin":
            hints.append(
                "提示：macOS 可运行 `brew install pango gdk-pixbuf libffi` 后再执行 "
                "`python3 scripts/render_pdf.py --setup`。脚本会自动注入 Homebrew 动态库路径。"
            )
        else:
            hints.append(
                "提示：Linux 可安装 pango/gdk-pixbuf 系统库，例如 "
                "`sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0`。"
            )
    return "\n".join(f"[render_pdf] {hint}" for hint in hints)


def _install_system_pango() -> bool:
    """best-effort 安装 WeasyPrint 的系统库；成功发起安装返回 True。

    macOS 用 brew（用户级、无需 sudo），Linux 试 apt-get（多数需权限、可能失败）。
    设 BOTTLENECK_NO_AUTOINSTALL 可关闭。
    """
    import os
    import platform
    import shutil
    import subprocess

    if os.environ.get("BOTTLENECK_NO_AUTOINSTALL"):
        return False
    system = platform.system()
    if system == "Darwin" and shutil.which("brew"):
        print("[render_pdf] 正在用 brew 安装 WeasyPrint 系统库（pango 等，一次性）…", file=sys.stderr)
        subprocess.run(["brew", "install", "pango", "gdk-pixbuf", "libffi"], check=False)
        # 装一个覆盖完整、Preview 安全的 CJK 字体（Noto），让 WeasyPrint 不必回退系统 PingFang。
        subprocess.run(["brew", "install", "--cask", "font-noto-sans-cjk-sc"], check=False)
        return True
    if system == "Linux" and shutil.which("apt-get"):
        subprocess.run(
            ["apt-get", "install", "-y", "libpango-1.0-0", "libpangoft2-1.0-0", "libgdk-pixbuf-2.0-0"],
            check=False,
        )
        return True
    if system == "Windows":
        # Windows 没有统一包管理器可靠地放置 GTK/pango 给 WeasyPrint，自动安装不稳，
        # 直接回退到纯 pip 的 ReportLab（会用 Microsoft YaHei，照样能出可读 PDF）。
        print("[render_pdf] Windows：未自动安装 WeasyPrint 系统库（GTK/pango）。"
              "已用 ReportLab 出 PDF。想要层级版式，可装 GTK3 运行库或改用 WSL。",
              file=sys.stderr)
        return False
    return False


def _macos_brew_lib_dirs() -> list[str]:
    import os
    return [p for p in ("/opt/homebrew/lib", "/usr/local/lib") if os.path.isdir(p)]


def _ensure_macos_dyld() -> None:
    """macOS：让 dyld 能找到 brew 安装的 pango/cairo/gobject 等原生库。

    macOS 默认不搜 /opt/homebrew/lib，导致 WeasyPrint 即使装了 pango 也"找不到外部库"。
    在进程内改 DYLD 环境变量 dyld 不一定生效，所以设好后带着它**重启一次自己**（一次性）。
    """
    import os
    import platform
    import sys

    if platform.system() != "Darwin" or os.environ.get("BOTTLENECK_REEXEC"):
        return
    libs = _macos_brew_lib_dirs()
    if not libs:
        return
    cur = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if all(d in cur.split(":") for d in libs):
        return
    new_path = ":".join([p for p in cur.split(":") if p] + libs + ["/usr/lib"])
    env = dict(os.environ, DYLD_FALLBACK_LIBRARY_PATH=new_path, BOTTLENECK_REEXEC="1")
    sys.stderr.write("[render_pdf] 配置 macOS 动态库路径并重启一次以加载 WeasyPrint 依赖…\n")
    os.execve(sys.executable, [sys.executable, *sys.argv], env)


def _setup_marker() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / ".render_setup.json"


def _probe_weasyprint() -> bool:
    """真渲染一小段，验证 WeasyPrint 及其系统库（pango 等）确实可用。"""
    try:
        import weasyprint
        weasyprint.HTML(string="<p>测试 test 123</p>").write_pdf()
        return True
    except Exception:
        return False


def _write_marker(weasy_ok: bool) -> None:
    import json
    try:
        marker = _setup_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"weasyprint_ok": bool(weasy_ok)}), encoding="utf-8")
    except Exception:
        pass


def _weasy_known_unavailable() -> bool:
    import json
    try:
        return json.loads(_setup_marker().read_text(encoding="utf-8")).get("weasyprint_ok") is False
    except Exception:
        return False


def _first_run_setup(force: bool = False) -> None:
    """首次使用跑一遍安装：pip 依赖 + 尝试系统库，再真探测 WeasyPrint 是否可用。
    结果写入标记文件，之后不再重复尝试；确实装不上就记下来，以后直接降级。"""
    import os
    if not force and (_setup_marker().exists() or os.environ.get("BOTTLENECK_NO_AUTOINSTALL")):
        return
    print("[render_pdf] 首次使用，正在安装渲染依赖（一次性，可能需要几分钟）…", file=sys.stderr)
    _bootstrap_deps()
    _ensure_macos_dyld()  # brew 库已存在时，带 DYLD 重启再探测
    weasy_ok = _probe_weasyprint()
    if not weasy_ok and _install_system_pango():
        _ensure_macos_dyld()  # 刚装完 pango：带 DYLD 重启，新进程才能加载它
        weasy_ok = _probe_weasyprint()
    _write_marker(weasy_ok)
    print("[render_pdf] 安装完成：WeasyPrint "
          + ("可用，输出层级版式" if weasy_ok else "不可用，降级 ReportLab（仍可出 PDF）"),
          file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--setup", action="store_true",
                        help="强制跑一遍首次安装（pip 依赖 + 系统库探测），可单独运行。")
    parser.add_argument("--title", default=None)
    parser.add_argument(
        "--toc-mode",
        choices=["never", "auto", "always"],
        default="never",
        help="目录模式：never 默认不生成；auto 超过阈值生成；always 强制生成。",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "weasyprint", "reportlab"],
        default="auto",
        help="渲染后端：auto 默认先用 WeasyPrint（层级版式），失败回退 ReportLab。",
    )
    args = parser.parse_args()

    # macOS：确保 dyld 能找到 brew 的 pango 等库（必要时带 DYLD 重启一次自己）。
    _ensure_macos_dyld()
    # 首次使用跑一遍安装（一次性，结果记入标记文件）；--setup 可强制重跑。
    _first_run_setup(force=args.setup)
    if args.setup and not args.input:
        return 0
    if not args.input or not args.output:
        parser.error("需要 input 和 output（或单独用 --setup 只做安装）")

    markdown = normalize_report_metadata(args.input.read_text(encoding="utf-8"))
    title = args.title or args.input.stem

    # 内部字段名/脚本名 → 中文显示（两个后端都生效）；Markdown 源文件不变，validator 仍可见英文字段。
    for _tok, _zh in (
        ("scripts/price_position.py", "价格位置工具"),
        ("price_position.py", "价格位置工具"),
        ("expected_price_reaction", "预期价格反应"),
        ("invalidation_condition", "失效条件"),
        ("directional_bias", "方向"),
        ("research_rating", "研究评级"),
        ("target_price_range", "目标价区间"),
        ("target_time_horizon", "目标时间窗口"),
        ("target_price_basis", "目标价依据"),
    ):
        markdown = markdown.replace(_tok, _zh)

    # auto/weasyprint 每次都真去试 WeasyPrint（不因旧标记永久跳过）：
    # 成功就把标记刷回可用（自愈，避免被一次性失败永久锁死降级）；失败才回退 ReportLab。
    if args.backend in ("auto", "weasyprint"):
        try:
            import render_pdf_weasy
            pages = render_pdf_weasy.render(markdown, args.output, title)
            _write_marker(True)
            print(f"[render_pdf] 后端: WeasyPrint（层级版式）· {pages} 页", file=sys.stderr)
            print(args.output)
            return 0
        except Exception as exc:  # noqa: BLE001
            if args.backend == "weasyprint":
                print(f"WeasyPrint 渲染失败: {exc}", file=sys.stderr)
                hint = _weasyprint_hint(exc)
                if hint:
                    print(hint, file=sys.stderr)
                return 1
            print(f"[render_pdf] WeasyPrint 不可用，回退 ReportLab：{exc}", file=sys.stderr)
            hint = _weasyprint_hint(exc)
            if hint:
                print(hint, file=sys.stderr)
            _write_marker(False)

    markdown = _degrade_blocks_to_tables(markdown)
    include_toc = args.toc_mode == "always"
    if args.toc_mode == "auto":
        with tempfile.TemporaryDirectory() as tmpdir:
            probe_output = Path(tmpdir) / "toc-probe.pdf"
            probe_pages = render_pdf(markdown, probe_output, title, include_toc=False)
        include_toc = probe_pages > TOC_MIN_PAGES
    render_pdf(markdown, args.output, title, include_toc=include_toc)
    print(f"[render_pdf] 后端: ReportLab · 字体 {FONT}", file=sys.stderr)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
