#!/usr/bin/env python3
"""Unit tests for the A-share data-source adapter.

These tests do not hit live network endpoints.
"""

from __future__ import annotations

import unittest
from unittest import mock
from tempfile import TemporaryDirectory
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_sources import a_stock
from data_sources.errors import NoUsableDataError


class FakeUrlopenResponse:
    def __init__(self, text: str):
        self._text = text

    def read(self) -> bytes:
        return self._text.encode("gbk")


class FakeResponse:
    status_code = 200

    def __init__(self, payload, content: bytes | None = None):
        self._payload = payload
        self.content = content if content is not None else b"%PDF sample"

    def json(self):
        return self._payload


class AStockAdapterTests(unittest.TestCase):
    def test_normalize_code_variants(self):
        cases = {
            "600519": "600519",
            "SH600519": "600519",
            "600519.SH": "600519",
            "sz000001": "000001",
            "BJ832000": "832000",
        }
        for raw, expected in cases.items():
            self.assertEqual(a_stock.normalize_code(raw), expected)
        self.assertEqual(a_stock.canonical_ticker("600519"), "600519.SH")
        self.assertEqual(a_stock.canonical_ticker("000001"), "000001.SZ")

    def test_tencent_quote_parses_core_fields(self):
        values = [""] * 60
        values[1] = "贵州茅台"
        values[3] = "1500.50"
        values[4] = "1490.00"
        values[5] = "1491.00"
        values[31] = "10.50"
        values[32] = "0.70"
        values[33] = "1510.00"
        values[34] = "1480.00"
        values[37] = "123456"
        values[38] = "0.82"
        values[39] = "28.5"
        values[43] = "2.0"
        values[44] = "18850"
        values[45] = "18850"
        values[46] = "8.2"
        values[47] = "1639.00"
        values[48] = "1341.00"
        values[49] = "1.1"
        values[52] = "29.0"
        text = 'v_sh600519="' + "~".join(values) + '";'
        with mock.patch("urllib.request.urlopen", return_value=FakeUrlopenResponse(text)):
            parsed = a_stock.tencent_quote(["600519"])
        self.assertEqual(parsed["600519"]["name"], "贵州茅台")
        self.assertEqual(parsed["600519"]["ticker"], "600519.SH")
        self.assertEqual(parsed["600519"]["price"], 1500.5)
        self.assertEqual(parsed["600519"]["pe_ttm"], 28.5)
        self.assertEqual(parsed["600519"]["pb"], 8.2)

    def test_tencent_quote_empty_response_is_no_usable_data(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeUrlopenResponse("")):
            with self.assertRaises(NoUsableDataError):
                a_stock.tencent_quote(["600519"])

    def test_eastmoney_stock_info_adds_canonical_ticker(self):
        payload = {
            "data": {
                "f57": "600519",
                "f58": "贵州茅台",
                "f127": "白酒",
                "f84": 1256197800,
                "f85": 1256197800,
                "f116": 1885000000000,
                "f117": 1885000000000,
                "f189": "20010827",
                "f43": 150050,
            }
        }
        with mock.patch("data_sources.a_stock.em_get", return_value=FakeResponse(payload)):
            info = a_stock.eastmoney_stock_info("600519")
        self.assertEqual(info["ticker"], "600519.SH")
        self.assertEqual(info["industry"], "白酒")

    def test_fetch_snapshot_records_dataset_status(self):
        with mock.patch.dict(
            a_stock.FETCHERS,
            {
                "quote": (
                    lambda code, **_: {"code": code, "price": 10},
                    a_stock.SourceMeta("测试源", "mock://quote"),
                ),
                "empty": (
                    lambda code, **_: [],
                    a_stock.SourceMeta("测试源", "mock://empty"),
                ),
            },
            clear=True,
        ):
            snapshot = a_stock.fetch_snapshot("000001", ["quote", "empty"])
        self.assertEqual(snapshot["ticker"], "000001.SZ")
        self.assertEqual(snapshot["datasets"]["quote"]["status"], "ok")
        self.assertEqual(snapshot["datasets"]["empty"]["status"], "empty")
        self.assertTrue(snapshot["policy"]["default_single_agent"])
        self.assertFalse(snapshot["policy"]["full_source_scan"])

    def test_fetch_snapshot_marks_full_source_scan_after_include_expansion(self):
        with mock.patch.dict(
            a_stock.FETCHERS,
            {
                "quote": (
                    lambda code, **_: {"code": code, "price": 10},
                    a_stock.SourceMeta("测试源", "mock://quote"),
                ),
                "empty": (
                    lambda code, **_: [],
                    a_stock.SourceMeta("测试源", "mock://empty"),
                ),
            },
            clear=True,
        ):
            snapshot = a_stock.fetch_snapshot("000001", a_stock.parse_include("all"))
        self.assertTrue(snapshot["policy"]["full_source_scan"])

    def test_fetch_snapshot_accepts_stock_info_with_extra_cli_kwargs(self):
        payload = {
            "data": {
                "f57": "600519",
                "f58": "贵州茅台",
                "f127": "白酒",
                "f84": 1256197800,
                "f85": 1256197800,
                "f116": 1885000000000,
                "f117": 1885000000000,
                "f189": "20010827",
                "f43": 150050,
            }
        }
        with mock.patch("data_sources.a_stock.em_get", return_value=FakeResponse(payload)):
            snapshot = a_stock.fetch_snapshot("600519", ["stock-info"], page_size=5, trade_date="2026-06-27")
        self.assertEqual(snapshot["datasets"]["stock-info"]["status"], "ok")
        self.assertEqual(snapshot["datasets"]["stock-info"]["data"]["ticker"], "600519.SH")

    def test_list_datasets_cli_does_not_require_ticker(self):
        with mock.patch("builtins.print") as mocked_print:
            code = a_stock.main(["--list-datasets"])
        self.assertEqual(code, 0)
        printed = "\n".join(call.args[0] for call in mocked_print.call_args_list)
        self.assertIn("reports", printed)
        self.assertIn("stock-news", printed)
        self.assertIn("answered-irm", printed)

    def test_list_presets_cli_does_not_require_ticker(self):
        with mock.patch("builtins.print") as mocked_print:
            code = a_stock.main(["--list-presets"])
        self.assertEqual(code, 0)
        printed = "\n".join(call.args[0] for call in mocked_print.call_args_list)
        self.assertIn("company: quote,stock-info,announcements,financials", printed)
        self.assertIn("market:", printed)

    def test_parse_include_uses_role_scoped_presets(self):
        self.assertEqual(a_stock.parse_include("", preset="company"), ["quote", "stock-info", "announcements", "financials"])
        deep = a_stock.parse_include("", preset="deep")
        self.assertIn("answered-irm", deep)
        self.assertIn("ths-eps-forecast", deep)
        self.assertNotIn("zt-pool", deep)
        custom = a_stock.parse_include("deep,market")
        self.assertIn("answered-irm", custom)
        self.assertIn("zt-pool", custom)

    def test_normalize_trade_date_accepts_dash_and_compact(self):
        self.assertEqual(a_stock.normalize_trade_date("2026-06-26", style="compact"), "20260626")
        self.assertEqual(a_stock.normalize_trade_date("20260626", style="dash"), "2026-06-26")

    def test_zt_time_formats_hhmm_and_hhmmss(self):
        self.assertEqual(a_stock._fmt_zt_time(930), "09:30")
        self.assertEqual(a_stock._fmt_zt_time(92503), "09:25:03")
        self.assertEqual(a_stock._fmt_zt_time(150000), "15:00:00")

    def test_em_zt_api_nonzero_rc_is_unusable_not_empty(self):
        with mock.patch("data_sources.a_stock.em_get", return_value=FakeResponse({"rc": 205, "data": None})):
            with self.assertRaises(NoUsableDataError):
                a_stock.em_zt_pool("2026-06-26")

    def test_em_zt_api_uses_zero_based_page_and_compact_date(self):
        captured = {}

        def fake_em_get(url, params=None, **kwargs):
            captured.update(params or {})
            return FakeResponse({"rc": 0, "data": {"pool": []}})

        with mock.patch("data_sources.a_stock.em_get", side_effect=fake_em_get):
            a_stock.em_zt_pool("2026-06-26")
        self.assertEqual(captured["Pageindex"], 0)
        self.assertEqual(captured["date"], "20260626")

    def test_ths_limit_up_pool_maps_current_fields(self):
        payload = {
            "status_code": 0,
            "data": {
                "info": [
                    {
                        "code": "688409",
                        "name": "富创精密",
                        "latest": 274.8,
                        "change_rate": 20.0,
                        "reason_type": "半导体设备+一季报扭亏",
                        "limit_up_type": "换手板",
                        "limit_up_suc_rate": 1.0,
                        "open_num": None,
                        "order_amount": 533257920.0,
                        "currency_value": 84146720000.0,
                        "turnover_rate": 3.9028,
                        "high_days": "首板",
                        "first_limit_up_time": "1782456938",
                        "last_limit_up_time": "1782456938",
                        "is_again_limit": 0,
                        "market_type": "STAR",
                    }
                ]
            },
        }
        with mock.patch("requests.get", return_value=FakeResponse(payload)):
            rows = a_stock.ths_limit_up_pool("2026-06-26")
        self.assertEqual(rows[0]["price"], 274.8)
        self.assertEqual(rows[0]["pct"], 20.0)
        self.assertEqual(rows[0]["reason"], "半导体设备+一季报扭亏")
        self.assertEqual(rows[0]["board_type"], "换手板")
        self.assertEqual(rows[0]["break_times"], 0)
        self.assertEqual(rows[0]["seal_amount_yi"], 5.33)
        self.assertEqual(rows[0]["first_seal"], "14:55:38")
        self.assertEqual(rows[0]["row_evidence_level"], "待核验/线索级")
        self.assertEqual(rows[0]["research_role"], "market_temperature")

    def test_cninfo_irm_marks_unanswered_questions_as_leads(self):
        first = FakeResponse({"data": [{"secid": "990000"}]})
        second = FakeResponse(
            {
                "rows": [
                    {
                        "stockCode": "002475",
                        "companyShortName": "立讯精密",
                        "mainContent": "请问液冷进展？",
                        "attachedContent": None,
                        "attachedAuthor": None,
                        "pubDate": 1782131888000,
                    },
                    {
                        "stockCode": "002475",
                        "companyShortName": "立讯精密",
                        "mainContent": "请问股东人数？",
                        "attachedContent": "截至5月29日为397,768户",
                        "attachedAuthor": "立讯精密",
                        "pubDate": 1780790527000,
                    },
                ]
            }
        )
        with mock.patch("requests.post", side_effect=[first, second]):
            rows = a_stock.cninfo_irm("002475")
        self.assertFalse(rows[0]["answered"])
        self.assertEqual(rows[0]["row_evidence_level"], "待核验/线索级")
        self.assertEqual(rows[0]["claim_scope"], "investor_question_only")
        self.assertTrue(rows[1]["answered"])
        self.assertEqual(rows[1]["row_evidence_level"], "直接证据")
        self.assertEqual(rows[1]["claim_scope"], "company_answer")

    def test_cninfo_irm_answered_only_filters_unanswered(self):
        first = FakeResponse({"data": [{"secid": "990000"}]})
        second = FakeResponse(
            {
                "rows": [
                    {"stockCode": "002475", "companyShortName": "立讯精密", "mainContent": "未答", "attachedContent": None, "attachedAuthor": None},
                    {"stockCode": "002475", "companyShortName": "立讯精密", "mainContent": "已答", "attachedContent": "答复", "attachedAuthor": "立讯精密"},
                ]
            }
        )
        with mock.patch("requests.post", side_effect=[first, second]):
            rows = a_stock.cninfo_irm("002475", answered_only=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question"], "已答")

    def test_unexpected_fetcher_error_degrades_dataset(self):
        with mock.patch.dict(
            a_stock.FETCHERS,
            {
                "broken": (
                    lambda code, **_: (_ for _ in ()).throw(ValueError("bad json")),
                    a_stock.SourceMeta("坏源", "mock://broken"),
                )
            },
            clear=True,
        ):
            snapshot = a_stock.fetch_snapshot("600519", ["broken"])
        self.assertEqual(snapshot["datasets"]["broken"]["status"], "unavailable")
        self.assertIn("ValueError", snapshot["datasets"]["broken"]["error"])

    def test_report_pdf_download_errors_do_not_discard_report_list(self):
        reports = [
            {"title": "研报A", "infoCode": "A1", "publishDate": "2026-06-27", "orgSName": "机构"},
            {"title": "研报B", "infoCode": "B1", "publishDate": "2026-06-27", "orgSName": "机构"},
        ]
        with mock.patch.dict(
            a_stock.FETCHERS,
            {"reports": (lambda code, **_: reports, a_stock.SourceMeta("东方财富", "mock://reports", kind="research_report"))},
            clear=True,
        ), mock.patch("data_sources.a_stock.download_pdf_artifact", side_effect=RuntimeError("pdf blocked")):
            snapshot = a_stock.fetch_snapshot("600519", ["reports"], download_report_pdfs=True, pdf_limit=2)
        dataset = snapshot["datasets"]["reports"]
        self.assertEqual(dataset["status"], "ok")
        self.assertEqual(dataset["data"], reports)
        self.assertEqual(dataset["downloaded_pdfs"], [])
        self.assertEqual(len(dataset["pdf_download_errors"]), 2)

    def test_report_pdf_download_writes_run_manifest(self):
        reports = [{"title": "研报A", "infoCode": "AP1", "publishDate": "2026-06-27", "orgSName": "机构"}]
        content = b"%PDF-1.4\n" + b"x" * 2048
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(
                a_stock.FETCHERS,
                {"reports": (lambda code, **_: reports, a_stock.SourceMeta("东方财富", "mock://reports", kind="research_report"))},
                clear=True,
            ), mock.patch("data_sources.a_stock.em_get", return_value=FakeResponse({}, content=content)):
                snapshot = a_stock.fetch_snapshot(
                    "600519",
                    ["reports"],
                    download_report_pdfs=True,
                    artifact_root=tmp,
                    run_id="run-a",
                    pdf_limit=1,
                )
            manifest_path = Path(snapshot["artifacts"]["manifest_path"])
            self.assertTrue(manifest_path.exists())
            manifest = a_stock.json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["run_id"], "run-a")
            self.assertEqual(len(manifest["sources"]), 1)
            entry = manifest["sources"][0]
            self.assertEqual(entry["infoCode"], "AP1")
            self.assertFalse(entry["reused_from_cache"])
            self.assertTrue(Path(entry["path"]).exists())
            self.assertEqual(entry["sha256"], a_stock._sha256_file(Path(entry["path"])))
            self.assertEqual(snapshot["datasets"]["reports"]["pdf_manifest_entries"][0]["infoCode"], "AP1")

    def test_report_pdf_cache_reuses_same_infocode_with_new_manifest_entry(self):
        reports = [{"title": "研报A", "infoCode": "AP1", "publishDate": "2026-06-27", "orgSName": "机构"}]
        content = b"%PDF-1.4\n" + b"x" * 2048
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(
                a_stock.FETCHERS,
                {"reports": (lambda code, **_: reports, a_stock.SourceMeta("东方财富", "mock://reports", kind="research_report"))},
                clear=True,
            ), mock.patch("data_sources.a_stock.em_get", return_value=FakeResponse({}, content=content)) as mocked_get:
                first = a_stock.fetch_snapshot(
                    "600519",
                    ["reports"],
                    download_report_pdfs=True,
                    artifact_root=tmp,
                    run_id="run-a",
                    pdf_limit=1,
                    pdf_cache_days=1,
                )
                second = a_stock.fetch_snapshot(
                    "600519",
                    ["reports"],
                    download_report_pdfs=True,
                    artifact_root=tmp,
                    run_id="run-b",
                    pdf_limit=1,
                    pdf_cache_days=1,
                )
            self.assertEqual(mocked_get.call_count, 1)
            first_entry = first["datasets"]["reports"]["pdf_manifest_entries"][0]
            second_entry = second["datasets"]["reports"]["pdf_manifest_entries"][0]
            self.assertFalse(first_entry["reused_from_cache"])
            self.assertTrue(second_entry["reused_from_cache"])
            self.assertEqual(first_entry["sha256"], second_entry["sha256"])
            self.assertNotEqual(first_entry["path"], second_entry["path"])

    def test_report_pdf_manifest_dedupes_same_report_in_same_run(self):
        reports = [{"title": "研报A", "infoCode": "AP1", "publishDate": "2026-06-27", "orgSName": "机构"}]
        content = b"%PDF-1.4\n" + b"x" * 2048
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(
                a_stock.FETCHERS,
                {"reports": (lambda code, **_: reports, a_stock.SourceMeta("东方财富", "mock://reports", kind="research_report"))},
                clear=True,
            ), mock.patch("data_sources.a_stock.em_get", return_value=FakeResponse({}, content=content)):
                a_stock.fetch_snapshot(
                    "600519",
                    ["reports"],
                    download_report_pdfs=True,
                    artifact_root=tmp,
                    run_id="same-run",
                    pdf_limit=1,
                )
                snapshot = a_stock.fetch_snapshot(
                    "600519",
                    ["reports"],
                    download_report_pdfs=True,
                    artifact_root=tmp,
                    run_id="same-run",
                    pdf_limit=1,
                )
            manifest = a_stock.json.loads(Path(snapshot["artifacts"]["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["sources"]), 1)
            self.assertEqual(manifest["sources"][0]["infoCode"], "AP1")

    def test_report_pdf_manifest_accumulates_across_tickers_in_same_run(self):
        def fake_reports(code, **_):
            return [{"title": f"研报{code}", "infoCode": f"AP{code}", "publishDate": "2026-06-27", "orgSName": "机构"}]

        content = b"%PDF-1.4\n" + b"x" * 2048
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(
                a_stock.FETCHERS,
                {"reports": (fake_reports, a_stock.SourceMeta("东方财富", "mock://reports", kind="research_report"))},
                clear=True,
            ), mock.patch("data_sources.a_stock.em_get", return_value=FakeResponse({}, content=content)):
                first = a_stock.fetch_snapshot(
                    "600519",
                    ["reports"],
                    download_report_pdfs=True,
                    artifact_root=tmp,
                    run_id="shared-run",
                    pdf_limit=1,
                )
                second = a_stock.fetch_snapshot(
                    "000001",
                    ["reports"],
                    download_report_pdfs=True,
                    artifact_root=tmp,
                    run_id="shared-run",
                    pdf_limit=1,
                )
            manifest_path = Path(second["artifacts"]["manifest_path"])
            self.assertEqual(Path(first["artifacts"]["manifest_path"]), manifest_path)
            manifest = a_stock.json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["tickers"], ["600519.SH", "000001.SZ"])
            self.assertEqual([entry["infoCode"] for entry in manifest["sources"]], ["AP600519", "AP000001"])


if __name__ == "__main__":
    unittest.main()
