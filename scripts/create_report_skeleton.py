#!/usr/bin/env python3
"""Create bottleneck-scout-v3 Chinese report scaffolds."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path


FORMAL_TEMPLATE = """# {title}

作者：瓶颈侦察 v3
生成时间：{generated}
行情时间：TODO
报告性质：研究分析，不构成投资建议。
交付状态：正式深度研报

## 结论

首页只放 3-5 个最高优先级对象。`待核验/线索级` 和 `无支撑` 不得进入首页核心结论。

| 分层 | 市场 | 标的/环节 | 代码 | 方向 | 风格 | 综合评分 | 证据等级 | 核心理由 | 失效条件 |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| TODO | TODO | TODO | N/A | 中性 / 待验证 | 中期验证 | 0 | 直接证据 / 交叉印证 / 框架推演 | TODO | TODO |

- 新闻触发背景：TODO
- 瓶颈节点：TODO
- 核心结论：TODO
- 短期/长期判断：TODO
- 下一验证窗口：TODO

## 报告摘要

- 事件性质：TODO
- 核心价格/需求变量：TODO
- 受益与受损环节：TODO
- 最大证伪风险：TODO
- 下一阶段验证事件：TODO

## 提问背景

- 用户给出的事件/政策/产业变化：TODO
- 用户希望推导的投资问题：TODO
- 已验证的公开事实：TODO
- 仍待验证或仅属线索的部分：TODO

## 叙事逻辑

TODO

## 投资者答案

| 优先级 | 公司/环节 | Alpha 类型 | 市场可能低估什么 | 弹性触发器 | 当前不确定性 | 结论 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | TODO | TODO | TODO | TODO | TODO | TODO |

## 评分分层与证据封顶

| 对象 | 瓶颈稀缺度 30 | 财务传导 30 | 估值/赔率 25 | 催化与验证 15 | 研究强度分 | 最强证据 | 封顶后评分 | 分层 | 扣分项 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |
| TODO | 0 | 0 | 0 | 0 | 0 | 直接证据 | 0 | 剔除/待验证 | TODO |

## 价值传导链 / 供应链地图

### 链路证据表

| 起点 | 传导到 | 关系 | 证据等级 | 来源 | 绕开风险 |
| --- | --- | --- | --- | --- | --- |
| TODO | TODO | TODO | 直接证据 | S01 | TODO |

## 建议拆解图 / 价值传导剖解图（可选）

不适用或证据不足时删除本节，改用 2-3 句文字链路。

| 图层 | 关键节点 | 卡点来源 | 关键数字 | 来源/日期 | 证据等级 | 证伪条件 |
| --- | --- | --- | --- | --- | --- | --- |
| TODO | TODO | TODO | N/A | S01 / {date_text} | 直接证据 | TODO |

## Chokepoint Quick Filter

| 候选 | Demand | Transmission | Bottleneck | Elasticity | 结论 |
| --- | --- | --- | --- | --- | --- |
| TODO | TODO | TODO | TODO | TODO | TODO |

## 公司证据与财务传导

| 公司 | 代码 | directional_bias | research_rating | expected_price_reaction | 收入/客户/订单/产能证据 | 财务传导 | 估值/赔率 | invalidation_condition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TODO | N/A | 中性 / 待验证 | 观察跟踪 | TODO | TODO | TODO | TODO | TODO |

## 股价位置与交易赔率

只覆盖核心研究和弹性关注；输出价格位置、拥挤度和赔率框架，不输出交易动作。

## 方向判断与目标价框架

| 公司 | 代码 | directional_bias | expected_price_reaction | target_price_range | target_time_horizon | target_price_basis |
| --- | --- | --- | --- | --- | --- | --- |
| TODO | N/A | 中性 / 待验证 | TODO | N/A | N/A | 证据不足，暂无可靠估值锚 |

## 红队与硬性否决

| 候选 | 最强反方论点 | 证伪事件 | 当前处理 |
| --- | --- | --- | --- |
| TODO | TODO | TODO | TODO |

## 高风险交叉验证

- 是否触发：TODO
- 验证任务：TODO
- 结论冲突和裁决：TODO
- 降级说明：TODO

## 跟踪清单

| 触发器 | 监控位置 | 意义 | 时间窗口 |
| --- | --- | --- | --- |
| TODO | TODO | TODO | TODO |

## 本报告数据源清单

| 来源 | 用途 | 日期 | 检索日 | 证据等级 | 状态 | fallback |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | TODO | {date_text} | {date_text} | 直接证据 | TODO | TODO |

