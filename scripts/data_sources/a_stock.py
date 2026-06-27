"""A-share public data fetchers adapted from a-stock-data.

Source project: https://github.com/simonlin1212/a-stock-data
License: Apache-2.0. This module copies and adapts a focused subset of the
public endpoint logic so bottleneck-scout-v3 can run without referencing the
external repository at runtime.

Default policy:
- Use explicit calls only; do not scan all providers by default.
- Keep Eastmoney requests serial and throttled.
- Attach source/date/evidence metadata so reports can downgrade weak data.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from data_sources.errors import (
    DataSourceError,
    DataSourceRateLimitError,
    DataSourceUnavailableError,
    NoUsableDataError,
)


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]
_CNINFO_ORGID_MAP: dict[str, str] = {}


@dataclass(frozen=True)
class SourceMeta:
    source: str
    endpoint: str
    evidence_level: str = "直接证据"
    kind: str = "market_data"
    status: str = "ok"

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "endpoint": self.endpoint,
            "evidence_level": self.evidence_level,
            "kind": self.kind,
            "status": self.status,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_code(code: str) -> str:
    """Normalize SH/SZ/BJ-prefixed or suffixed tickers into six digits."""
    text = str(code or "").strip().upper()
    text = re.sub(r"^(SH|SZ|BJ)", "", text)
    text = re.sub(r"\.(SH|SZ|BJ)$", "", text)
    text = re.sub(r"\D", "", text)
    if not re.fullmatch(r"\d{6}", text):
        raise ValueError(f"invalid A-share code: {code!r}")
    return text


def exchange_suffix(code: str) -> str:
    code = normalize_code(code)
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("8", "4")):
        return "BJ"
    return "SZ"


def market_prefix(code: str) -> str:
    code = normalize_code(code)
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("8", "4")):
        return "bj"
    return "sz"


def eastmoney_market_code(code: str) -> int:
    return 1 if normalize_code(code).startswith(("6", "9")) else 0


def canonical_ticker(code: str) -> str:
    normalized = normalize_code(code)
    return f"{normalized}.{exchange_suffix(normalized)}"


def _to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "-", "--"):
        return default
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def source_record(meta: SourceMeta, data: Any, *, status: str = "ok", error: str = "") -> dict[str, Any]:
    record = meta.as_dict()
    record.update(
        {
            "retrieved": now_iso(),
            "status": status,
            "data": data,
        }
    )
    if error:
        record["error"] = error
    return record


def em_get(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    **kwargs: Any,
) -> requests.Response:
    """Eastmoney request gate: serial throttle, session reuse, browser UA."""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        response = EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"Eastmoney request failed: {exc}") from exc
    finally:
        _em_last_call[0] = time.time()
    if response.status_code in {403, 429}:
        raise DataSourceRateLimitError(f"Eastmoney HTTP {response.status_code}")
    return response


def eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict[str, Any]]:
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    response = em_get(DATACENTER_URL, params=params, timeout=15)
    data = response.json()
    rows = (data.get("result") or {}).get("data") or []
    return rows if isinstance(rows, list) else []


def tencent_quote(codes: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch Tencent real-time quotes: price, PE/PB, market cap, turnover."""
    normalized = [normalize_code(code) for code in codes]
    prefixed = [f"{market_prefix(code)}{code}" for code in normalized]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "Mozilla/5.0")
    try:
        response = urllib.request.urlopen(request, timeout=10)
        text = response.read().decode("gbk")
    except Exception as exc:  # urllib raises several non-RequestException types.
        raise DataSourceUnavailableError(f"Tencent quote request failed: {exc}") from exc

    result: dict[str, dict[str, Any]] = {}
    for line in text.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        values = line.split('"')[1].split("~")
        if len(values) < 53:
            continue
        code = key[2:]
        result[code] = {
            "code": code,
            "ticker": canonical_ticker(code),
            "name": values[1],
            "price": _to_float(values[3]),
            "last_close": _to_float(values[4]),
            "open": _to_float(values[5]),
            "change_amt": _to_float(values[31]),
            "change_pct": _to_float(values[32]),
            "high": _to_float(values[33]),
            "low": _to_float(values[34]),
            "amount_wan": _to_float(values[37]),
            "turnover_pct": _to_float(values[38]),
            "pe_ttm": _to_float(values[39]),
            "amplitude_pct": _to_float(values[43]),
            "mcap_yi": _to_float(values[44]),
            "float_mcap_yi": _to_float(values[45]),
            "pb": _to_float(values[46]),
            "limit_up": _to_float(values[47]),
            "limit_down": _to_float(values[48]),
            "vol_ratio": _to_float(values[49]),
            "pe_static": _to_float(values[52]),
        }
    missing = [code for code in normalized if code not in result]
    if missing and not result:
        raise NoUsableDataError("Tencent quote", ",".join(missing), "empty or unparsable response")
    return result


