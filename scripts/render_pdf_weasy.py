#!/usr/bin/env python3
"""WeasyPrint 后端：层级优先的 HTML/CSS → PDF。

对应 PDF 主次优化目标：
- 删掉每页重复抬头，只留一行细页脚。
- 首页"决策 Hero"：`## 结论` 区视觉权重最高（底色块 + 大标题 + 强色表头）。
- 评级/方向用色块 badge，让答案一眼可见。
- 来源清单/数据源/交付QA/跟踪清单等降为"参考资料"小字层级。
- 经 fontconfig 直接用系统 Noto / Source Han CJK，告别 STSong 细衬线。

仅依赖 weasyprint 与 markdown。作为 render_pdf.py 的默认后端，失败时回退 ReportLab。
"""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

import markdown as _md

BRAND = "#9F1D20"
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
  font-family: "Noto Sans CJK SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif;
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
code {{ font-family: "DejaVu Sans Mono", monospace; font-size: 8.2pt; }}
pre {{ background: #f4f4f4; color: #555; padding: 5pt 6pt; border-radius: 3pt;
       border-left: 2pt solid #ccc; white-space: pre-wrap;
       overflow-wrap: anywhere; word-break: break-all; font-size: 7.4pt;
       line-height: 1.35; }}
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
    for line in head.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# ") and not title:
            title = s[2:].strip()
        elif not s.startswith("#"):
            meta_lines.append(s)
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
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{_html.escape(page_title)}</title>"
        "<meta name='author' content='瓶颈侦察 v3'>"
        "<meta name='description' content='瓶颈侦察 v3 研究分析，不构成投资建议'>"
        f"<style>{CSS}</style></head><body>{content}</body></html>"
    )


def render(markdown_text: str, output: Path, title: str = "") -> int:
    from weasyprint import HTML  # 延迟导入，便于上层在缺依赖时回退

    full_html = build_html(markdown_text, title)
    document = HTML(string=full_html).render()
    pages = len(document.pages)
    document.write_pdf(str(output))
    return pages


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    n = render(src.read_text(encoding="utf-8"), dst, src.stem)
    print(f"{dst} ({n} 页)")
