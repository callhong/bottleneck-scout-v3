#!/usr/bin/env python3
"""Unit tests for the A-share data-source adapter.

These tests do not hit live network endpoints.
"""

from __future__ import annotations

import unittest
from unittest import mock
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
    content = b"%PDF sample"

    def __init__(self, payload):
        self._payload = payload

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
        ), mock.patch("data_sources.a_stock.download_pdf", side_effect=RuntimeError("pdf blocked")):
            snapshot = a_stock.fetch_snapshot("600519", ["reports"], download_report_pdfs=True, pdf_limit=2)
        dataset = snapshot["datasets"]["reports"]
        self.assertEqual(dataset["status"], "ok")
        self.assertEqual(dataset["data"], reports)
        self.assertEqual(dataset["downloaded_pdfs"], [])
        self.assertEqual(len(dataset["pdf_download_errors"]), 2)


if __name__ == "__main__":
    unittest.main()
