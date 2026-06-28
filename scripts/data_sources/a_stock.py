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
import hashlib
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
DEFAULT_ARTIFACT_ROOT = Path("./reports/runs")
CHINA_TZ = timezone(timedelta(hours=8))

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
    research_role: str = "company_truth"
    usage: str = ""

    def as_dict(self) -> dict[str, str]:
        record = {
            "source": self.source,
            "endpoint": self.endpoint,
            "evidence_level": self.evidence_level,
            "kind": self.kind,
            "status": self.status,
            "research_role": self.research_role,
        }
        if self.usage:
            record["usage"] = self.usage
        return record


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


def normalize_trade_date(value: str | None, *, style: str = "dash") -> str:
    """Normalize CLI trade dates into endpoint-specific formats."""
    raw = (value or datetime.now().strftime("%Y-%m-%d")).strip()
    if re.fullmatch(r"\d{8}", raw):
        dt = datetime.strptime(raw, "%Y%m%d")
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dt = datetime.strptime(raw, "%Y-%m-%d")
    else:
        raise ValueError(f"invalid trade date: {value!r}; use YYYY-MM-DD or YYYYMMDD")
    if style == "compact":
        return dt.strftime("%Y%m%d")
    if style == "dash":
        return dt.strftime("%Y-%m-%d")
    raise ValueError(f"unknown trade date style: {style!r}")


def _fmt_zt_time(t: Any) -> str:
    """Format Eastmoney HHMM/HHMMSS integer times."""
    if t in (None, "", 0, "0"):
        return ""
    try:
        text = str(int(t))
    except (TypeError, ValueError):
        return str(t)
    if len(text) <= 4:
        text = text.zfill(4)
        return f"{text[:2]}:{text[2:]}"
    text = text.zfill(6)
    return f"{text[:2]}:{text[2:4]}:{text[4:6]}"


def _fmt_epoch_time(t: Any) -> str:
    if t in (None, "", 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(t), CHINA_TZ).strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(t)


def _safe_filename_part(value: Any, limit: int = 80, default: str = "unknown") -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip("._")
    return (text[:limit] or default)


def make_run_id(code: str, topic: str = "") -> str:
    topic_part = _safe_filename_part(topic, limit=32, default="")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [stamp, normalize_code(code)]
    if topic_part:
        parts.append(topic_part)
    return "_".join(parts)


def init_artifact_manifest(
    code: str,
    *,
    artifact_root: str | Path = DEFAULT_ARTIFACT_ROOT,
    run_id: str | None = None,
    topic: str = "",
) -> dict[str, Any]:
    normalized = normalize_code(code)
    rid = run_id or make_run_id(normalized, topic=topic)
    artifact_root_path = Path(artifact_root)
    run_dir = artifact_root_path if artifact_root_path.name == rid else artifact_root_path / rid
    pdf_dir = run_dir / "downloaded_pdfs"
    run_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    ticker = canonical_ticker(normalized)
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if isinstance(manifest, dict):
            manifest.setdefault("run_id", rid)
            manifest.setdefault("created_at", now_iso())
            manifest["artifact_dir"] = str(run_dir)
            manifest["pdf_dir"] = str(pdf_dir)
            manifest["manifest_path"] = str(manifest_path)
            sources = manifest.get("sources")
            if not isinstance(sources, list):
                manifest["sources"] = []
            tickers = manifest.get("tickers")
            if not isinstance(tickers, list):
                tickers = []
                manifest["tickers"] = tickers
            existing_ticker = manifest.get("ticker")
            if isinstance(existing_ticker, str) and existing_ticker and existing_ticker not in tickers:
                tickers.append(existing_ticker)
            if ticker not in tickers:
                tickers.append(ticker)
            if topic and not manifest.get("topic"):
                manifest["topic"] = topic
            manifest["updated_at"] = now_iso()
            return manifest
    return {
        "run_id": rid,
        "created_at": now_iso(),
        "ticker": ticker,
        "tickers": [ticker],
        "code": normalized,
        "topic": topic,
        "artifact_dir": str(run_dir),
        "pdf_dir": str(pdf_dir),
        "manifest_path": str(manifest_path),
        "sources": [],
    }


