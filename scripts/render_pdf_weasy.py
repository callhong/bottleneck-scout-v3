#!/usr/bin/env python3
"""WeasyPrint 后端：层级优先的 HTML/CSS → PDF。

对应 PDF 主次优化目标：
- 删掉每页重复抬头，只留一行细页脚。
- 首页"决策 Hero"：`## 结论` 区视觉权重最高（底色块 + 大标题 + 强色表头）。
- 评级/方向用色块 badge，让答案一眼可见。
- 来源清单/数据源/交付QA/跟踪清单等降为"参考资料"小字层级。
- 只接受稳定 TrueType/TTC CJK 字体；OTF/CFF 曾导致 PDF 预览中文掉字，交给
  ReportLab 兜底，不在 WeasyPrint 默认路径冒险。

仅依赖 weasyprint 与 markdown。作为 render_pdf.py 的默认后端，失败时回退 ReportLab。
"""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

import markdown as _md

BRAND = "#9F1D20"
AUTHOR = "瓶颈侦察 v3"
CJK = "㐀-䶿一-鿿豈-﫿"
VISUAL = " "  # 细空格：中英混排的标准间隔，也让文本提取不粘连（与 ReportLab 一致）

# 评级 → 色块；先长后短，避免子串误配。
TIER_TOKENS = [
    ("核心研究", "core"), ("核心推荐", "core"), ("核心候选", "core"),
    ("弹性关注", "elastic"),
    ("观察跟踪", "watch"), ("中性跟踪", "watch"), ("观察", "watch"),
    ("证据不足剔除", "drop"), ("剔除/待验证", "drop"), ("剔除", "drop"),
    ("待验证", "drop"), ("待核验", "drop"),
]
# 方向 → 颜色（红=多 / 绿=空 / 灰=中性 / 橙=双向）。
DIR_TOKENS = [
    ("看多", "long"), ("偏多", "long"), ("利多", "long"), ("正相关", "long"),
    ("看空", "short"), ("偏空", "short"), ("利空", "short"), ("负相关", "short"),
    ("中性", "neutral"),
    ("双向", "pending"),
]

REF_SECTION_RE = re.compile(r"附录|来源清单|数据源清单|交付\s*QA|跟踪清单|催化验证日历|观点复盘")
METHOD_SECTION_RE = re.compile(r"方法与数据来源|研究方法|本报告方法|术语速查")

# 渲染时把内部字段名/脚本名映射成中文显示，避免交付件露出 snake_case 或 .py。
# Markdown 仍保留英文字段（validator 需要它们），只在 PDF 显示层替换。先长后短。
FIELD_MAP = [
    ("scripts/price_position.py", "价格位置工具"),
    ("price_position.py", "价格位置工具"),
    ("expected_price_reaction", "预期价格反应"),
    ("invalidation_condition", "失效条件"),
    ("directional_bias", "方向"),
    ("research_rating", "研究评级"),
    ("target_price_range", "目标价区间"),
    ("target_time_horizon", "目标时间窗口"),
    ("target_price_basis", "目标价依据"),
]