def eastmoney_reports(code: str, max_pages: int = 2) -> list[dict[str, Any]]:
    code = normalize_code(code)
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2000-01-01",
            "endTime": "2030-01-01",
            "pageNo": str(page),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": code,
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        }
        response = em_get(REPORT_API, params=params, headers={"Referer": "https://data.eastmoney.com/"}, timeout=30)
        payload = response.json()
        rows = payload.get("data") or []
        if not rows:
            break
        records.extend(rows)
        if page >= (payload.get("TotalPage", 1) or 1):
            break
    return records


def eastmoney_industry_reports(industry_code: str = "*", max_pages: int = 2, begin: str = "2024-01-01") -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": industry_code,
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": begin,
            "endTime": "2030-01-01",
            "pageNo": str(page),
            "fields": "",
            "qType": "1",
        }
        response = em_get(REPORT_API, params=params, headers={"Referer": "https://data.eastmoney.com/"}, timeout=30)
        payload = response.json()
        rows = payload.get("data") or []
        if not rows:
            break
        records.extend(rows)
        if page >= (payload.get("TotalPage", 1) or 1):
            break
    return records


def download_pdf(record: dict[str, Any], target_dir: str | Path = "./reports") -> str | None:
    info_code = record.get("infoCode", "")
    if not info_code:
        return None
    date = (record.get("publishDate") or "")[:10]
    org = record.get("orgSName") or "未知"
    title = re.sub(r'[\\/:*?"<>|]', "_", record.get("title", ""))[:80]
    target = Path(target_dir) / f"{date}_{org}_{title}.pdf"
    if target.exists():
        return str(target)
    response = em_get(PDF_TPL.format(info_code=info_code), headers={"Referer": "https://data.eastmoney.com/"}, timeout=60)
    if response.status_code == 200 and len(response.content) >= 1024 and response.content.startswith(b"%PDF"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return str(target)
    return None


def eastmoney_concept_blocks(code: str) -> dict[str, Any]:
    code = normalize_code(code)
    params = {
        "fltt": "2",
        "invt": "2",
        "secid": f"{eastmoney_market_code(code)}.{code}",
        "spt": "3",
        "pi": "0",
        "pz": "200",
        "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    response = em_get(
        "https://push2.eastmoney.com/api/qt/slist/get",
        params=params,
        headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
        timeout=15,
    )
    payload = response.json()
    diff = (payload.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = [
        {
            "name": item.get("f14", ""),
            "code": item.get("f12", ""),
            "change_pct": item.get("f3", ""),
            "lead_stock": item.get("f128", ""),
        }
        for item in items
        if isinstance(item, dict)
    ]
    return {"total": len(boards), "boards": boards, "concept_tags": [board["name"] for board in boards]}


def eastmoney_stock_info(code: str) -> dict[str, Any]:
    code = normalize_code(code)
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
        "secid": f"{eastmoney_market_code(code)}.{code}",
    }
    response = em_get(
        "https://push2.eastmoney.com/api/qt/stock/get",
        params=params,
        headers={"User-Agent": UA},
        timeout=10,
    )
    data = response.json().get("data", {}) or {}
    if not data:
        raise NoUsableDataError("Eastmoney stock info", code, "empty data")
    return {
        "code": data.get("f57", ""),
        "ticker": canonical_ticker(code),
        "name": data.get("f58", ""),
        "industry": data.get("f127", ""),
        "total_shares": data.get("f84", 0),
        "float_shares": data.get("f85", 0),
        "mcap": data.get("f116", 0),
        "float_mcap": data.get("f117", 0),
        "list_date": str(data.get("f189", "")),
        "price": data.get("f43", 0),
    }


def stock_fund_flow_120d(code: str) -> list[dict[str, Any]]:
    code = normalize_code(code)
    params = {
        "secid": f"{eastmoney_market_code(code)}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    response = em_get(
        "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
        params=params,
        headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
        timeout=15,
    )
    klines = (response.json().get("data") or {}).get("klines") or []
    rows: list[dict[str, Any]] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append(
                {
                    "date": parts[0],
                    "main_net": _to_float(parts[1]),
                    "small_net": _to_float(parts[2]),
                    "mid_net": _to_float(parts[3]),
                    "large_net": _to_float(parts[4]),
                    "super_net": _to_float(parts[5]),
                }
            )
    return rows


def baidu_kline_with_ma(code: str, start_time: str = "") -> dict[str, Any]:
    """Baidu K-line endpoint with MA5/MA10/MA20 fields."""
    code = normalize_code(code)
    url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
    params = {
        "all": "1",
        "isIndex": "false",
        "isBk": "false",
        "isBlock": "false",
        "isFutures": "false",
        "isStock": "true",
        "newFormat": "1",
        "group": "quotation_kline_ab",
        "finClientType": "pc",
        "code": code,
        "start_time": start_time,
        "ktype": "1",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"Baidu kline request failed: {exc}") from exc
    market_data = ((response.json().get("Result") or {}).get("newMarketData") or {})
    return {
        "keys": market_data.get("keys", []),
        "rows": [row for row in str(market_data.get("marketData", "")).split(";") if row],
    }


def eastmoney_fund_flow_minute(code: str) -> list[dict[str, Any]]:
    """Intraday minute-level Eastmoney fund flow."""
    code = normalize_code(code)
    params = {
        "secid": f"{eastmoney_market_code(code)}.{code}",
        "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    response = em_get(
        "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
        params=params,
        headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
        timeout=10,
    )
    rows: list[dict[str, Any]] = []
    for line in (response.json().get("data") or {}).get("klines", []) or []:
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append(
                {
                    "time": parts[0],
                    "main_net": _to_float(parts[1]),
                    "small_net": _to_float(parts[2]),
                    "mid_net": _to_float(parts[3]),
                    "large_net": _to_float(parts[4]),
                    "super_net": _to_float(parts[5]),
                }
            )
    return rows


def block_trade(code: str, page_size: int = 20) -> list[dict[str, Any]]:
    code = normalize_code(code)
    rows = eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    records = []
    for row in rows:
        close = _to_float(row.get("CLOSE_PRICE"))
        deal_price = _to_float(row.get("DEAL_PRICE"))
        premium = (deal_price / close - 1) * 100 if close else 0
        records.append(
            {
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "price": deal_price,
                "close": close,
                "premium_pct": round(premium, 2),
                "vol": row.get("DEAL_VOLUME", 0),
                "amount": row.get("DEAL_AMT", 0),
                "buyer": row.get("BUYER_NAME", ""),
                "seller": row.get("SELLER_NAME", ""),
            }
        )
    return records


def dragon_tiger_board(code: str, trade_date: str, look_back: int = 30) -> dict[str, Any]:
    code = normalize_code(code)
    start_date = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
    records = []
    detail_rows = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f'(TRADE_DATE>="{start_date:%Y-%m-%d}")(TRADE_DATE<="{trade_date}")(SECURITY_CODE="{code}")',
        page_size=50,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    for row in detail_rows:
        records.append(
            {
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "reason": row.get("EXPLANATION", ""),
                "net_buy_wan": round(_to_float(row.get("BILLBOARD_NET_AMT")) / 10000, 1),
                "turnover_pct": round(_to_float(row.get("TURNOVERRATE")), 2),
            }
        )

    seats = {"buy": [], "sell": []}
    institution = {"buy_amt_wan": 0.0, "sell_amt_wan": 0.0, "net_amt_wan": 0.0}
    if records:
        latest_date = records[0]["date"]
        for report_name, side, sort_column in (
            ("RPT_BILLBOARD_DAILYDETAILSBUY", "buy", "BUY"),
            ("RPT_BILLBOARD_DAILYDETAILSSELL", "sell", "SELL"),
        ):
            side_rows = eastmoney_datacenter(
                report_name,
                filter_str=f'(TRADE_DATE="{latest_date}")(SECURITY_CODE="{code}")',
                page_size=10,
                sort_columns=sort_column,
                sort_types="-1",
            )
            for row in side_rows[:5]:
                seats[side].append(
                    {
                        "name": row.get("OPERATEDEPT_NAME", ""),
                        "buy_amt_wan": round(_to_float(row.get("BUY")) / 10000, 1),
                        "sell_amt_wan": round(_to_float(row.get("SELL")) / 10000, 1),
                        "net_wan": round(_to_float(row.get("NET")) / 10000, 1),
                    }
                )
            for row in side_rows:
                if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                    institution["buy_amt_wan"] += _to_float(row.get("BUY")) / 10000
                    institution["sell_amt_wan"] += _to_float(row.get("SELL")) / 10000
    institution["buy_amt_wan"] = round(institution["buy_amt_wan"], 1)
    institution["sell_amt_wan"] = round(institution["sell_amt_wan"], 1)
    institution["net_amt_wan"] = round(institution["buy_amt_wan"] - institution["sell_amt_wan"], 1)
    return {"records": records, "seats": seats, "institution": institution}


def lockup_expiry(code: str, trade_date: str, forward_days: int = 90) -> dict[str, Any]:
    code = normalize_code(code)
    history_rows = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=15,
        sort_columns="FREE_DATE",
        sort_types="-1",
    )
    end_date = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)
    upcoming_rows = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")(FREE_DATE>="{trade_date}")(FREE_DATE<="{end_date:%Y-%m-%d}")',
        page_size=20,
        sort_columns="FREE_DATE",
        sort_types="1",
    )

    def convert(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "date": str(row.get("FREE_DATE", ""))[:10],
            "type": row.get("LIMITED_STOCK_TYPE", ""),
            "shares": row.get("FREE_SHARES_NUM", 0),
            "ratio": row.get("FREE_RATIO", 0),
        }

    return {"history": [convert(row) for row in history_rows], "upcoming": [convert(row) for row in upcoming_rows]}


