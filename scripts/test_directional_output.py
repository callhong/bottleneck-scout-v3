import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
os.environ.setdefault("BOTTLENECK_NO_AUTOINSTALL", "1")


def install_reportlab_stubs() -> None:
    if "reportlab" in sys.modules:
        return

    reportlab = types.ModuleType("reportlab")
    lib = types.ModuleType("reportlab.lib")
    colors = types.ModuleType("reportlab.lib.colors")
    enums = types.ModuleType("reportlab.lib.enums")
    pagesizes = types.ModuleType("reportlab.lib.pagesizes")
    styles = types.ModuleType("reportlab.lib.styles")
    units = types.ModuleType("reportlab.lib.units")
    pdfbase = types.ModuleType("reportlab.pdfbase")
    pdfmetrics = types.ModuleType("reportlab.pdfbase.pdfmetrics")
    cidfonts = types.ModuleType("reportlab.pdfbase.cidfonts")
    ttfonts = types.ModuleType("reportlab.pdfbase.ttfonts")
    platypus = types.ModuleType("reportlab.platypus")
    toc = types.ModuleType("reportlab.platypus.tableofcontents")

    colors.HexColor = lambda value: value
    colors.white = "#ffffff"
    enums.TA_CENTER = 1
    enums.TA_LEFT = 0
    pagesizes.A4 = (595, 842)
    units.inch = 72

    class ParagraphStyle:
        def __init__(self, name="", parent=None, **kwargs):
            self.name = name
            self.parent = parent
            for key, value in kwargs.items():
                setattr(self, key, value)

    class SampleStylesheet:
        def __init__(self):
            self.byName = {
                "Title": ParagraphStyle(name="Title"),
                "Heading1": ParagraphStyle(name="Heading1"),
                "Heading2": ParagraphStyle(name="Heading2"),
                "BodyText": ParagraphStyle(name="BodyText"),
                "Code": ParagraphStyle(name="Code"),
            }

        def add(self, style):
            self.byName[style.name] = style

        def __getitem__(self, key):
            return self.byName[key]

    styles.ParagraphStyle = ParagraphStyle
    styles.getSampleStyleSheet = SampleStylesheet
    pdfmetrics.registerFont = lambda font: None
    cidfonts.UnicodeCIDFont = lambda name: name
    ttfonts.TTFont = lambda name, filename, subfontIndex=0: name

    class Dummy:
        def __init__(self, *args, **kwargs):
            pass

        def wrap(self, *args, **kwargs):
            return (0, 0)

        def drawOn(self, *args, **kwargs):
            return None

        def setStyle(self, *args, **kwargs):
            return None

    for name in [
        "Flowable",
        "HRFlowable",
        "PageBreak",
        "Paragraph",
        "Preformatted",
        "SimpleDocTemplate",
        "Spacer",
        "Table",
        "TableStyle",
    ]:
        setattr(platypus, name, type(name, (Dummy,), {}))
    toc.TableOfContents = Dummy

    reportlab.lib = lib
    sys.modules["reportlab"] = reportlab
    sys.modules["reportlab.lib"] = lib
    sys.modules["reportlab.lib.colors"] = colors
    sys.modules["reportlab.lib.enums"] = enums
    sys.modules["reportlab.lib.pagesizes"] = pagesizes
    sys.modules["reportlab.lib.styles"] = styles
    sys.modules["reportlab.lib.units"] = units
    sys.modules["reportlab.pdfbase"] = pdfbase
    sys.modules["reportlab.pdfbase.pdfmetrics"] = pdfmetrics
    sys.modules["reportlab.pdfbase.cidfonts"] = cidfonts
    sys.modules["reportlab.pdfbase.ttfonts"] = ttfonts
    sys.modules["reportlab.platypus"] = platypus
    sys.modules["reportlab.platypus.tableofcontents"] = toc


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


install_reportlab_stubs()
render_pdf = load_module("bottleneck_render_pdf", "render_pdf.py")
validate_report = load_module("bottleneck_validate_report", "validate_report.py")
validate_router = load_module("bottleneck_validate_router", "validate_router.py")