CSS = f"""
@page {{
  size: A4;
  margin: 16mm 15mm 14mm 15mm;
  @bottom-center {{
    content: "第 " counter(page) " 页 · 研究分析，不构成投资建议";
    font-size: 7.5pt; color: #9a9a9a;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: "BSCJK","WenQuanYi Zen Hei","Droid Sans Fallback","Microsoft YaHei",sans-serif;
  font-size: 10pt; color: #1c1c1c; line-height: 1.55;
}}
h1 {{ font-size: 18pt; color: {BRAND}; margin: 0 0 3pt; line-height: 1.2; }}
header.cover {{ border-bottom: 1.5pt solid {BRAND}; padding-bottom: 5pt; margin-bottom: 9pt; }}
header.cover p.meta {{ font-size: 7.8pt; color: #8a8a8a; margin: 0.5pt 0 0; line-height: 1.4; }}
h2 {{ font-size: 13pt; color: {BRAND}; border-left: 4pt solid {BRAND}; padding-left: 7pt;
      margin: 14pt 0 6pt; page-break-after: avoid; }}
h3 {{ font-size: 11pt; color: #333; margin: 9pt 0 3pt; page-break-after: avoid; }}
p {{ margin: 5pt 0; line-height: 1.62; }}
ul {{ margin: 5pt 0; padding-left: 16pt; }}
li {{ margin: 2.5pt 0; line-height: 1.55; }}
strong {{ color: #111; }}
section.hero {{ background: #FBF3F3; border: 1pt solid #E7C9C9; border-radius: 5pt;
               padding: 8pt 11pt 10pt; margin-bottom: 10pt; }}
section.hero h2 {{ margin-top: 2pt; font-size: 15pt; border-left: none; padding-left: 0; }}
section.ref {{ font-size: 8.5pt; color: #555; }}
section.ref h2 {{ font-size: 11pt; color: #777; border-left-color: #bbb; }}
table {{ width: 100%; table-layout: fixed; border-collapse: collapse;
         margin: 6pt 0; font-size: 8.4pt; line-height: 1.3; }}
th {{ background: #F3E7E7; color: #7a1417; font-weight: 600; text-align: left;
      padding: 2.5pt 4pt; border: 0.5pt solid #E2C7C7; }}
td {{ padding: 2.5pt 4pt; border: 0.5pt solid #E6E0E0; vertical-align: top; }}
th, td {{ overflow-wrap: anywhere; word-break: break-word; }}
tr {{ page-break-inside: avoid; }}
/* 宽表（>7 列）自动缩字号、收紧 padding，避免撑破右边界 */
table.wide {{ font-size: 7.4pt; }}
table.wide th, table.wide td {{ padding: 2pt 3pt; }}
section.hero table {{ font-size: 8.8pt; }}
section.hero table.wide {{ font-size: 7.8pt; }}
section.hero th {{ background: {BRAND}; color: #fff; border-color: {BRAND}; }}
.badge {{ display: inline-block; padding: 0.5pt 4pt; border-radius: 3pt;
          font-size: 8pt; font-weight: 700; color: #fff; white-space: normal; }}
.badge-core {{ background: {BRAND}; }}
.badge-elastic {{ background: #D98A2B; }}
.badge-watch {{ background: #7a8a99; }}
.badge-drop {{ background: #aeb4ba; }}
.dir {{ font-weight: 700; }}
.dir-long {{ color: #C0392B; }}
.dir-short {{ color: #1E8449; }}
.dir-neutral {{ color: #777; }}
.dir-pending {{ color: #D98A2B; }}
code {{ font-family: "DejaVu Sans Mono", "BSCJK", monospace; font-size: 8.2pt; }}
pre {{ background: #f4f4f4; color: #555; padding: 5pt 6pt; border-radius: 3pt;
       border-left: 2pt solid #ccc; white-space: pre-wrap;
       overflow-wrap: anywhere; word-break: break-all; font-size: 7.4pt;
       line-height: 1.35; font-family: "DejaVu Sans Mono", "BSCJK", monospace; }}
blockquote {{ margin: 5pt 0; padding: 4pt 9pt; border-left: 3pt solid {BRAND};
              background: #FBF3F3; font-weight: 600; }}
.chainwrap {{ margin: 9pt 0; text-align: center; }}
svg.chain {{ width: 100%; max-width: 470pt; height: auto; }}
table.bom td.bomcost {{ white-space: nowrap; }}
.bombar {{ display: inline-block; width: 56pt; height: 7pt; background: #eee;
           border-radius: 2pt; margin-right: 5pt; vertical-align: middle; overflow: hidden; }}
.bombar > span {{ display: block; height: 7pt; background: {BRAND}; }}
section.method {{ font-size: 8pt; color: #666; border-top: 0.5pt solid #ddd;
                  margin-top: 10pt; padding-top: 5pt; }}
section.method h2 {{ font-size: 10pt; color: #888; border-left-color: #ccc; }}
a.src {{ color: #4a5a8a; text-decoration: none; }}
"""