def industry_comparison(top_n: int = 20) -> dict[str, Any]:
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    response = em_get(
        "https://push2.eastmoney.com/api/qt/clist/get",
        params=params,
        headers={"User-Agent": UA},
        timeout=15,
    )
    items = (response.json().get("data") or {}).get("diff", []) or []
    rows = [
        {
            "rank": idx + 1,
            "name": item.get("f14", ""),
            "change_pct": item.get("f3", 0),
            "code": item.get("f12", ""),
            "up_count": item.get("f104", 0),
            "down_count": item.get("f105", 0),
            "leader": item.get("f140", ""),
            "leader_change": item.get("f136", 0),
        }
        for idx, item in enumerate(items)
        if isinstance(item, dict)
    ]
    return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}


def daily_dragon_tiger(trade_date: str, min_net_buy: float | None = None) -> dict[str, Any]:
    rows = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f'(TRADE_DATE>="{trade_date}")(TRADE_DATE<="{trade_date}")',
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT",
        sort_types="-1",
    )
    stocks = []
    for row in rows:
        net_buy = _to_float(row.get("BILLBOARD_NET_AMT")) / 10000
        if min_net_buy is not None and net_buy < min_net_buy:
            continue
        stocks.append(
            {
                "code": row.get("SECURITY_CODE", ""),
                "name": row.get("SECURITY_NAME_ABBR", ""),
                "reason": row.get("EXPLANATION", ""),
                "close": row.get("CLOSE_PRICE") or 0,
                "change_pct": round(_to_float(row.get("CHANGE_RATE")), 2),
                "net_buy_wan": round(net_buy, 1),
                "buy_wan": round(_to_float(row.get("BILLBOARD_BUY_AMT")) / 10000, 1),
                "sell_wan": round(_to_float(row.get("BILLBOARD_SELL_AMT")) / 10000, 1),
                "turnover_pct": round(_to_float(row.get("TURNOVERRATE")), 2),
            }
        )
    actual_date = str(rows[0].get("TRADE_DATE", ""))[:10] if rows else trade_date
    return {"date": actual_date, "total_records": len(stocks), "stocks": stocks}