## 附录：来源清单

| ID | 等级 | 来源 | 日期 | 检索日 | 支持的结论 | 链接 |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | 直接证据 | TODO | {date_text} | {date_text} | TODO | TODO |
"""


LIGHT_TEMPLATE = """# {title}

作者：瓶颈侦察 v3
生成时间：{generated}
报告性质：研究分析，不构成投资建议。
交付状态：{mode_label}

## 当前判断

TODO

## 证据等级

TODO

## 最大反证

TODO

## 下一步优先查什么

TODO
"""


QA_TEMPLATE = """# 交付QA_{date}

## 交付状态

| 产物 | 状态 | 路径/说明 |
| --- | --- | --- |
| Markdown | 待完成 | {markdown_path} |
| PDF | 待渲染 | {pdf_path} |
| PDF 版式检查 | 待检查 | 渲染后必须运行 validate_pdf_layout.py |
| 证据清单 | 待完成 | 可合并入正文或 sidecar |
| 价值传导链 | 待完成 | 不适用时写文字降级 |

## 核心闸门

| 闸门 | 结果 | 说明 |
| --- | --- | --- |
| 首页 `## 结论` | 待检查 | 元信息后的第一个二级标题必须是结论 |
| 交易话术 | 待检查 | 禁止指令性交易建议 |
| 证据等级与封顶 | 待检查 | 框架推演 64，待核验/线索级 49 |
| 待核验线索 | 待检查 | 不得进入首页核心结论 |
| 裸 Mermaid/内部字段 | 待检查 | 正式 PDF 不得出现 |

## QA 问题清单

| Severity | Category | Issue | Suggested Fix | Status |
| --- | --- | --- | --- | --- |

## 本报告数据源清单

| 来源 | 用途 | 日期 | 证据等级 | 状态 | fallback |
| --- | --- | --- | --- | --- | --- |

## PDF 检查摘要

| 项目 | 结果 |
| --- | --- |
| 页数 | 待检查 |
| 字体 | 待检查 |
| 首页结论 | 待检查 |
| 股票代码断行 | 待检查 |
| 缺字方块 | 待检查 |
| 裸 Mermaid/JSON/内部字段 | 待检查 |

## 降级与例外

TODO
"""


def date_stamp(value: str | None) -> str:
    if value:
        cleaned = re.sub(r"\D", "", value)
        if len(cleaned) == 8:
            return cleaned
        raise ValueError("--date must be YYYYMMDD or YYYY-MM-DD")
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def safe_title(title: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "", title).strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned or "瓶颈侦察"


def resolve_paths(title: str, output: Path, mode: str, date: str) -> tuple[Path, Path | None, Path | None]:
    output = output.expanduser()
    if output.suffix == ".md":
        markdown_path = output
        directory = output.parent
        stem = output.stem
    else:
        directory = output
        mode_suffix = {"formal": "深度研报", "event": "事件快评", "review": "复盘验证"}[mode]
        stem = f"{safe_title(title)}{mode_suffix}_{date}"
        markdown_path = directory / f"{stem}.md"
    pdf_path = directory / f"{stem}.pdf" if mode == "formal" else None
    qa_path = directory / f"交付QA_{date}.md" if mode == "formal" else None
    return markdown_path, pdf_path, qa_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("title")
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=["formal", "event", "review"], default="formal")
    parser.add_argument("--date", default=None, help="YYYYMMDD or YYYY-MM-DD; defaults to current UTC date")
    args = parser.parse_args()

    date = date_stamp(args.date)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    date_text = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    markdown_path, pdf_path, qa_path = resolve_paths(args.title, args.output, args.mode, date)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "formal":
        markdown = FORMAL_TEMPLATE.format(
            title=args.title,
            generated=generated,
            date_text=date_text,
        )
        markdown_path.write_text(markdown, encoding="utf-8")
        assert pdf_path is not None and qa_path is not None
        qa_path.write_text(
            QA_TEMPLATE.format(
                date=date,
                markdown_path=markdown_path,
                pdf_path=pdf_path,
            ),
            encoding="utf-8",
        )
        print(markdown_path)
        print(pdf_path)
        print(qa_path)
        return 0

    mode_label = "事件快评" if args.mode == "event" else "复盘验证"
    markdown_path.write_text(
        LIGHT_TEMPLATE.format(title=args.title, generated=generated, mode_label=mode_label),
        encoding="utf-8",
    )
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