_TD_RE = re.compile(r"(<td[^>]*>)(.*?)(</td>)", re.S)


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _colorize_cells(html_str: str) -> str:
    """只在表格单元格内给评级/方向上色，避免污染正文。"""
    def repl(match: re.Match[str]) -> str:
        open_tag, inner, close_tag = match.groups()
        text = _plain(inner)
        # 只给"就是一个评级词"的短单元格做色块；长描述（如"观察跟踪→弹性关注*"）保持纯文本，避免 badge 溢出。
        for tok, cls in TIER_TOKENS:
            if text == tok or (text.startswith(tok) and len(text) <= len(tok) + 1):
                return f'{open_tag}<span class="badge badge-{cls}">{inner}</span>{close_tag}'
        for tok, cls in DIR_TOKENS:
            if text == tok or (text.startswith(tok) and len(text) <= len(tok) + 1):
                return f'{open_tag}<span class="dir dir-{cls}">{inner}</span>{close_tag}'
        return match.group(0)

    return _TD_RE.sub(repl, html_str)


def _split_cover(markdown_text: str) -> tuple[str, str, str]:
    """返回 (标题, 封面元信息 HTML, 去掉封面的正文 markdown)。"""
    m = re.search(r"^##\s", markdown_text, flags=re.M)
    head = markdown_text[: m.start()] if m else markdown_text
    body = markdown_text[m.start():] if m else ""
    title = ""
    meta_lines: list[str] = []
    author_seen = False
    for line in head.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# ") and not title:
            title = s[2:].strip()
        elif not s.startswith("#"):
            if re.match(r"作者\s*[:：]", s):
                s = f"作者：{AUTHOR}"
                author_seen = True
            meta_lines.append(s)
    if title and not author_seen:
        meta_lines.insert(0, f"作者：{AUTHOR}")
    cover = [f"<header class='cover'><h1>{_html.escape(title)}</h1>"]
    for ln in meta_lines:
        cover.append(f"<p class='meta'>{_html.escape(ln)}</p>")
    cover.append("</header>")
    return title, "".join(cover), body


def _wrap_sections(body_html: str) -> str:
    parts = re.split(r"(?=<h2\b)", body_html)
    out: list[str] = []
    for part in parts:
        if not part.strip():
            continue
        if not part.lstrip().startswith("<h2"):
            out.append(part)
            continue
        heading = _plain(re.match(r"<h2[^>]*>(.*?)</h2>", part, re.S).group(1)
                         if re.match(r"<h2[^>]*>(.*?)</h2>", part, re.S) else "")
        if "结论" in heading:
            cls = "hero"
        elif METHOD_SECTION_RE.search(heading):
            cls = "method"
        elif REF_SECTION_RE.search(heading):
            cls = "ref"
        else:
            cls = "sec"
        out.append(f"<section class='{cls}'>{part}</section>")
    return "".join(out)