def ths_hot_reason(date: str) -> list[dict[str, Any]]:
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"THS hot reason request failed: {exc}") from exc
    payload = response.json()
    if payload.get("errocode", 0) != 0:
        raise NoUsableDataError("同花顺热点", date, payload.get("errormsg", ""))
    return payload.get("data") or []


def hsgt_realtime() -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36",
        "Host": "data.hexin.cn",
        "Referer": "https://data.hexin.cn/",
    }
    try:
        response = requests.get("https://data.hexin.cn/market/hsgtApi/method/dayChart/", headers=headers, timeout=10)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"Northbound request failed: {exc}") from exc
    payload = response.json()
    times = payload.get("time", [])
    hgt = payload.get("hgt", [])
    sgt = payload.get("sgt", [])
    rows = []
    for idx, point in enumerate(times):
        rows.append(
            {
                "time": point,
                "hgt_yi": hgt[idx] if idx < len(hgt) else None,
                "sgt_yi": sgt[idx] if idx < len(sgt) else None,
            }
        )
    return rows


def eastmoney_stock_news(code: str, page_size: int = 20) -> list[dict[str, Any]]:
    code = normalize_code(code)
    inner_params = json.dumps(
        {
            "uid": "",
            "keyword": code,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": page_size,
                    "preTag": "",
                    "postTag": "",
                }
            },
        },
        separators=(",", ":"),
    )
    response = em_get(
        "https://search-api-web.eastmoney.com/search/jsonp",
        params={"cb": "jQuery_news", "param": inner_params},
        headers={"User-Agent": UA, "Referer": "https://so.eastmoney.com/"},
        timeout=15,
    )
    text = response.text
    if "(" not in text or ")" not in text:
        raise NoUsableDataError("东方财富个股新闻", code, "unparsable JSONP")
    payload = json.loads(text[text.index("(") + 1 : text.rindex(")")])
    articles = (payload.get("result") or {}).get("cmsArticleWebOld", []) or []
    rows = []
    for item in articles:
        rows.append(
            {
                "title": re.sub(r"<[^>]+>", "", item.get("title", "")),
                "content": re.sub(r"<[^>]+>", "", item.get("content", ""))[:200],
                "time": item.get("date", ""),
                "source": item.get("mediaName", ""),
                "url": item.get("url", ""),
            }
        )
    return rows