class DirectionalOutputTests(unittest.TestCase):
    def test_inline_markdown_colors_bullish_bearish_terms(self):
        rendered = render_pdf.inline_markdown(
            "directional_bias: 看多；expected_price_reaction: 看空；中性；待验证"
        )
        self.assertIn("#B42318", rendered)
        self.assertIn("#027A48", rendered)
        self.assertIn("#667085", rendered)
        self.assertIn("#B54708", rendered)

    def test_inline_markdown_strips_raw_html_span_styles(self):
        rendered = render_pdf.inline_markdown('<span style="color:red">偏多</span>')
        self.assertIn("偏多", rendered)
        self.assertIn("#B42318", rendered)
        self.assertNotIn("span", rendered.lower())
        self.assertNotIn("style", rendered.lower())

    def test_table_row_strips_raw_html_before_reportlab_layout(self):
        row = render_pdf.split_table_row(
            '| 弹性关注 | <span style="color:orange">待验证偏多</span> |'
        )
        self.assertEqual(row, ["弹性关注", "待验证偏多"])

    def test_inline_html_cleanup_does_not_strip_comparison_text(self):
        self.assertEqual(render_pdf.strip_inline_html("A < B > C"), "A < B > C")
        rendered = render_pdf.inline_markdown("A < B > C")
        self.assertIn("&lt;", rendered)
        self.assertIn("&gt;", rendered)
        self.assertIn("B", rendered)

    def test_validate_report_detects_directional_and_target_price_fields(self):
        text = """
## 公司证据与财务传导

| 公司 | 代码 | directional_bias | research_rating | expected_price_reaction | target_price_range | target_price_basis | target_time_horizon | invalidation_condition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 测试公司 | 000001.SZ | 看多 | 弹性关注 | 短中期偏正面 | 42-48元 | 分部收入与可比估值 | 6-12个月 | 订单增速连续下滑 |
"""
        self.assertTrue(validate_report.has_directional_fields(text))
        self.assertTrue(validate_report.has_target_price_fields(text))

    def test_markdown_separator_does_not_force_pdf_page_break(self):
        story = render_pdf.build_story(
            "# 测试报告\n\n## 结论\n核心结论。\n\n---\n\n## 提问背景\n新闻背景。",
            doc_width=480,
        )
        self.assertFalse(any(item.__class__.__name__ == "PageBreak" for item in story))
        self.assertTrue(any(item.__class__.__name__ == "HRFlowable" for item in story))

    def test_explicit_pagebreak_comment_forces_pdf_page_break(self):
        story = render_pdf.build_story(
            "# 测试报告\n\n## 结论\n核心结论。\n\n<!-- pagebreak -->\n\n## 提问背景\n新闻背景。",
            doc_width=480,
        )
        self.assertTrue(any(item.__class__.__name__ == "PageBreak" for item in story))

    def test_validate_report_requires_exact_first_section_conclusion(self):
        self.assertTrue(validate_report.section_present("## 结论\n正文", "结论"))
        self.assertFalse(validate_report.section_present("## 一页结论\n正文", "结论"))

    def test_conclusion_table_keeps_stock_code_column_wide_enough(self):
        widths = render_pdf.table_widths(
            9,
            1000,
            ["分级", "市场", "标的/环节", "代码", "方向", "风格", "证据等级", "核心理由", "失效条件"],
        )
        self.assertGreaterEqual(widths[3], 135)

    def test_new_conclusion_table_keeps_stock_code_column_wide_enough(self):
        widths = render_pdf.table_widths(
            10,
            1000,
            ["分层", "市场", "标的/环节", "代码", "方向", "风格", "综合评分", "证据等级", "核心理由", "失效条件"],
        )
        self.assertGreaterEqual(widths[3], 125)

    def test_code_table_cell_splits_multiple_company_codes(self):
        formatted = render_pdf.format_code_table_cell("湖南裕能（301358.SZ）/万润新能（688275.SH）")
        visible = formatted.replace("\u2060", "")
        self.assertEqual(
            visible,
            f"湖南裕能{render_pdf.LINE_BREAK_MARKER}301358.SZ"
            f"{render_pdf.LINE_BREAK_MARKER}万润新能{render_pdf.LINE_BREAK_MARKER}688275.SH",
        )
        self.assertGreaterEqual(render_pdf.inline_markdown(formatted).count("<br/>"), 3)

    def test_code_table_cell_preserves_na_placeholder(self):
        self.assertEqual(render_pdf.format_code_table_cell("N/A"), "N/A")
        self.assertEqual(render_pdf.format_code_table_cell("N / A"), "N/A")

    def test_share_class_terms_stay_in_cjk_font(self):
        rendered = render_pdf.inline_markdown("需关注H股折价与A股流动性")
        self.assertNotIn("<font name='Helvetica'>H</font>股", rendered)
        self.assertNotIn("<font name='Helvetica'>A</font>股", rendered)

    def test_router_rewrites_trading_questions_to_research_language(self):
        self.assertIn("研究评级", validate_router.rewrite("这个能买吗"))
        self.assertIn("验证窗口", validate_router.rewrite("什么时候买"))
        self.assertIn("风险等级", validate_router.rewrite("仓位多少"))
        self.assertIn("评分排序", validate_router.rewrite("哪个最值得看"))
        self.assertEqual(validate_router.classify("这条新闻利好谁")["mode"], "事件快评")

    def test_validate_report_enforces_evidence_caps(self):
        text = """
| 对象 | 最强证据 | 封顶后评分 | 分层 |
| --- | --- | ---: | --- |
| A | 框架推演 | 88 | 核心研究 |
| B | 待核验/线索级 | 70 | 弹性关注 |
"""
        errors = validate_report.validate_score_caps(text)
        self.assertTrue(any("64" in error for error in errors))
        self.assertTrue(any("49" in error for error in errors))
        self.assertTrue(any("core research" in error for error in errors))

    def test_validate_report_trading_language_context(self):
        self.assertFalse(validate_report.validate_trading_language("本报告不输出买入、加仓或仓位建议。"))
        errors = validate_report.validate_trading_language("建议买入测试公司并加仓。")
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