def _render_chain_svg(spec: str) -> str:
    """把 ```chain``` 简易声明渲染成"完成态"价值传导图（SVG），不裸露代码。

    每行格式 `层级: 节点A ｜ 节点B`，从上到下用箭头串联。
    """
    bands: list[tuple[str, list[str]]] = []
    for line in spec.strip().splitlines():
        line = line.strip()
        sep = "：" if "：" in line else (":" if ":" in line else "")
        if not sep:
            continue
        label, rest = line.split(sep, 1)
        items = [x.strip() for x in re.split(r"[|｜]", rest) if x.strip()]
        if items:
            bands.append((label.strip(), items))
    if not bands:
        return ""
    W, pad, band_h, gap, lab_w = 520, 10, 50, 22, 58

    def _wrap2(s: str, maxlen: int) -> list[str]:
        s = s.strip()
        if len(s) <= maxlen:
            return [s]
        mid = len(s) // 2
        cut = mid
        for d in range(mid):
            for j in (mid - d, mid + d):
                if 0 < j < len(s) and s[j] in "（(·/、｜|→ ":
                    cut = j
                    break
            else:
                continue
            break
        l1, l2 = s[:cut].strip(), s[cut:].strip()
        if len(l2) > maxlen:
            l2 = l2[: maxlen - 1] + "…"
        return [l1, l2]
    H = len(bands) * band_h + (len(bands) - 1) * gap + 2 * pad
    area_x = lab_w + 8
    area_w = W - area_x - pad
    parts = [
        f'<svg class="chain" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">',
        '<defs><marker id="ca" markerWidth="8" markerHeight="8" refX="5" refY="3" '
        'orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#bbb"/></marker></defs>',
    ]
    band_top: list[float] = []
    y = float(pad)
    for label, items in bands:
        band_top.append(y)
        parts.append(f'<text x="{pad}" y="{y + band_h/2 + 3:.0f}" font-size="9" '
                     f'fill="{BRAND}" font-weight="700">{_html.escape(label)}</text>')
        n = len(items)
        bw = min(158.0, (area_w - (n - 1) * 8) / n)
        total = n * bw + (n - 1) * 8
        x = area_x + (area_w - total) / 2
        maxlen = max(8, int(bw / 8.2))
        for it in items:
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.0f}" width="{bw:.1f}" height="{band_h}" '
                f'rx="5" fill="#FBF3F3" stroke="{BRAND}" stroke-width="0.8"/>')
            lines = _wrap2(it, maxlen)
            cx_b = x + bw / 2
            if len(lines) == 1:
                ys = [y + band_h / 2 + 3]
            else:
                ys = [y + band_h / 2 - 4, y + band_h / 2 + 9]
            for ln, yy in zip(lines, ys):
                parts.append(
                    f'<text x="{cx_b:.1f}" y="{yy:.0f}" font-size="7.6" '
                    f'fill="#1c1c1c" text-anchor="middle">{_html.escape(ln)}</text>')
            x += bw + 8
        y += band_h + gap
    cx = W / 2
    for i in range(len(bands) - 1):
        y1 = band_top[i] + band_h
        y2 = band_top[i + 1]
        parts.append(f'<line x1="{cx}" y1="{y1:.0f}" x2="{cx}" y2="{y2:.0f}" '
                     f'stroke="#bbb" stroke-width="1" marker-end="url(#ca)"/>')
    parts.append("</svg>")
    return '<div class="chainwrap">' + "".join(parts) + "</div>"