def eastmoney_global_news(page_size: int = 50) -> list[dict[str, Any]]:
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": "102",
        "sortEnd": "",
        "pageSize": str(page_size),
        "req_trace": str(uuid.uuid4()),
    }
    response = em_get(
        "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
        params=params,
        headers={"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"},
        timeout=10,
    )
    rows = []
    for item in ((response.json().get("data") or {}).get("fastNewsList") or []):
        rows.append(
            {
                "title": item.get("title", ""),
                "summary": item.get("summary", "")[:200],
                "time": item.get("showTime", ""),
            }
        )
    return rows


def margin_trading(code: str, page_size: int = 30) -> list[dict[str, Any]]:
    code = normalize_code(code)
    rows = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_str=f'(SCODE="{code}")',
        page_size=page_size,
        sort_columns="DATE",
        sort_types="-1",
    )
    return [
        {
            "date": str(row.get("DATE", ""))[:10],
            "rzye": row.get("RZYE", 0),
            "rzmre": row.get("RZMRE", 0),
            "rzche": row.get("RZCHE", 0),
            "rqye": row.get("RQYE", 0),
            "rqmcl": row.get("RQMCL", 0),
            "rqchl": row.get("RQCHL", 0),
            "rzrqye": row.get("RZRQYE", 0),
        }
        for row in rows
    ]


def holder_num_change(code: str, page_size: int = 10) -> list[dict[str, Any]]:
    code = normalize_code(code)
    rows = eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="END_DATE",
        sort_types="-1",
    )
    return [
        {
            "date": str(row.get("END_DATE", ""))[:10],
            "holder_num": row.get("HOLDER_NUM", 0),
            "change_num": row.get("HOLDER_NUM_CHANGE", 0),
            "change_ratio": row.get("HOLDER_NUM_RATIO", 0),
            "avg_shares": row.get("AVG_FREE_SHARES", 0),
        }
        for row in rows
    ]


