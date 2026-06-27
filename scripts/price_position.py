#!/usr/bin/env python3
"""Compute Chinese price-position tables and stock cards from JSON history."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import pstdev
from typing import Any


WINDOWS = [
    ("3年", 756),
    ("1年", 252),
    ("6个月", 126),
    ("3个月", 63),
    ("21日", 21),
]
FULL_CARD_RATINGS = {"核心研究", "核心推荐", "弹性关注"}


def as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return float(value)
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("%", "")
        if not text or text in {"-", "未取得", "N/A", "None"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def fmt_num(value: Any, suffix: str = "") -> str:
    number = as_float(value)
    if number is None:
        return "未取得"
    if abs(number) >= 100:
        return f"{number:.0f}{suffix}"
    if abs(number) >= 10:
        return f"{number:.1f}{suffix}"
    return f"{number:.2f}{suffix}"


def fmt_pct(value: Any) -> str:
    number = as_float(value)
    if number is None:
        return "未取得"
    return f"{number:.1f}%"


def fmt_money_yi(value: Any) -> str:
    number = as_float(value)
    if number is None:
        return "未取得"
    return f"{number:.1f}亿元"


def escape_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def series_values(item: dict[str, Any], key: str) -> list[float]:
    raw = item.get(key, [])
    values: list[float] = []
    for entry in raw:
        if isinstance(entry, dict):
            value = entry.get("value")
            if value is None:
                if key == "closes":
                    value = entry.get("close")
                elif key in {"amounts", "turnover_amounts"}:
                    value = entry.get("amount")
                elif key == "market_caps":
                    value = entry.get("market_cap")
        else:
            value = entry
        number = as_float(value)
        if number is not None:
            values.append(number)
    return values


def last_window(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    return values[-min(len(values), window) :]


def percentile(current: float | None, values: list[float]) -> float | None:
    if current is None or not values:
        return None
    count = sum(1 for value in values if value <= current)
    return count / len(values) * 100


def distance_from_high(current: float | None, values: list[float]) -> float | None:
    if current is None or not values:
        return None
    high = max(values)
    if high <= 0:
        return None
    return (current / high - 1) * 100


def distance_from_low(current: float | None, values: list[float]) -> float | None:
    if current is None or not values:
        return None
    low = min(values)
    if low <= 0:
        return None
    return (current / low - 1) * 100


def period_return(values: list[float], days: int) -> float | None:
    if len(values) <= days:
        return None
    start = values[-days - 1]
    end = values[-1]
    if start <= 0:
        return None
    return (end / start - 1) * 100


def annualized_volatility(values: list[float], days: int = 60) -> float | None:
    window = last_window(values, days + 1)
    if len(window) < 3:
        return None
    returns = []
    for prev, cur in zip(window, window[1:]):
        if prev > 0:
            returns.append(cur / prev - 1)
    if len(returns) < 2:
        return None
    return pstdev(returns) * math.sqrt(252) * 100


def max_drawdown(values: list[float], days: int = 252) -> float | None:
    window = last_window(values, days)
    if len(window) < 2:
        return None
    peak = window[0]
    worst = 0.0
    for value in window:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1)
    return worst * 100


def relative_strength(item: dict[str, Any], closes: list[float]) -> float | None:
    benchmark = series_values(item, "benchmark_closes")
    stock_return = period_return(closes, 60)
    benchmark_return = period_return(benchmark, 60)
    if stock_return is None or benchmark_return is None:
        return None
    return stock_return - benchmark_return


def position_label(one_year_pct: float | None, distance_1y_high: float | None, amount_pct: float | None, evidence: float | None) -> str:
    if evidence is not None and evidence < 3:
        return "剔除风险型"
    if one_year_pct is not None and one_year_pct <= 35:
        return "低位修复型" if evidence is not None and evidence >= 4 else "左侧观察型"

    near_high = distance_1y_high is not None and distance_1y_high > -15
    high_position = one_year_pct is not None and one_year_pct >= 75
    hot_turnover = amount_pct is not None and amount_pct >= 90
    evidence_lag = evidence is None or evidence < 4

    # A high percentile is not crowding by itself. Treat it as breakout strength
    # unless trading heat is extreme and the evidence score has not caught up.
    if high_position and near_high:
        return "拥挤交易型" if hot_turnover and evidence_lag else "高位突破型"
    if hot_turnover and evidence_lag:
        return "拥挤交易型"
    if one_year_pct is not None and one_year_pct >= 75:
        return "高位突破型"
    return "均衡观察型"


def odds_comment(label: str) -> str:
    comments = {
        "低位修复型": "价格位置不高，若证据继续兑现，赔率来自估值修复。",
        "高位突破型": "价格已偏强，可能是新信息确认；关键是证据、估值和催化能否继续跟上。",
        "拥挤交易型": "交易热度已高，只有证据兑现速度继续超过预期，赔率才会改善。",
        "左侧观察型": "位置有吸引力，但证据或催化还不够，需要等验证。",
        "剔除风险型": "便宜本身不能补足证据缺口，谨防价值陷阱。",
        "均衡观察型": "价格位置居中，主要看后续证据和催化质量。",
    }
    return comments.get(label, "需要结合证据、估值和催化继续判断。")


def build_metrics(item: dict[str, Any]) -> dict[str, Any]:
    closes = series_values(item, "closes")
    current = as_float(item.get("current_price")) or (closes[-1] if closes else None)
    amounts = series_values(item, "amounts") or series_values(item, "turnover_amounts")
    current_amount = as_float(item.get("turnover_amount")) or (amounts[-1] if amounts else None)
    market_caps = series_values(item, "market_caps")
    current_market_cap = as_float(item.get("market_cap")) or (market_caps[-1] if market_caps else None)

    price_percentiles = {
        label: percentile(current, last_window(closes, days)) for label, days in WINDOWS
    }
    high_distances = {
        label: distance_from_high(current, last_window(closes, days)) for label, days in WINDOWS
    }
    amount_pct_20 = percentile(current_amount, last_window(amounts, 20)) if amounts else None
    market_cap_pct = percentile(current_market_cap, market_caps) if market_caps else None
    one_year_closes = last_window(closes, 252)
    label = position_label(
        price_percentiles.get("1年"),
        high_distances.get("1年"),
        amount_pct_20,
        as_float(item.get("evidence")),
    )

    return {
        "current": current,
        "current_amount": current_amount,
        "market_cap": current_market_cap,
        "float_market_cap": as_float(item.get("float_market_cap")),
        "turnover_rate": as_float(item.get("turnover_rate")),
        "pe": as_float(item.get("pe")),
        "pb": as_float(item.get("pb")),
        "ps": as_float(item.get("ps")),
        "price_percentiles": price_percentiles,
        "high_distances": high_distances,
        "distance_1y_low": distance_from_low(current, one_year_closes),
        "return_60d": period_return(closes, 60),
        "amount_pct_20": amount_pct_20,
        "market_cap_pct": market_cap_pct,
        "volatility_60d": annualized_volatility(closes, 60),
        "max_drawdown_1y": max_drawdown(closes, 252),
        "relative_strength_60d": relative_strength(item, closes),
        "label": item.get("position_tag") or label,
        "comment": item.get("position_comment") or odds_comment(item.get("position_tag") or label),
    }


def overview_table(items: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 公司 | 评级 | 股价分位 | 距1年高点 | 距3年高点 | 市值分位 | 成交热度 | 交易赔率判断 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for item in items:
        metrics = item["_metrics"]
        if item.get("rating") not in FULL_CARD_RATINGS:
            continue
        lines.append(
            "| {company} | {rating} | {pct_1y} | {high_1y} | {high_3y} | {mcap_pct} | {amount_pct} | {comment} |".format(
                company=escape_cell(item.get("company", "")),
                rating=escape_cell(item.get("rating", "")),
                pct_1y=fmt_pct(metrics["price_percentiles"].get("1年")),
                high_1y=fmt_pct(metrics["high_distances"].get("1年")),
                high_3y=fmt_pct(metrics["high_distances"].get("3年")),
                mcap_pct=fmt_pct(metrics["market_cap_pct"]),
                amount_pct=fmt_pct(metrics["amount_pct_20"]),
                comment=escape_cell(metrics["label"] + "：" + metrics["comment"]),
            )
        )
    return lines


def stock_card(item: dict[str, Any]) -> list[str]:
    metrics = item["_metrics"]
    company = escape_cell(item.get("company", ""))
    ticker = escape_cell(item.get("ticker", ""))
    lines = [f"### {company}（{ticker}）"]
    lines.extend(
        [
            "| 模块 | 指标 | 数据 |",
            "| --- | --- | --- |",
            f"| 当前状态 | 股价 / 市值 / 流通市值 | {fmt_num(metrics['current'])} / {fmt_money_yi(metrics['market_cap'])} / {fmt_money_yi(metrics['float_market_cap'])} |",
            f"| 当前状态 | 成交额 / 换手率 | {fmt_money_yi(metrics['current_amount'])} / {fmt_pct(metrics['turnover_rate'])} |",
            f"| 当前状态 | PE / PB / PS | {fmt_num(metrics['pe'])} / {fmt_num(metrics['pb'])} / {fmt_num(metrics['ps'])} |",
            f"| 价格分位 | 3年 / 1年 / 6个月 / 3个月 / 21日 | {fmt_pct(metrics['price_percentiles'].get('3年'))} / {fmt_pct(metrics['price_percentiles'].get('1年'))} / {fmt_pct(metrics['price_percentiles'].get('6个月'))} / {fmt_pct(metrics['price_percentiles'].get('3个月'))} / {fmt_pct(metrics['price_percentiles'].get('21日'))} |",
            f"| 距离高点 | 3年 / 1年 / 6个月 / 3个月 / 21日 | {fmt_pct(metrics['high_distances'].get('3年'))} / {fmt_pct(metrics['high_distances'].get('1年'))} / {fmt_pct(metrics['high_distances'].get('6个月'))} / {fmt_pct(metrics['high_distances'].get('3个月'))} / {fmt_pct(metrics['high_distances'].get('21日'))} |",
            f"| 辅助判断 | 距1年低点 / 60日涨跌幅 | {fmt_pct(metrics['distance_1y_low'])} / {fmt_pct(metrics['return_60d'])} |",
            f"| 辅助判断 | 20日成交额分位 / 波动率 / 最大回撤 | {fmt_pct(metrics['amount_pct_20'])} / {fmt_pct(metrics['volatility_60d'])} / {fmt_pct(metrics['max_drawdown_1y'])} |",
            f"| 辅助判断 | 相对板块强弱 | {fmt_pct(metrics['relative_strength_60d'])} |",
            f"| 交易标签 | {escape_cell(metrics['label'])} | {escape_cell(metrics['comment'])} |",
        ]
    )
    if item.get("position_note"):
        lines.append(f"\n{escape_cell(item['position_note'])}\n")
    return lines


def load_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        raise ValueError("Expected a JSON list or an object with an 'items' list")
    items = [item for item in data if isinstance(item, dict)]
    for item in items:
        item["_metrics"] = build_metrics(item)
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    items = load_items(args.input)
    lines = ["## 股价位置与交易赔率", ""]
    lines.extend(overview_table(items))
    lines.append("")
    lines.append("### 单股数据卡")
    lines.append("")
    for item in items:
        if item.get("rating") in FULL_CARD_RATINGS:
            lines.extend(stock_card(item))
            lines.append("")

    output = "\n".join(lines).rstrip() + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(args.output)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