def _render_bom_table(spec: str) -> str:
    """把 ```bom``` 渲染成"成本拆解"表：成本列带 CSS 横向柱，直观看"钱被谁赚走"。

    每行：`部件 | 成本(数值,同一单位) | 同比 | A股映射 | 证据`。
    """
    rows: list[list[str]] = []
    for line in spec.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cells = [c.strip() for c in re.split(r"[|｜]", line)]
        if len(cells) >= 2 and cells[0]:
            rows.append(cells)
    if not rows:
        return ""

    def _num(s: str) -> float:
        m = re.search(r"[\d.]+", s.replace(",", ""))
        return float(m.group()) if m else 0.0

    maxc = max((_num(r[1]) for r in rows if len(r) > 1), default=0.0) or 1.0
    out = ['<table class="bom"><thead><tr>'
           '<th>部件</th><th>单机柜成本（柱＝相对占比）</th><th>同比</th>'
           '<th>A股映射</th><th>证据</th></tr></thead><tbody>']
    for r in rows:
        part = r[0]
        cost = r[1] if len(r) > 1 else ""
        yoy = r[2] if len(r) > 2 else ""
        mapp = r[3] if len(r) > 3 else ""
        ev = r[4] if len(r) > 4 else ""
        w = _num(cost) / maxc * 100
        out.append(
            f"<tr><td>{_html.escape(part)}</td>"
            f'<td class="bomcost"><span class="bombar"><span style="width:{w:.0f}%"></span></span>'
            f"{_html.escape(cost)}</td>"
            f"<td>{_html.escape(yoy)}</td><td>{_html.escape(mapp)}</td>"
            f"<td>{_html.escape(ev)}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


_URL_RE = re.compile(r'(?<!")(https?://[^\s<）)"]+)')


def _shorten_urls(html_str: str) -> str:
    """把正文里裸露的长 URL 换成"域名"可点击超链接，避免来源附录窄列硬换行、末页大片空白。"""
    def repl(match: re.Match[str]) -> str:
        url = match.group(1).rstrip("。，、")
        m = re.match(r"https?://([^/]+)", url)
        domain = (m.group(1) if m else url).replace("www.", "")
        return f'<a class="src" href="{url}">{_html.escape(domain)}</a>'

    return _URL_RE.sub(repl, html_str)


_TABLE_RE = re.compile(r"<table>(.*?)</table>", re.S)


def _tag_wide_tables(html_str: str) -> str:
    """列数 >7 的表加 class='wide'，缩字号防止撑破右边界。"""
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        head = re.search(r"<tr>(.*?)</tr>", inner, re.S)
        ncol = len(re.findall(r"<th\b", head.group(1))) if head else 0
        cls = " class='wide'" if ncol > 7 else ""
        return f"<table{cls}>{inner}</table>"

    return _TABLE_RE.sub(repl, html_str)


def _space_text(text: str) -> str:
    text = re.sub(rf"([A-Za-z0-9][A-Za-z0-9.:%+\-_]*)(?=[{CJK}])",
                  lambda m: m.group(1) + VISUAL, text)
    text = re.sub(rf"([{CJK}])(?=[A-Za-z])", lambda m: m.group(1) + VISUAL, text)
    text = re.sub(rf"(?<=[{CJK}])/(?=[{CJK}])", VISUAL + "/" + VISUAL, text)
    return text


def _space_text_nodes(html_str: str) -> str:
    """在 CJK↔拉丁、CJK/CJK 斜杠之间插细空格；跳过 <pre> 代码块。"""
    out: list[str] = []
    for seg in re.split(r"(<pre.*?</pre>|<svg.*?</svg>)", html_str, flags=re.S):
        if seg[:4] == "<pre" or seg[:4] == "<svg":
            out.append(seg)
        else:
            out.append(re.sub(r">([^<]+)<", lambda m: ">" + _space_text(m.group(1)) + "<", seg))
    return "".join(out)


def build_html(markdown_text: str, title: str) -> str:
    _title, cover_html, body_md = _split_cover(markdown_text)
    page_title = title or _title or "瓶颈侦察研报"

    chain_svgs: list[str] = []

    def _grab_chain(match: re.Match[str]) -> str:
        chain_svgs.append(_render_chain_svg(match.group(1)))
        return f"\n\nCHAINPLACEHOLDER{len(chain_svgs) - 1}\n\n"

    body_md = re.sub(r"```chain\n(.*?)```", _grab_chain, body_md, flags=re.S)

    bom_tables: list[str] = []

    def _grab_bom(match: re.Match[str]) -> str:
        bom_tables.append(_render_bom_table(match.group(1)))
        return f"\n\nBOMPLACEHOLDER{len(bom_tables) - 1}\n\n"

    body_md = re.sub(r"```bom\n(.*?)```", _grab_bom, body_md, flags=re.S)

    body_html = _md.markdown(
        body_md,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )
    for idx, svg in enumerate(chain_svgs):
        body_html = body_html.replace(f"<p>CHAINPLACEHOLDER{idx}</p>", svg)
        body_html = body_html.replace(f"CHAINPLACEHOLDER{idx}", svg)
    for idx, tbl in enumerate(bom_tables):
        body_html = body_html.replace(f"<p>BOMPLACEHOLDER{idx}</p>", tbl)
        body_html = body_html.replace(f"BOMPLACEHOLDER{idx}", tbl)
    for token, zh in FIELD_MAP:
        body_html = body_html.replace(token, zh)
    body_html = _shorten_urls(body_html)
    body_html = _tag_wide_tables(body_html)
    body_html = _wrap_sections(body_html)
    body_html = _colorize_cells(body_html)
    content = _space_text_nodes(cover_html + body_html)
    font_face = _font_face_css(_safe_cjk_font_file())  # 指向安全的 TrueType CJK 字体
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{_html.escape(page_title)}</title>"
        f"<meta name='author' content='{AUTHOR}'>"
        f"<meta name='description' content='{AUTHOR} 研究分析，不构成投资建议'>"
        f"<style>{font_face}{CSS}</style></head><body>{content}</body></html>"
    )