def dividend_history(code: str, page_size: int = 20) -> list[dict[str, Any]]:
    code = normalize_code(code)
    rows = eastmoney_datacenter(
        "RPT_SHAREBONUS_DET",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="EX_DIVIDEND_DATE",
        sort_types="-1",
    )
    return [
        {
            "date": str(row.get("EX_DIVIDEND_DATE", ""))[:10],
            "bonus_rmb": row.get("PRETAX_BONUS_RMB", 0),
            "transfer_ratio": row.get("TRANSFER_RATIO", 0),
            "bonus_ratio": row.get("BONUS_RATIO", 0),
            "plan": row.get("ASSIGN_PROGRESS", ""),
        }
        for row in rows
    ]


def sina_financial_report(code: str, report_type: str = "lrb", num: int = 8) -> list[dict[str, Any]]:
    code = normalize_code(code)
    if report_type not in {"fzb", "lrb", "llb"}:
        raise ValueError("report_type must be one of: fzb, lrb, llb")
    url = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
    params = {
        "paperCode": f"{market_prefix(code)}{code}",
        "source": report_type,
        "type": "0",
        "page": "1",
        "num": str(num),
    }
    try:
        response = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=15)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"Sina financial report request failed: {exc}") from exc
    report_list = (response.json().get("result") or {}).get("data", {}).get("report_list", {}) or {}
    rows: list[dict[str, Any]] = []
    for period in sorted(report_list.keys(), reverse=True)[:num]:
        item = report_list[period]
        record: dict[str, Any] = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for entry in item.get("data", []) or []:
            title = entry.get("item_title", "")
            if not title or entry.get("item_value") is None:
                continue
            record[title] = entry.get("item_value")
            tongbi = entry.get("item_tongbi")
            if tongbi not in (None, ""):
                record[f"{title}_同比"] = tongbi
        rows.append(record)
    return rows