def write_artifact_manifest(manifest: dict[str, Any]) -> None:
    path = Path(str(manifest["manifest_path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = now_iso()
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_manifest_source(manifest: dict[str, Any], entry: dict[str, Any]) -> None:
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        sources = []
        manifest["sources"] = sources
    key = (entry.get("dataset"), entry.get("infoCode"))
    for existing in sources:
        if isinstance(existing, dict) and (existing.get("dataset"), existing.get("infoCode")) == key:
            if entry.get("linked_at"):
                existing["linked_at"] = entry["linked_at"]
            if entry.get("path"):
                existing.setdefault("path", entry["path"])
            if entry.get("sha256"):
                existing.setdefault("sha256", entry["sha256"])
            if entry.get("downloaded_at"):
                existing.setdefault("downloaded_at", entry["downloaded_at"])
            return
    sources.append(entry)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_like_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"%PDF"
    except OSError:
        return False


def _pdf_source_url(info_code: str) -> str:
    return PDF_TPL.format(info_code=info_code)


def _pdf_filename(record: dict[str, Any]) -> str:
    info_code = _safe_filename_part(record.get("infoCode"), limit=32)
    date = _safe_filename_part((record.get("publishDate") or "")[:10], limit=16, default="no_date")
    org = _safe_filename_part(record.get("orgSName") or record.get("orgName"), limit=24)
    title = _safe_filename_part(record.get("title"), limit=72)
    return f"{date}_{org}_{info_code}_{title}.pdf"


def _cache_is_fresh(sidecar: Path, cache_days: int) -> tuple[bool, str]:
    if cache_days <= 0 or not sidecar.exists():
        return False, ""
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        downloaded_at = str(payload.get("downloaded_at", ""))
        dt = datetime.fromisoformat(downloaded_at)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False, ""
    age = datetime.now(timezone.utc).astimezone() - dt.astimezone()
    return age.total_seconds() <= cache_days * 86400, downloaded_at


def download_pdf_artifact(
    record: dict[str, Any],
    target_dir: str | Path,
    *,
    cache_dir: str | Path | None = None,
    cache_days: int = 1,
    run_id: str = "",
    dataset: str = "",
) -> dict[str, Any] | None:
    info_code = str(record.get("infoCode") or "").strip()
    if not info_code:
        return None
    target_root = Path(target_dir)
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / _pdf_filename(record)
    cache_root = Path(cache_dir) if cache_dir else None
    cache_path = cache_root / f"{_safe_filename_part(info_code, limit=48)}.pdf" if cache_root else None
    sidecar = cache_root / f"{_safe_filename_part(info_code, limit=48)}.json" if cache_root else None

    reused_from_cache = False
    downloaded_at = ""
    content_sha = ""
    if cache_path and sidecar:
        fresh, downloaded_at = _cache_is_fresh(sidecar, cache_days)
        if fresh and cache_path.exists() and _looks_like_pdf(cache_path):
            target.write_bytes(cache_path.read_bytes())
            content_sha = _sha256_file(target)
            reused_from_cache = True

    if not reused_from_cache:
        response = em_get(_pdf_source_url(info_code), headers={"Referer": "https://data.eastmoney.com/"}, timeout=60)
        content = response.content
        if response.status_code != 200 or len(content) < 1024 or not content.startswith(b"%PDF"):
            return None
        content_sha = _sha256_bytes(content)
        target.write_bytes(content)
        downloaded_at = now_iso()
        if cache_path and sidecar:
            cache_root.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(content)
            sidecar.write_text(
                json.dumps(
                    {
                        "infoCode": info_code,
                        "source_url": _pdf_source_url(info_code),
                        "sha256": content_sha,
                        "downloaded_at": downloaded_at,
                        "title": record.get("title", ""),
                        "publisher": record.get("orgSName") or record.get("orgName") or "",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    return {
        "run_id": run_id,
        "dataset": dataset,
        "type": "research_report_pdf",
        "infoCode": info_code,
        "title": record.get("title", ""),
        "publisher": record.get("orgSName") or record.get("orgName") or "",
        "published": (record.get("publishDate") or "")[:10],
        "source_url": _pdf_source_url(info_code),
        "path": str(target),
        "sha256": content_sha,
        "downloaded_at": downloaded_at,
        "linked_at": now_iso(),
        "reused_from_cache": reused_from_cache,
        "cache_path": str(cache_path) if cache_path else "",
        "evidence_level": "待核验/线索级",
        "research_role": "valuation_setup" if dataset == "reports" else "thesis_leads",
        "claim_scope": "report_opinion_only",
    }


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


def em_request(
    method: str,
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
        response = EM_SESSION.request(method, url, params=params, headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"Eastmoney request failed: {exc}") from exc
    finally:
        _em_last_call[0] = time.time()
    if response.status_code in {403, 429}:
        raise DataSourceRateLimitError(f"Eastmoney HTTP {response.status_code}")
    return response


def em_get(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    **kwargs: Any,
) -> requests.Response:
    return em_request("GET", url, params=params, headers=headers, timeout=timeout, **kwargs)


def em_post(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    **kwargs: Any,
) -> requests.Response:
    return em_request("POST", url, params=params, headers=headers, timeout=timeout, **kwargs)


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
    """Compatibility wrapper for one-off PDF downloads without cross-run cache."""
    entry = download_pdf_artifact(record, target_dir, cache_dir=None, cache_days=0)
    return str(entry["path"]) if entry else None


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



# ---------------------------------------------------------------------------
# 研报与一致预期扩展 fetcher（adapted from a-stock-data v3.2.5）
# ---------------------------------------------------------------------------

def ths_eps_forecast(code: str) -> list[dict[str, Any]]:
    """同花顺机构一致预期 EPS。直连 basic.10jqka.com.cn 解析 HTML 表格。

    返回 list，每条: {year, brokers, eps_min, eps_mean, eps_max}
    `eps_mean` 即"机构一致预期 EPS"；brokers<3 视为弱一致预期。
    """
    from html.parser import HTMLParser
    from html import unescape

    code = normalize_code(code)
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    headers = {
        "User-Agent": UA,
        "Referer": "https://basic.10jqka.com.cn/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"THS EPS forecast request failed: {exc}") from exc
    response.encoding = "gbk"

    class _TableParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.tables: list[list[list[str]]] = []
            self._current: list[list[str]] | None = None
            self._row: list[str] | None = None
            self._cell: list[str] | None = None
            self._in_cell = False

        def handle_starttag(self, tag: str, attrs):
            if tag == "tr" and self._current is not None:
                self._row = []
            elif tag in ("td", "th") and self._row is not None:
                self._cell = []
                self._in_cell = True
            elif tag == "table":
                self._current = []

        def handle_endtag(self, tag: str):
            if tag == "table" and self._current is not None:
                self.tables.append(self._current)
                self._current = None
            elif tag == "tr" and self._row is not None and self._current is not None:
                self._current.append(self._row)
                self._row = None
            elif tag in ("td", "th") and self._row is not None and self._cell is not None:
                self._row.append("".join(self._cell).strip())
                self._cell = None
                self._in_cell = False

        def handle_data(self, data: str):
            if self._in_cell and self._cell is not None:
                self._cell.append(unescape(data))

    parser = _TableParser()
    parser.feed(response.text)
    if not parser.tables:
        raise NoUsableDataError("同花顺一致预期", code, "no table parsed")
    target = None
    for table in parser.tables:
        for row in table:
            joined = "".join(row)
            if "每股收益" in joined and ("均值" in joined or "预测机构数" in joined):
                target = table
                break
        if target is not None:
            break
    if target is None:
        target = parser.tables[0]
    if not target:
        return []
    header = [c.replace("\n", "").strip() for c in target[0]]
    out: list[dict[str, Any]] = []
    for row in target[1:]:
        record: dict[str, Any] = {}
        for idx, col in enumerate(row):
            key = header[idx] if idx < len(header) else f"col{idx}"
            value = col.strip()
            if "年度" in key or "报告期" in key:
                record["year"] = value
            elif "预测机构数" in key or "机构数" in key:
                record["brokers"] = _to_float(value, 0)
            elif "最小值" in key or "最小" in key:
                record["eps_min"] = _to_float(value, 0.0)
            elif "最大值" in key or "最大" in key:
                record["eps_max"] = _to_float(value, 0.0)
            elif "均值" in key:
                record["eps_mean"] = _to_float(value, 0.0)
            else:
                record[key] = value
        if "eps_mean" in record:
            record["research_role"] = "valuation_setup"
            record["row_evidence_level"] = "交叉印证"
            record["claim_scope"] = "consensus_forecast_only"
            out.append(record)
    if not out:
        raise NoUsableDataError("同花顺一致预期", code, "no eps_mean row parsed")
    return out


def cninfo_irm(
    code: str,
    page_size: int = 30,
    page_num: int = 1,
    *,
    answered_only: bool = False,
) -> list[dict[str, Any]]:
    """巨潮互动易问答（沪深北全市场）。两阶段请求：

    1) POST /newircs/index/queryKeyboardInfo 用 code 取 orgId
    2) POST /newircs/company/question 拿问答列表

    返回 list，每条区分公司已答复与投资者未答复提问，避免把线索当成公司口径。
    """
    code = normalize_code(code)
    headers = {"User-Agent": UA}
    try:
        first = requests.post(
            "https://irm.cninfo.com.cn/newircs/index/queryKeyboardInfo",
            data={"keyWord": code},
            headers=headers,
            timeout=10,
        )
        d1 = first.json().get("data") or []
        if not d1:
            raise NoUsableDataError("巨潮互动易", code, "no orgId matched")
        org_id = d1[0].get("secid")
        params = {
            "_t": 1,
            "stockcode": code,
            "orgId": org_id,
            "pageSize": page_size,
            "pageNum": page_num,
            "keyWord": "",
            "startDay": "",
            "endDay": "",
        }
        second = requests.post(
            "https://irm.cninfo.com.cn/newircs/company/question",
            params=params,
            headers=headers,
            timeout=10,
        )
        rows = second.json().get("rows") or []
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"cninfo irm request failed: {exc}") from exc
    except ValueError as exc:
        raise DataSourceUnavailableError(f"cninfo irm json parse failed: {exc}") from exc
    out: list[dict[str, Any]] = []
    for item in rows:
        pub_ms = item.get("pubDate")
        ask_time = ""
        if isinstance(pub_ms, (int, float)) and pub_ms > 0:
            ask_time = datetime.fromtimestamp(pub_ms / 1000, CHINA_TZ).isoformat(timespec="seconds")
        answer = item.get("attachedContent")
        answerer = item.get("attachedAuthor")
        answered = bool(str(answer or "").strip() and str(answerer or "").strip())
        if answered_only and not answered:
            continue
        out.append(
            {
                "code": item.get("stockCode"),
                "company": item.get("companyShortName"),
                "question": item.get("mainContent"),
                "answer": answer,
                "answerer": answerer,
                "ask_time": ask_time,
                "answered": answered,
                "row_evidence_level": "直接证据" if answered else "待核验/线索级",
                "claim_scope": "company_answer" if answered else "investor_question_only",
                "research_role": "company_truth" if answered else "thesis_leads",
            }
        )
    return out


def _em_zt_api(endpoint: str, sort: str, date: str) -> list[dict[str, Any]]:
    """涨停/炸板/跌停/昨涨停四个池子的内部入口，date=YYYYMMDD 交易日。"""
    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": 0,
        "Pagesize": 200,
        "sort": sort,
        "date": normalize_trade_date(date, style="compact"),
    }
    try:
        response = em_get(url, params=params, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=10)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"EM {endpoint} failed: {exc}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise DataSourceUnavailableError(f"EM {endpoint} json parse failed: {exc}") from exc
    if payload.get("rc") != 0:
        raise NoUsableDataError("东方财富涨跌停池", date, f"{endpoint} rc={payload.get('rc')}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise NoUsableDataError("东方财富涨跌停池", date, f"{endpoint} missing data")
    pool = data.get("pool")
    return pool if isinstance(pool, list) else []


def em_zt_pool(date: str) -> list[dict[str, Any]]:
    """涨停池。date=YYYYMMDD（交易日）。返回 code/name/price/pct/amount_yi/float_cap_yi/turnover_pct/limit_days/industry/first_seal/last_seal/seal_fund_yi/break_times。"""
    out: list[dict[str, Any]] = []
    for p in _em_zt_api("getTopicZTPool", "fbt:asc", date):
        out.append({
            "code": p.get("c"),
            "name": p.get("n"),
            "price": p.get("p", 0) / 1000,
            "pct": round(p.get("zdp", 0) or 0, 2),
            "amount_yi": round((p.get("amount") or 0) / 1e8, 2),
            "float_cap_yi": round((p.get("ltsz") or 0) / 1e8, 2),
            "turnover_pct": round(p.get("hs", 0) or 0, 2),
            "limit_days": p.get("lbc"),
            "first_seal": _fmt_zt_time(p.get("fbt")),
            "last_seal": _fmt_zt_time(p.get("lbt")),
            "seal_fund_yi": round((p.get("fund") or 0) / 1e8, 2),
            "break_times": p.get("zbc"),
            "industry": p.get("hybk", ""),
            "research_role": "market_temperature",
            "row_evidence_level": "待核验/线索级",
            "claim_scope": "market_temperature_only",
        })
    return out


def em_zb_pool(date: str) -> list[dict[str, Any]]:
    """炸板池（涨停后开板）。"""
    out: list[dict[str, Any]] = []
    for p in _em_zt_api("getTopicZBPool", "fbt:asc", date):
        out.append({
            "code": p.get("c"),
            "name": p.get("n"),
            "price": p.get("p", 0) / 1000,
            "limit_price": p.get("ztp", 0) / 1000,
            "pct": round(p.get("zdp", 0) or 0, 2),
            "turnover_pct": round(p.get("hs", 0) or 0, 2),
            "first_seal": _fmt_zt_time(p.get("fbt")),
            "break_times": p.get("zbc"),
            "amplitude_pct": round(p.get("zf", 0) or 0, 2),
            "speed_pct": round(p.get("zs", 0) or 0, 2),
            "industry": p.get("hybk", ""),
            "research_role": "market_temperature",
            "row_evidence_level": "待核验/线索级",
            "claim_scope": "market_temperature_only",
        })
    return out


def em_dt_pool(date: str) -> list[dict[str, Any]]:
    """跌停池。"""
    out: list[dict[str, Any]] = []
    for p in _em_zt_api("getTopicDTPool", "fund:asc", date):
        out.append({
            "code": p.get("c"),
            "name": p.get("n"),
            "price": p.get("p", 0) / 1000,
            "pct": round(p.get("zdp", 0) or 0, 2),
            "turnover_pct": round(p.get("hs", 0) or 0, 2),
            "pe": p.get("pe"),
            "seal_fund_yi": round((p.get("fund") or 0) / 1e8, 2),
            "last_seal": _fmt_zt_time(p.get("lbt")),
            "dt_days": p.get("days"),
            "open_times": p.get("oc"),
            "industry": p.get("hybk", ""),
            "research_role": "market_temperature",
            "row_evidence_level": "待核验/线索级",
            "claim_scope": "market_temperature_only",
        })
    return out


def em_yzt_pool(date: str) -> list[dict[str, Any]]:
    """昨日涨停今表现（赚钱效应/晋级率）。"""
    out: list[dict[str, Any]] = []
    for p in _em_zt_api("getYesterdayZTPool", "zs:desc", date):
        out.append({
            "code": p.get("c"),
            "name": p.get("n"),
            "price": p.get("p", 0) / 1000,
            "pct_today": round(p.get("zdp", 0) or 0, 2),
            "turnover_pct": round(p.get("hs", 0) or 0, 2),
            "amplitude_pct": round(p.get("zf", 0) or 0, 2),
            "speed_pct": round(p.get("zs", 0) or 0, 2),
            "y_first_seal": _fmt_zt_time(p.get("yfbt")),
            "y_limit_days": p.get("ylbc"),
            "industry": p.get("hybk", ""),
            "research_role": "market_temperature",
            "row_evidence_level": "待核验/线索级",
            "claim_scope": "market_temperature_only",
        })
    return out


def ths_limit_up_pool(date: str) -> list[dict[str, Any]]:
    """同花顺涨停揭秘：涨停原因题材 + 板型 + 封板成功率。date=YYYYMMDD。"""
    url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
    params = {
        "page": 1,
        "limit": 200,
        "field": "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
        "filter": "HS,GEM2STAR",
        "order_field": "330324",
        "order_type": "0",
        "date": normalize_trade_date(date, style="compact"),
    }
    try:
        response = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=10)
    except requests.RequestException as exc:
        raise DataSourceUnavailableError(f"THS limit-up pool failed: {exc}") from exc
    try:
        payload = response.json()
        if payload.get("status_code") not in (0, "0", None):
            raise NoUsableDataError("同花顺涨停池", date, f"status_code={payload.get('status_code')}")
        info = (payload.get("data") or {}).get("info", [])
    except ValueError as exc:
        raise DataSourceUnavailableError(f"THS limit-up pool json parse failed: {exc}") from exc
    out: list[dict[str, Any]] = []
    for p in info:
        out.append({
            "code": p.get("code"),
            "name": p.get("name"),
            "price": p.get("latest"),
            "pct": round(_to_float(p.get("change_rate")), 2),
            "reason": p.get("reason_type"),
            "board_type": p.get("limit_up_type"),
            "seal_success_rate": round(_to_float(p.get("limit_up_suc_rate")), 4),
            "break_times": p.get("open_num") or 0,
            "seal_amount_yi": round((p.get("order_amount") or 0) / 1e8, 2),
            "float_cap_yi": round((p.get("currency_value") or 0) / 1e8, 2),
            "turnover_pct": round(_to_float(p.get("turnover_rate")), 2),
            "high_days": p.get("high_days"),
            "first_seal": _fmt_epoch_time(p.get("first_limit_up_time")),
            "last_seal": _fmt_epoch_time(p.get("last_limit_up_time")),
            "is_again": bool(p.get("is_again_limit")),
            "market_type": p.get("market_type"),
            "research_role": "market_temperature",
            "row_evidence_level": "待核验/线索级",
            "claim_scope": "market_temperature_only",
        })
    return out


def em_hot_rank(top: int = 50) -> list[dict[str, Any]]:
    """东财人气榜 TOP。返回 rank/code/name/price/pct/rank_chg。"""
    body = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "pageNo": 1,
        "pageSize": top,
    }
    try:
        response = em_post(
            "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
            json=body,
            headers={"User-Agent": UA},
            timeout=10,
        )
        data = response.json().get("data") or []
        if not data:
            return []
        secids = []
        for it in data:
            sc = str(it.get("sc") or "")
            if len(sc) >= 8:
                secids.append(("0." if sc.startswith("SZ") else "1.") + sc[2:])
        if not secids:
            return []
        u = em_get(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            params={"ut": "f057cbcbce2a86e2866ab8877db1d059", "fltt": 2, "invt": 2,
                    "fields": "f14,f3,f12,f2", "secids": ",".join(secids)},
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=10,
        )
        diff = (u.json().get("data") or {}).get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        nm = {x.get("f12"): (x.get("f14"), x.get("f2"), x.get("f3")) for x in diff}
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise DataSourceUnavailableError(f"EM hot rank failed: {exc}") from exc
    out: list[dict[str, Any]] = []
    for it in data:
        sc = str(it.get("sc") or "")
        if len(sc) < 8:
            continue
        code = sc[2:]
        name, price, pct = nm.get(code, ("", None, None))
        out.append({
            "rank": it.get("rk"),
            "code": code,
            "name": name,
            "price": price,
            "pct": pct,
            "rank_chg": it.get("hisRc"),
            "research_role": "market_temperature",
            "row_evidence_level": "待核验/线索级",
            "claim_scope": "market_attention_only",
        })
    return out


def ths_hot_list(period: str = "hour") -> list[dict[str, Any]]:
    """同花顺热榜。period: hour|day。返回 rank/code/name/heat/pct/rank_chg/concepts/tag。"""
    try:
        response = requests.get(
            "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock",
            params={"stock_type": "a", "type": period, "list_type": "normal"},
            headers={"User-Agent": UA},
            timeout=10,
        )
        lst = (response.json().get("data") or {}).get("stock_list") or []
    except (requests.RequestException, ValueError) as exc:
        raise DataSourceUnavailableError(f"THS hot list failed: {exc}") from exc
    out: list[dict[str, Any]] = []
    for it in lst:
        tag = it.get("tag") or {}
        out.append({
            "rank": it.get("order"),
            "code": it.get("code"),
            "name": it.get("name"),
            "heat": it.get("rate"),
            "pct": it.get("rise_and_fall"),
            "rank_chg": it.get("hot_rank_chg"),
            "concepts": tag.get("concept_tag") or [],
            "tag": tag.get("popularity_tag", ""),
            "research_role": "thesis_leads",
            "row_evidence_level": "待核验/线索级",
            "claim_scope": "market_attention_only",
        })
    return out


def em_hot_concept(code: str) -> list[dict[str, Any]]:
    """东财个股热门概念命中。返回 [{concept, bk, hit}] 按热度降序。"""
    code = normalize_code(code)
    prefix = "SH" if code.startswith(("6", "9")) else "SZ"
    body = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "srcSecurityCode": prefix + code,
    }
    try:
        response = em_post(
            "https://emappdata.eastmoney.com/stockrank/getHotStockRankList",
            json=body,
            headers={"User-Agent": UA},
            timeout=10,
        )
        data = response.json().get("data") or []
    except (requests.RequestException, ValueError) as exc:
        raise DataSourceUnavailableError(f"EM hot concept failed: {exc}") from exc
    return [
        {
            "concept": x.get("conceptName"),
            "bk": x.get("conceptId"),
            "hit": x.get("hitCount"),
            "research_role": "thesis_leads",
            "row_evidence_level": "待核验/线索级",
            "claim_scope": "concept_attribution_only",
        }
        for x in data
    ]


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
        return datetime.fromtimestamp(value / 1000, CHINA_TZ).strftime("%Y-%m-%d")
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
    "quote": (
        lambda code, **_: tencent_quote([code]).get(normalize_code(code), {}),
        SourceMeta("腾讯财经", "qt.gtimg.cn/q", research_role="valuation_setup", usage="价格和估值输入；不证明业务暴露。"),
    ),
    "stock-info": (
        lambda code, **_: eastmoney_stock_info(code),
        SourceMeta("东方财富", "push2.eastmoney.com/api/qt/stock/get", research_role="company_truth"),
    ),
    "reports": (
        lambda code, max_pages=2, **_: eastmoney_reports(code, max_pages=max_pages),
        SourceMeta(
            "东方财富",
            "reportapi.eastmoney.com/report/list",
            evidence_level="待核验/线索级",
            kind="research_report",
            research_role="valuation_setup",
            usage="券商观点和预测线索，不能替代公告/财报。",
        ),
    ),
    "industry-reports": (
        lambda code, industry_code="*", max_pages=2, **_: eastmoney_industry_reports(industry_code, max_pages=max_pages),
        SourceMeta(
            "东方财富",
            "reportapi.eastmoney.com/report/list?qType=1",
            evidence_level="待核验/线索级",
            kind="research_report",
            research_role="thesis_leads",
            usage="行业观点线索，需一手来源交叉验证。",
        ),
    ),
    "concepts": (
        lambda code, **_: eastmoney_concept_blocks(code),
        SourceMeta("东方财富", "push2.eastmoney.com/api/qt/slist/get", evidence_level="待核验/线索级", research_role="thesis_leads", usage="概念归属只能定位题材。"),
    ),
    "kline-ma": (
        lambda code, start_time="", **_: baidu_kline_with_ma(code, start_time=start_time),
        SourceMeta("百度股市通", "finance.pae.baidu.com/selfselect/getstockquotation", research_role="market_temperature", usage="价格位置辅助。"),
    ),
    "fund-flow": (
        lambda code, **_: stock_fund_flow_120d(code),
        SourceMeta("东方财富", "push2his.eastmoney.com/api/qt/stock/fflow/daykline/get", evidence_level="待核验/线索级", research_role="market_temperature"),
    ),
    "fund-flow-minute": (
        lambda code, **_: eastmoney_fund_flow_minute(code),
        SourceMeta("东方财富", "push2.eastmoney.com/api/qt/stock/fflow/kline/get", evidence_level="待核验/线索级", research_role="market_temperature"),
    ),
    "margin": (
        lambda code, page_size=30, **_: margin_trading(code, page_size=page_size),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPTA_WEB_RZRQ_GGMX", research_role="market_temperature"),
    ),
    "block-trade": (
        lambda code, page_size=30, **_: block_trade(code, page_size=page_size),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_DATA_BLOCKTRADE", evidence_level="待核验/线索级", research_role="market_temperature"),
    ),
    "holders": (
        lambda code, page_size=30, **_: holder_num_change(code, page_size=page_size),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_HOLDERNUMLATEST", research_role="valuation_setup"),
    ),
    "dividends": (
        lambda code, page_size=30, **_: dividend_history(code, page_size=page_size),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_SHAREBONUS_DET", research_role="valuation_setup"),
    ),
    "dragon-tiger": (
        lambda code, trade_date, **_: dragon_tiger_board(code, trade_date=normalize_trade_date(trade_date, style="dash")),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_DAILYBILLBOARD_DETAILSNEW", evidence_level="待核验/线索级", research_role="market_temperature"),
    ),
    "daily-dragon-tiger": (
        lambda code, trade_date, **_: daily_dragon_tiger(trade_date=normalize_trade_date(trade_date, style="dash")),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_DAILYBILLBOARD_DETAILSNEW", evidence_level="待核验/线索级", research_role="market_temperature"),
    ),
    "lockup": (
        lambda code, trade_date, **_: lockup_expiry(code, trade_date=normalize_trade_date(trade_date, style="dash")),
        SourceMeta("东方财富", "datacenter-web.eastmoney.com/RPT_LIFT_STAGE", research_role="valuation_setup"),
    ),
    "industry-comparison": (
        lambda code, page_size=20, **_: industry_comparison(top_n=page_size),
        SourceMeta("东方财富", "push2.eastmoney.com/api/qt/clist/get", evidence_level="待核验/线索级", research_role="market_temperature"),
    ),
    "ths-hot": (
        lambda code, trade_date, **_: ths_hot_reason(trade_date),
        SourceMeta("同花顺", "zx.10jqka.com.cn/event/api/getharden", evidence_level="待核验/线索级", research_role="thesis_leads", usage="强势题材线索，需公告/财报核验。"),
    ),
    "northbound": (
        lambda code, **_: hsgt_realtime(),
        SourceMeta("同花顺", "data.hexin.cn/market/hsgtApi/method/dayChart", evidence_level="待核验/线索级", research_role="market_temperature"),
    ),
    "stock-news": (
        lambda code, page_size=30, **_: eastmoney_stock_news(code, page_size=page_size),
        SourceMeta("东方财富", "search-api-web.eastmoney.com/search/jsonp", evidence_level="待核验/线索级", kind="news", research_role="thesis_leads", usage="新闻线索，需原始来源核验。"),
    ),
    "global-news": (
        lambda code, page_size=50, **_: eastmoney_global_news(page_size=page_size),
        SourceMeta("东方财富", "np-weblist.eastmoney.com/comm/web/getFastNewsList", evidence_level="待核验/线索级", kind="news", research_role="thesis_leads", usage="快讯线索，需原始来源核验。"),
    ),
    "financials": (
        lambda code, report_type="lrb", financial_periods=8, **_: sina_financial_report(code, report_type, financial_periods),
        SourceMeta("新浪财经", "quotes.sina.cn/CompanyFinanceService.getFinanceReport2022", kind="financial_statement", research_role="company_truth"),
    ),
    "announcements": (
        lambda code, page_size=30, **_: cninfo_announcements(code, page_size=page_size),
        SourceMeta("巨潮资讯", "cninfo.com.cn/new/hisAnnouncement/query", kind="filing", research_role="company_truth"),
    ),
    "ths-eps-forecast": (
        lambda code, **_: ths_eps_forecast(code),
        SourceMeta(
            "同花顺",
            "basic.10jqka.com.cn/new/{code}/worth.html",
            evidence_level="交叉印证",
            kind="consensus_eps",
            research_role="valuation_setup",
            usage="估值输入；不能替代公司业绩披露。",
        ),
    ),
    "irm": (
        lambda code, page_size=30, **_: cninfo_irm(code, page_size=page_size),
        SourceMeta(
            "巨潮互动易",
            "irm.cninfo.com.cn/newircs/company/question",
            evidence_level="待核验/线索级",
            kind="irm_qa",
            research_role="thesis_leads",
            usage="已回答内容可作公司口径；未回答提问只能作线索。",
        ),
    ),
    "answered-irm": (
        lambda code, page_size=30, **_: cninfo_irm(code, page_size=page_size, answered_only=True),
        SourceMeta(
            "巨潮互动易",
            "irm.cninfo.com.cn/newircs/company/question",
            kind="irm_qa",
            usage="只返回公司已答复问答，适合深度研报主证据库存。",
        ),
    ),
    "zt-pool": (
        lambda code, trade_date, **_: em_zt_pool(trade_date),
        SourceMeta("东方财富", "push2ex.eastmoney.com/getTopicZTPool", evidence_level="待核验/线索级", kind="limit_up", research_role="market_temperature", usage="只衡量交易温度，不证明瓶颈。"),
    ),
    "zb-pool": (
        lambda code, trade_date, **_: em_zb_pool(trade_date),
        SourceMeta("东方财富", "push2ex.eastmoney.com/getTopicZBPool", evidence_level="待核验/线索级", kind="limit_up", research_role="market_temperature", usage="只衡量交易温度，不证明瓶颈。"),
    ),
    "dt-pool": (
        lambda code, trade_date, **_: em_dt_pool(trade_date),
        SourceMeta("东方财富", "push2ex.eastmoney.com/getTopicDTPool", evidence_level="待核验/线索级", kind="limit_up", research_role="market_temperature", usage="只衡量交易温度，不证明瓶颈。"),
    ),
    "yzt-pool": (
        lambda code, trade_date, **_: em_yzt_pool(trade_date),
        SourceMeta("东方财富", "push2ex.eastmoney.com/getYesterdayZTPool", evidence_level="待核验/线索级", kind="limit_up", research_role="market_temperature", usage="只衡量交易温度，不证明瓶颈。"),
    ),
    "ths-limit-up": (
        lambda code, trade_date, **_: ths_limit_up_pool(trade_date),
        SourceMeta("同花顺", "data.10jqka.com.cn/dataapi/limit_up/limit_up_pool", evidence_level="待核验/线索级", kind="limit_up", research_role="market_temperature", usage="只衡量交易温度，不证明瓶颈。"),
    ),
    "em-hot-rank": (
        lambda code, **_: em_hot_rank(50),
        SourceMeta("东方财富", "emappdata.eastmoney.com/stockrank/getAllCurrentList", evidence_level="待核验/线索级", kind="hot_rank", research_role="market_temperature", usage="市场关注度，不是公司事实。"),
    ),
    "ths-hot-list": (
        lambda code, **_: ths_hot_list("hour"),
        SourceMeta("同花顺", "dq.10jqka.com.cn/fuyao/hot_list_data/.../stock", evidence_level="待核验/线索级", kind="hot_rank", research_role="thesis_leads", usage="题材线索，需公告/财报核验。"),
    ),
    "em-hot-concept": (
        lambda code, **_: em_hot_concept(code),
        SourceMeta("东方财富", "emappdata.eastmoney.com/stockrank/getHotStockRankList", evidence_level="待核验/线索级", kind="hot_concept", research_role="thesis_leads", usage="市场归因，不能单独支撑瓶颈结论。"),
    ),
}

PRESETS: dict[str, list[str]] = {
    "company": ["quote", "stock-info", "announcements", "financials"],
    "deep": ["quote", "stock-info", "announcements", "financials", "reports", "ths-eps-forecast", "answered-irm"],
    "leads": ["stock-news", "global-news", "industry-reports", "concepts", "em-hot-concept", "ths-hot-list"],
    "market": [
        "em-hot-concept",
        "em-hot-rank",
        "ths-hot-list",
        "zt-pool",
        "zb-pool",
        "dt-pool",
        "yzt-pool",
        "ths-limit-up",
        "fund-flow",
        "fund-flow-minute",
        "dragon-tiger",
        "daily-dragon-tiger",
        "northbound",
    ],
}
DEFAULT_PRESET = "company"
DEFAULT_INCLUDE = PRESETS[DEFAULT_PRESET]


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
    artifact_root: str | Path = DEFAULT_ARTIFACT_ROOT,
    run_id: str | None = None,
    topic: str = "",
    pdf_dir: str | Path | None = None,
    pdf_limit: int = 3,
    pdf_cache_days: int = 1,
) -> dict[str, Any]:
    """Fetch an explicit A-share data snapshot with provenance per dataset."""
    normalized = normalize_code(code)
    full_source_scan = bool(include and "all" in include)
    selected = expand_datasets(include)
    trade_date = normalize_trade_date(trade_date, style="dash")
    snapshot: dict[str, Any] = {
        "ticker": canonical_ticker(normalized),
        "code": normalized,
        "market": exchange_suffix(normalized),
        "fetched_at": now_iso(),
        "policy": {
            "default_single_agent": True,
            "full_source_scan": full_source_scan,
            "note": "Datasets are role-scoped; leads and market temperature do not prove core bottleneck claims.",
        },
        "datasets": {},
    }
    artifact_manifest: dict[str, Any] | None = None
    run_pdf_dir: Path | None = None
    pdf_cache_dir: Path | None = None
    if download_report_pdfs:
        artifact_manifest = init_artifact_manifest(normalized, artifact_root=artifact_root, run_id=run_id, topic=topic)
        run_pdf_dir = Path(pdf_dir) if pdf_dir else Path(str(artifact_manifest["pdf_dir"]))
        pdf_cache_dir = Path(artifact_root) / "_cache" / "pdfs"
        snapshot["artifacts"] = {
            "run_id": artifact_manifest["run_id"],
            "artifact_dir": artifact_manifest["artifact_dir"],
            "manifest_path": artifact_manifest["manifest_path"],
            "pdf_dir": str(run_pdf_dir),
            "pdf_cache_dir": str(pdf_cache_dir),
            "pdf_cache_days": pdf_cache_days,
            "policy": "Only sources listed in this run manifest should be cited by this report.",
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
            if (
                download_report_pdfs
                and name in {"reports", "industry-reports"}
                and isinstance(data, list)
                and artifact_manifest is not None
                and run_pdf_dir is not None
                and pdf_cache_dir is not None
            ):
                paths: list[str] = []
                entries: list[dict[str, Any]] = []
                errors: list[dict[str, str]] = []
                for idx, record in enumerate(data[: max(0, pdf_limit)], start=1):
                    if not isinstance(record, dict):
                        errors.append({"index": str(idx), "error": "record is not an object"})
                        continue
                    try:
                        entry = download_pdf_artifact(
                            record,
                            run_pdf_dir,
                            cache_dir=pdf_cache_dir,
                            cache_days=pdf_cache_days,
                            run_id=str(artifact_manifest["run_id"]),
                            dataset=name,
                        )
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
                    if entry:
                        paths.append(str(entry["path"]))
                        entries.append(entry)
                        add_manifest_source(artifact_manifest, entry)
                    else:
                        errors.append({"index": str(idx), "title": str(record.get("title", ""))[:80], "error": "PDF not available"})
                snapshot["datasets"][name]["downloaded_pdfs"] = paths
                snapshot["datasets"][name]["pdf_manifest_entries"] = entries
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
    if artifact_manifest is not None:
        write_artifact_manifest(artifact_manifest)
    return snapshot


def expand_datasets(include: list[str] | None = None) -> list[str]:
    items = include or DEFAULT_INCLUDE
    if "all" in items:
        return list(FETCHERS.keys())
    selected: list[str] = []
    for item in items:
        if item in PRESETS:
            selected.extend(PRESETS[item])
        else:
            selected.append(item)
    deduped: list[str] = []
    for item in selected:
        if item not in deduped:
            deduped.append(item)
    return deduped


def parse_include(value: str, *, preset: str = DEFAULT_PRESET) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if items:
        if "all" in items:
            return items
        return expand_datasets(items)
    if preset not in PRESETS:
        raise ValueError(f"unknown preset: {preset}")
    return expand_datasets(PRESETS[preset])


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch explicit A-share public data with provenance metadata.")
    parser.add_argument("ticker", nargs="?", help="A-share ticker, e.g. 600519, 600519.SH, SZ000001")
    parser.add_argument(
        "--include",
        default="",
        help="Comma list of datasets or preset names; overrides --preset when provided.",
    )
    parser.add_argument("--preset", choices=sorted(PRESETS), default=DEFAULT_PRESET, help="Role-scoped dataset bundle")
    parser.add_argument("--list-datasets", action="store_true", help="List available dataset names and exit")
    parser.add_argument("--list-presets", action="store_true", help="List dataset presets and exit")
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--report-type", choices=["lrb", "fzb", "llb"], default="lrb")
    parser.add_argument("--financial-periods", type=int, default=8)
    parser.add_argument("--industry-code", default="*")
    parser.add_argument("--trade-date", help="YYYY-MM-DD or YYYYMMDD for daily event datasets; defaults to today")
    parser.add_argument("--download-report-pdfs", action="store_true", help="Download PDFs for reports/industry-reports")
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT, help="Root for per-run artifacts and PDF cache")
    parser.add_argument("--run-id", help="Explicit run id for artifact isolation")
    parser.add_argument("--topic", default="", help="Optional topic slug stored in the run manifest")
    parser.add_argument("--pdf-dir", type=Path, help="Override this run's PDF output directory")
    parser.add_argument("--pdf-limit", type=int, default=3)
    parser.add_argument("--pdf-cache-days", type=int, default=1, help="Reuse same infoCode PDF cache for this many days; 0 disables")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.list_datasets:
        for name in sorted(FETCHERS):
            print(name)
        return 0
    if args.list_presets:
        for name, datasets in PRESETS.items():
            print(f"{name}: {','.join(datasets)}")
        return 0
    if not args.ticker:
        parser.error("ticker is required unless --list-datasets or --list-presets is used")
    snapshot = fetch_snapshot(
        args.ticker,
        parse_include(args.include, preset=args.preset),
        max_pages=args.max_pages,
        page_size=args.page_size,
        report_type=args.report_type,
        financial_periods=args.financial_periods,
        industry_code=args.industry_code,
        trade_date=args.trade_date,
        download_report_pdfs=args.download_report_pdfs,
        artifact_root=args.artifact_root,
        run_id=args.run_id,
        topic=args.topic,
        pdf_dir=args.pdf_dir,
        pdf_limit=args.pdf_limit,
        pdf_cache_days=args.pdf_cache_days,
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