# 真正会让 PDF 预览乱码/掉字的是「被嵌入的 macOS 系统字体」
#（PingFang/Hiragino 等）以及 OTF/CFF CJK 字体。后者文本提取常常正常，
# 但 Apple Preview/Poppler 视觉渲染可能大量缺中文字形，所以默认禁用。
_UNSAFE_FONT_HINTS = ("pingfang", "hiragino", "songti", "stheiti", "stkaiti", "applesd")

# 只列稳定 TrueType/TTC 候选；不要把 Noto/SourceHan 的 OTF/CFF 版放进默认路径。
_SAFE_CJK_FONT_FILES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/msjh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/simsun.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/system/fonts/DroidSansFallback.ttf",
    "/usr/share/fonts/**/*NotoSansSC*.ttf",
    "/usr/share/fonts/**/*NotoSansCJK*.ttf",
    "/usr/local/share/fonts/**/*NotoSansSC*.ttf",
]


def _font_has_truetype_outlines(path: str) -> bool:
    """Return True only for fonts with glyf outlines; reject OTF/CFF even if CJK glyphs exist."""
    suffix = Path(path).suffix.lower()
    if suffix == ".otf":
        return False
    try:
        from fontTools.ttLib import TTCollection, TTFont
        if suffix == ".ttc":
            coll = TTCollection(path)
            return any("glyf" in font and "CFF " not in font and "CFF2" not in font for font in coll.fonts)
        font = TTFont(path)
        return "glyf" in font and "CFF " not in font and "CFF2" not in font
    except Exception:
        # Without fontTools, stay conservative: TTF is generally glyf; TTC is accepted for
        # Windows/Linux CJK fonts listed above, but OTF is never accepted.
        return suffix in {".ttf", ".ttc"}


def _safe_cjk_font_file() -> str:
    """返回第一个覆盖完整、Preview 安全（非系统、非 CFF）的 CJK 字体文件；找不到返回空串。

    优先用仓库自带 TrueType/TTC 字体（assets/fonts/cjk.{ttf,ttc}），保证跨机器确定。
    """
    import glob
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    fdir = os.path.join(os.path.dirname(here), "assets", "fonts")
    bundled = (sorted(glob.glob(os.path.join(fdir, "cjk.ttf")))
               + sorted(glob.glob(os.path.join(fdir, "cjk.ttc"))))
    user_fonts = [
        os.path.expanduser("~/Library/Fonts/NotoSansSC-Regular.ttf"),
        os.path.expanduser("~/Library/Fonts/NotoSansCJKsc-Regular.ttf"),
    ]
    for path in bundled + user_fonts + _SAFE_CJK_FONT_FILES:
        candidates = sorted(glob.glob(path, recursive=True)) if any(ch in path for ch in "*?[") else [path]
        for candidate in candidates:
            if candidate and os.path.exists(candidate) and _font_has_truetype_outlines(candidate):
                return candidate
    return ""


def _font_face_css(font_file: str) -> str:
    if not font_file:
        return ""
    uri = Path(font_file).as_uri()
    # 正常 + 粗体都指向同一个安全 TrueType 文件，避免粗体回退到系统 Noto 等 CFF 字体。
    return (
        f"@font-face{{font-family:'BSCJK';font-weight:normal;src:url('{uri}');}}"
        f"@font-face{{font-family:'BSCJK';font-weight:bold;src:url('{uri}');}}"
    )