def _cninfo_ts_to_date(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d")
    return str(value)[:10] if value else ""


def _cninfo_orgid(code: str) -> str:
    code = normalize_code(code)
    global _CNINFO_ORGID_MAP
    if not _CNINFO_ORGID_MAP:
        try:
            response = requests.get(
                "http://www.cninfo.com.cn/new/data/szse_stock.json",
                headers={"User-Agent": UA},
                timeout=15,
            )
            _CNINFO_ORGID_MAP = {
                stock["code"]: stock["orgId"]
                for stock in response.json().get("stockList", [])
                if "code" in stock and "orgId" in stock
            }
        except Exception:
            _CNINFO_ORGID_MAP = {}
    org_id = _CNINFO_ORGID_MAP.get(code)
    if org_id:
        return org_id
    if code.startswith("6"):
        return f"gssh0{code}"
    if code.startswith(("8", "4")):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def cninfo_announcements(code: str, page_size: int = 30) -> list[dict[str, Any]]:
    code = normalize_code(code)
    payload = {
        "stock": f"{code},{_cninfo_orgid(code)}",
        "tabName": "fulltext",
        "pageSize": str(page_size),
        "pageNum": "1",
        "column": "",
        "category": "",
        "plate": "",
        "seDate": "",
        "searchkey": "",
        "secid": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.cninfo.com.cn/new/disclosure",
        "Origin": "https://www.cninfo.com.cn",
    }
    try:
        response = requests.post(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data=payload,
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"CNINFO announcement request failed: {exc}") from exc
    rows = []
    for item in response.json().get("announcements", []) or []:
        rows.append(
            {
                "title": re.sub(r"<[^>]+>", "", item.get("announcementTitle", "")),
                "type": item.get("announcementTypeName", ""),
                "date": _cninfo_ts_to_date(item.get("announcementTime")),
                "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
            }
        )
    return rows


FETCHERS: dict[str, tuple[Callable[..., Any], SourceMeta]] = {
    "quote": (lambda code, **_: tencent_quote([code]).get(normalize_code(code), {}), SourceMeta("腾讯财经", "qt.gtimg.cn/q")),
    "stock-info": (
        lambda code, **_: eastmoney_stock_info(code),
        SourceMeta("东方财富", "push2.eastmoney.com/api/qt/stock/get"),
    ),
    "reports": (
        lambda code, max_pages=2, **_: eastmoney_reports(code, max_pages=max_pages),
        SourceMeta("东方财富", "reportapi.eastmoney.com/report/list", kind="research_report"),
    ),
    "industry-reports": (
        lambda code, industry_code="*", max_pages=2, **_: eastmoney_industry_reports(industry_code, max_pages=max_pages),
        SourceMeta("东方财富", "reportapi.eastmoney.com/report/list?qType=1", kind="research_report"),
    ),
    "concepts": (
        lambda code, **_: eastmoney_concept_blocks(code),
        SourceMeta("东方财富", "push2.eastmoney.com/api/qt/slist/get"),
    ),
    "kline-ma": (
        lambda code, start_time="", **_: baidu_kline_with_ma(code, start_time=start_time),
        SourceMeta("百度股市通", "finance.pae.baidu.com/selfselect/getstockquotation"),
    ),
    "fund-flow": (
        lambda code, **_: stock_fund_flow_120d(code),
        SourceMeta("东方财富", "push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"),
    ),
    "fund-flow-minute": (
        lambda code, **_: eastmoney_fund_flow_minute(code),
        SourceMeta("东方财富", "push2.eastmoney.com/api/qt/stock/fflow/kline/get"),
    ),
    "margin": (
        lambda code, page_size=30, **_: margin_trading(code, page_size=page_size),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPTA_WEB_RZRQ_GGMX"),
    ),
    "block-trade": (
        lambda code, page_size=30, **_: block_trade(code, page_size=page_size),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_DATA_BLOCKTRADE"),
    ),
    "holders": (
        lambda code, page_size=30, **_: holder_num_change(code, page_size=page_size),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_HOLDERNUMLATEST"),
    ),
    "dividends": (
        lambda code, page_size=30, **_: dividend_history(code, page_size=page_size),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_SHAREBONUS_DET"),
    ),
    "dragon-tiger": (
        lambda code, trade_date, **_: dragon_tiger_board(code, trade_date=trade_date),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_DAILYBILLBOARD_DETAILSNEW"),
    ),
    "daily-dragon-tiger": (
        lambda code, trade_date, **_: daily_dragon_tiger(trade_date=trade_date),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_DAILYBILLBOARD_DETAILSNEW"),
    ),
    "lockup": (
        lambda code, trade_date, **_: lockup_expiry(code, trade_date=trade_date),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_LIFT_STAGE"),
    ),
    "industry-comparison": (
        lambda code, page_size=20, **_: industry_comparison(top_n=page_size),
        SourceMeta("东方财富", "push2.eastmoney.com/api/qt/clist/get"),
    ),
    "ths-hot": (
        lambda code, trade_date, **_: ths_hot_reason(trade_date),
        SourceMeta("同花顺", "zx.10jqka.com.cn/event/api/getharden", evidence_level="交叉印证"),
    ),
    "northbound": (
        lambda code, **_: hsgt_realtime(),
        SourceMeta("同花顺", "data.hexin.cn/market/hsgtApi/method/dayChart", evidence_level="交叉印证"),
    ),
    "stock-news": (
        lambda code, page_size=30, **_: eastmoney_stock_news(code, page_size=page_size),
        SourceMeta("东方财富", "search-api-web.eastmoney.com/search/jsonp", evidence_level="交叉印证", kind="news"),
    ),
    "global-news": (
        lambda code, page_size=50, **_: eastmoney_global_news(page_size=page_size),
        SourceMeta("东方财富", "np-weblist.eastmoney.com/comm/web/getFastNewsList", evidence_level="交叉印证", kind="news"),
    ),
    "financials": (
        lambda code, report_type="lrb", financial_periods=8, **_: sina_financial_report(code, report_type, financial_periods),
        SourceMeta("新浪财经", "quotes.sina.cn/CompanyFinanceService.getFinanceReport2022", kind="financial_statement"),
    ),
    "announcements": (
        lambda code, page_size=30, **_: cninfo_announcements(code, page_size=page_size),
        SourceMeta("巨潮资讯", "cninfo.com.cn/new/hisAnnouncement/query", kind="filing"),
    ),
}

DEFAULT_INCLUDE = ["quote", "stock-info", "announcements", "reports", "financials"]


def fetch_snapshot(
    code: str,
    include: list[str] | None = None,
    *,
    max_pages: int = 2,
    page_size: int = 30,
    report_type: str = "lrb",
    financial_periods: int = 8,
    industry_code: str = "*",
    trade_date: str | None = None,
    download_report_pdfs: bool = False,
    pdf_dir: str | Path = "./reports/downloaded_research",
    pdf_limit: int = 3,
) -> dict[str, Any]:
    """Fetch an explicit A-share data snapshot with provenance per dataset."""
    normalized = normalize_code(code)
    selected = include or DEFAULT_INCLUDE
    if "all" in selected:
        selected = list(FETCHERS.keys())
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    snapshot: dict[str, Any] = {
        "ticker": canonical_ticker(normalized),
        "code": normalized,
        "market": exchange_suffix(normalized),
        "fetched_at": now_iso(),
        "policy": {
            "default_single_agent": True,
            "full_source_scan": False,
            "note": "Only explicitly requested datasets were fetched.",
        },
        "datasets": {},
    }
    for name in selected:
        if name not in FETCHERS:
            raise ValueError(f"unknown dataset: {name}")
        fetcher, meta = FETCHERS[name]
        try:
            data = fetcher(
                normalized,
                max_pages=max_pages,
                page_size=page_size,
                report_type=report_type,
                financial_periods=financial_periods,
                industry_code=industry_code,
                trade_date=trade_date,
            )
            status = "ok" if data not in ({}, [], None) else "empty"
            snapshot["datasets"][name] = source_record(meta, data, status=status)
            if download_report_pdfs and name in {"reports", "industry-reports"} and isinstance(data, list):
                paths: list[str] = []
                errors: list[dict[str, str]] = []
                for idx, record in enumerate(data[: max(0, pdf_limit)], start=1):
                    if not isinstance(record, dict):
                        errors.append({"index": str(idx), "error": "record is not an object"})
                        continue
                    try:
                        path = download_pdf(record, pdf_dir)
                    except DataSourceError as exc:
                        errors.append({"index": str(idx), "title": str(record.get("title", ""))[:80], "error": str(exc)})
                        continue
                    except Exception as exc:
                        errors.append(
                            {
                                "index": str(idx),
                                "title": str(record.get("title", ""))[:80],
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
                        continue
                    if path:
                        paths.append(path)
                    else:
                        errors.append({"index": str(idx), "title": str(record.get("title", ""))[:80], "error": "PDF not available"})
                snapshot["datasets"][name]["downloaded_pdfs"] = paths
                if errors:
                    snapshot["datasets"][name]["pdf_download_errors"] = errors
        except DataSourceError as exc:
            snapshot["datasets"][name] = source_record(meta, None, status="unavailable", error=str(exc))
        except Exception as exc:
            snapshot["datasets"][name] = source_record(
                meta,
                None,
                status="unavailable",
                error=f"{type(exc).__name__}: {exc}",
            )
    return snapshot


def parse_include(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or DEFAULT_INCLUDE


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch explicit A-share public data with provenance metadata.")
    parser.add_argument("ticker", nargs="?", help="A-share ticker, e.g. 600519, 600519.SH, SZ000001")
    parser.add_argument(
        "--include",
        default=",".join(DEFAULT_INCLUDE),
        help="Comma list of datasets; use --list-datasets to see all names.",
    )
    parser.add_argument("--list-datasets", action="store_true", help="List available dataset names and exit")
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--report-type", choices=["lrb", "fzb", "llb"], default="lrb")
    parser.add_argument("--financial-periods", type=int, default=8)
    parser.add_argument("--industry-code", default="*")
    parser.add_argument("--trade-date", help="YYYY-MM-DD for daily event datasets; defaults to today")
    parser.add_argument("--download-report-pdfs", action="store_true", help="Download PDFs for reports/industry-reports")
    parser.add_argument("--pdf-dir", type=Path, default=Path("./reports/downloaded_research"))
    parser.add_argument("--pdf-limit", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.list_datasets:
        for name in sorted(FETCHERS):
            print(name)
        return 0
    if not args.ticker:
        parser.error("ticker is required unless --list-datasets is used")
    snapshot = fetch_snapshot(
        args.ticker,
        parse_include(args.include),
        max_pages=args.max_pages,
        page_size=args.page_size,
        report_type=args.report_type,
        financial_periods=args.financial_periods,
        industry_code=args.industry_code,
        trade_date=args.trade_date,
        download_report_pdfs=args.download_report_pdfs,
        pdf_dir=args.pdf_dir,
        pdf_limit=args.pdf_limit,
    )
    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