def _embedded_font_problems(pdf_path: Path) -> list[str]:
    """检查 PDF 嵌入的字体是否对 Apple Preview 不安全：CFF(CIDFontType0) 或 macOS 系统字体。"""
    from pypdf import PdfReader

    problems: set[str] = set()
    try:
        reader = PdfReader(str(pdf_path))
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
                faces = [obj]
                desc = obj.get("/DescendantFonts")
                if desc:
                    for d in desc:
                        try:
                            faces.append(d.get_object())
                        except Exception:
                            pass
                for fnt in faces:
                    base = str(fnt.get("/BaseFont", "")).lower()
                    embedded = False
                    cff_embedded = False
                    fd = fnt.get("/FontDescriptor")
                    if fd is not None:
                        try:
                            fdo = fd.get_object()
                            embedded = any(k in fdo for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                            cff_embedded = "/FontFile3" in fdo
                        except Exception:
                            embedded = False
                            cff_embedded = False
                    if embedded and cff_embedded:
                        problems.add(f"嵌入 OTF/CFF 字体(预览易掉字):{base[:40]}")
                    if embedded:
                        for hint in _UNSAFE_FONT_HINTS:
                            if hint in base:
                                problems.add(f"嵌入系统字体(Preview易乱码):{base[:40]}")
    except Exception:
        return []
    return sorted(problems)


_ISOLATED_FONT_DIR = None


def _isolated_font_dir(font_file: str) -> str:
    """把选中的字体复制到一个独立临时目录，确保受限 fontconfig 只看到这一个字体
    （避免同目录其它字体文件——如 .ttc 集合里的 JP face——被误用）。"""
    global _ISOLATED_FONT_DIR
    if _ISOLATED_FONT_DIR is None:
        import os
        import shutil
        import tempfile
        d = tempfile.mkdtemp(prefix="bs-font-")
        shutil.copy(font_file, os.path.join(d, os.path.basename(font_file)))
        _ISOLATED_FONT_DIR = d
    return _ISOLATED_FONT_DIR


def _restricted_fontconfig(font_dir: str) -> str:
    """写一个只含指定字体目录的 fontconfig，禁止 WeasyPrint 回退到系统字体（如 PingFang）。"""
    import os
    import tempfile
    cache = os.path.join(tempfile.gettempdir(), "bs-fc-cache")
    conf = os.path.join(tempfile.gettempdir(), "bs-fonts.conf")
    with open(conf, "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">'
            f"<fontconfig><dir>{font_dir}</dir><cachedir>{cache}</cachedir>"
            "<config></config></fontconfig>"
        )
    return conf


def render(markdown_text: str, output: Path, title: str = "") -> int:
    import os
    import tempfile

    font_file = _safe_cjk_font_file()
    if not font_file:
        raise RuntimeError("WeasyPrint 未找到稳定 TrueType/TTC CJK 字体，回退 ReportLab")
    full_html = build_html(markdown_text, title)

    # 对所有选中的安全字体启用受限 fontconfig：WeasyPrint 只能看到这一枚
    # TrueType/TTC 字体，避免粗体/标点/缺字时偷偷回退到 Hiragino/PingFang
    # 等 OTF/CFF 或 macOS 系统 CJK 字体。
    use_restricted = bool(font_file)
    prev_fc = os.environ.get("FONTCONFIG_FILE")
    if use_restricted:
        os.environ["FONTCONFIG_FILE"] = _restricted_fontconfig(_isolated_font_dir(font_file))
    tmp_path: Path | None = None
    try:
        from weasyprint import HTML  # 延迟导入，便于上层在缺依赖时回退
        document = HTML(string=full_html).render()
        pages = len(document.pages)
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            prefix=f".{output.stem}.weasy-",
            dir=str(output.parent),
            delete=False,
        ) as fh:
            tmp_path = Path(fh.name)
        document.write_pdf(str(tmp_path))
    finally:
        if use_restricted:
            if prev_fc is None:
                os.environ.pop("FONTCONFIG_FILE", None)
            else:
                os.environ["FONTCONFIG_FILE"] = prev_fc

    # 渲染后硬闸（双保险）：先校验临时文件，只有通过后才替换目标文件。
    # 这样 forced WeasyPrint 失败时不会在目标路径留下坏 PDF。
    try:
        problems = _embedded_font_problems(tmp_path) if tmp_path else ["未生成临时 PDF"]
        if problems:
            raise RuntimeError(
                "WeasyPrint 输出含 Preview 不兼容字体，回退 ReportLab：" + "；".join(problems[:3])
            )
        tmp_path.replace(output)
    finally:
        if tmp_path and tmp_path.exists() and tmp_path != output:
            try:
                tmp_path.unlink()
            except Exception:
                pass
    return pages


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    n = render(src.read_text(encoding="utf-8"), dst, src.stem)
    print(f"{dst} ({n} 页)")
