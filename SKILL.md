---
name: bottleneck-scout-v3
description: Chinese-first paid-grade investment research skill for public equities, industry narratives, and company baskets. Use when the user asks to analyze a market theme, policy route, technology shift, KOL thesis, single company, or stock list by mapping the value-transmission chain, finding verified bottlenecks, ranking hidden-champion or high-elasticity candidates, red-teaming risks, checking fresh market data, and producing Markdown/PDF reports.
metadata:
  display_name: 瓶颈侦察v3
  short-description: 价值传导瓶颈与付费级中文投研
---

# 瓶颈侦察v3

把市场叙事、政策变化、技术路线或股票篮子，拆成可验证的价值传导链，并输出中文机构风格的投资研究结论。核心问题是：

**如果这个 thesis 成立，价值会通过哪条链路进入收入、利润、现金流或估值重分类？真正稀缺且可投资的瓶颈在哪里，证据是否足够让普通投资者愿意为这份研报付费？**

## Hard Rules

- 中文优先。中国、A股、港股主题默认中文机构研报风格；英文术语只保留标准名。
- 默认主战场是 A 股：除非用户明确要求“全球标的/全球”或指定美股/港股，正式输出以寻找可投 **A 股标的** 为首要目标，H 股、美股、全球赢家作为次要对照。首页结论默认 A 股候选在前，其它市场作对照行。
- 仍要分清全球赢家、A股映射、H股映射和 US exposure，并老实标注 A 股是直接暴露还是映射。不得为了凑 A 股答案而强行映射或编造；没有真实 A 股暴露时直接写“暂无直接 A 股标的”，并把全球/美股最直接的赢家作为对照列出，不忽略 US 公开股票里的真实瓶颈暴露。
- 按市场分车道相对排序：在用户可投范围（默认 A 股）内选出相对最优的几家，即使它们全球排不进前列也照常排序并标注；不要因为全球有更优标的就把整组 A 股降级或塌成待验证。
- 必须浏览或检索当前事实。股票价格、市值、成交、估值、公告、年报、监管信息不能靠记忆。
- KOL、单一媒体、社媒、截图只能作为 `待核验/线索级`，不得作为首页核心结论、核心研究或来源数量。
- 先回答投资者问题：有没有低估隐形冠军、小基数高弹性、低估值真实暴露；如果没有，直接说没有。
- 正式 Markdown/PDF 在元信息后先写 `## 结论`，直接列瓶颈结论、推荐/观察标的、方向、期限风格、证据等级、新闻触发背景和失效条件；不要先铺背景或目录。
- `## 结论` 是第一页决策入口，不是背景页：默认只列 3-5 个高优先级标的/环节；一行只放一个公开标的和一个代码，不要把多家公司或多个代码用 `/` 合并到同一格。
- 目录默认关闭。只有用户明确要求归档目录时，PDF 才允许开启目录；普通事件研报第一页必须承载关键结果。
- 首页必须回答"赛道进度 + 该投谁 + 各自位置"：在结论表前放一行 `赛道阶段`（萌芽/发酵/加速/验证/兑现退潮 + 一句话进度 + 下一关键验证），结论表用 `阶段位置` 列把赛道阶段与个股价格位置（低位/中位/高位/透支）合并。叙事发酵阶段是研究维度，必须有证据支撑，不靠情绪臆测；阶段判断错误也是失效条件之一。
- 不强行把所有公司套成硬件供应链；先识别业务类型，再用价值传导链分析。
- 宁缺毋滥。证据不足时降级为观察、待验证或剔除，不硬凑研报数量。
- 不输出买入、卖出、加仓、减仓、仓位、止损、无脑买、Kelly sizing 或个性化投资建议。把用户的交易动作问题改写成研究评级、证据强度、价格位置、观察窗口、风险等级和失效条件。
- 禁用话术只约束 skill 自身的指令性表达；来源引用、否定句、合规说明和反例说明可以出现相关词，但必须明确不是本报告建议。
- 正式深度研报默认交付中文三件套：中文 Markdown、中文 PDF、`交付QA_YYYYMMDD.md`。事件快评和普通复盘验证默认轻量，不强制 PDF、完整评分表或交付 QA。
- `研究提纲/待验证版` 默认只交付 Markdown；用户明确要求 PDF 时，标题、首页和 QA 必须显著标注“待验证版/非正式研报”。
- 事件驱动研报必须先通过 `事件方向闸门`：先判断核心价格变量方向，再判断标的与核心变量是正相关、负相关、双向还是待验证。
- 每个进入观察的公开标的必须输出 `directional_bias`、`research_rating`、`expected_price_reaction` 和 `invalidation_condition`；`Direct` 只代表证据直接，不代表利多或推荐。
- 标准/深度研报中，每个进入观察的公开标的还必须输出 `target_price_range`、`target_time_horizon` 和 `target_price_basis`；若证据不足，明确写 `N/A` 与原因，不得编造目标价。
- 正式 Markdown/PDF 中方向字段使用固定颜色：`看多/偏多/利多/正相关` 用红色，`看空/偏空/利空/负相关` 用绿色，`中性` 用灰色，`待验证/双向` 用橙色。
- 每个核心结论必须标五级中文证据：`直接证据（Direct）`、`交叉印证（Corroborated）`、`框架推演（Framework Inference）`、`待核验/线索级`、`无支撑（Unsupported）`。
- `待核验/线索级` 不能进入首页核心结论；`无支撑` 不能进入报告摘要、首页、核心研究或付费级结论。
- 评分采用“研究强度分 + 证据封顶”：框架推演最高 64 分，分层最多观察跟踪；待核验/线索级最高 49 分，分层只能剔除/待验证；无支撑不给分。
- 高风险核心结论必须触发交叉验证，或在无法交叉验证时显式降级。
- PDF 交付必须先出 Markdown，再渲染 PDF，并运行布局/文本 QA；PDF 失败时交付 Markdown 和失败命令。
- 本地 PDF/JSON 证据必须来自本轮 run 目录的 `manifest.json`；不得直接扫描或复用其它会话下载目录。研报 PDF 只允许按 `infoCode` 在 1 天缓存期内复用，并在本轮 manifest 标记 `reused_from_cache=true`。
- 默认仍为单 agent 高质量研究；不要把多 agent、多模型或全量数据源扫描变成固定前置成本。

## Request Router

先读 [router.md](references/router.md)，把用户入口收敛到 3 种内部模式：

- `事件快评`：新闻、政策、突发事件先判断核心价格变量和受益/受损链路，轻量输出，不默认 PDF。
- `复盘验证`：财报后验证、观点复盘、催化日历，输出一次性复盘快照或验证短表，不默认 PDF。
- `深度瓶颈研报`：正式交付、PDF、核心研究、投资标的分析、主题瓶颈扫描，要求来源清单、评分、证据封顶、结构化链路、红队、交叉验证和 PDF QA。

深度不是由文章长度决定，而是由证据强度和用户任务决定。轻量模式避免过度膨胀；标准/深度模式优先质量，不为凑数量引用弱来源。
如果用户用 `$bottleneck-scout-v3` 提出“投资标的分析”“中国投资标的分析”“可投标的分析”“深度分析”“付费级分析”，且没有明确说“快速/简单/初筛/不要 PDF”，默认按深度/PDF正式研报交付，不要停在聊天式标准回答。

## Core Workflow

1. **界定 thesis**
   - 复述用户问题，分离用户原始主张、已验证事实、待验证线索。
   - 对多事件、多股票请求，先提炼底层稀缺能力或价值传导节点。
   - 在正式报告中写出 `叙事逻辑`：用专业但易懂的语言说明需求、系统瓶颈、财务传导、远期叙事和最终评级之间的因果链。

2. **选择价值传导链（深度模式可选多模型发散）**
   - 读 [value-chain-types.md](references/value-chain-types.md)。
   - 硬件、软件、医药、能源、消费、金融平台分别使用不同链条。
   - 仅深度瓶颈研报、且主题宽或不熟时，可先做一次多模型发散，听别的模型怎么拆瓶颈、补盲区：`python3 scripts/cross_verify.py --diverge "主题"`。模型产出只是**候选假设 + 待验证清单**，一律以 `待核验/线索级` 进入，必须经四问过滤和证据闸门、联网取一手证据后才能升级。不调用则单 agent 自行拆链。事件快评、复盘、单公司财务复盘不做发散，避免把广度变成固定成本。

3. **建立证据库存**
   - 读 [source-playbook.md](references/source-playbook.md) 与 [evidence-gate.md](references/evidence-gate.md)。
   - 每条来源记录标题、发布者、日期、检索日、source rank、支持的具体 claim。

4. **运行四问过滤**
   - 读 [chokepoint-gate.md](references/chokepoint-gate.md)。
   - 对每个环节和候选公司检查 Demand、Transmission、Bottleneck、Elasticity。

5. **生成结构化链路**
   - 读 [graph-edges.md](references/graph-edges.md)。
   - 先写 JSON edges 作为内部/sidecar 验证材料，再把它转成投资者可读的链路证据表和 Mermaid/图。
   - 正式 PDF 正文不得出现 `Graph Gate`、`edges.json`、`source/target/relationship/evidence_level` 等内部流程词；不要让裸 Mermaid 留在最终 PDF。

6. **做红队与高风险判断**
   - 读 [red-team.md](references/red-team.md)。
   - 准备给核心推荐、正式 PDF 或高弹性候选时，读 [cross-check.md](references/cross-check.md)。
   - 需要对离散高风险事实（份额、产能、客户占比、独占率、涨价幅度等）做跨谱系核验时，按 cross-check.md 调用 `scripts/cross_verify.py`；不投票，按证据强度裁决，缺密钥则降级。默认单 agent 路径不调用。

7. **查行情和价格位置**
   - 对公开股票抓取最新价格、市值、成交、估值、公告日期。A 股可显式调用 `scripts/fetch_a_stock_data.py`；该工具已从 `a-stock-data` 复制/改写到本仓库，默认只抓取显式 dataset，不运行时引用外部目录。它不是唯一来源，仍可联网搜索和浏览原始网页补充最新事实、研报原文、公告原文和交叉验证。
   - 对 `核心推荐` 和 `弹性关注` 使用 `scripts/price_position.py` 计算 3年、1年、6个月、3个月、21日价格位置。
   - 若输出 `target_price_range`，必须同时写清估值法/分部法/可比法等 `target_price_basis` 与 `target_time_horizon`；证据不够时降级为 `N/A`，不要硬给数字。

8. **输出研报**
   - 标准/深度使用 [report-template.md](references/report-template.md)。
   - PDF 与排版规则读 [output-standards.md](references/output-standards.md)。
   - 正式深度研报默认使用中文文件名，例如 `{中文主题}深度研报_YYYYMMDD.md`、`{中文主题}深度研报_YYYYMMDD.pdf`、`交付QA_YYYYMMDD.md`。
   - 用 `scripts/render_pdf.py` 渲染，用 `scripts/validate_pdf_layout.py` 和 `scripts/validate_report.py` 验证；PDF QA 未通过时不得登记为完成。

9. **保留来源与取舍记录**
   - 读 [provenance.md](references/provenance.md)，确认本 skill 吸收了哪些 Serenity/chokepoint 精华，以及明确没有吸收哪些人格化、仓位化或弱证据内容。

## Rating Labels

只使用以下研究评级：

- `核心研究`：证据强、暴露真实、估值/赔率框架可接受、催化路径清楚，并已通过红队与高风险交叉验证或明确说明验证状态。
- `弹性关注`：真实暴露与高弹性存在，但客户、估值、波动、时点或证据强度仍不足以进入核心。
- `观察跟踪`：公司真实或龙头明确，但估值、拥挤、纯度或催化不足。
- `证据不足剔除`：只有概念表述、弱来源、旧线索、无收入/客户/订单/产能验证或公众市场捕获弱。

不要因为股价创新高就机械降级。价格位置是 setup 信号；拥挤必须结合成交、换手、波动、持仓、估值和证据兑现速度判断。

## Useful Scripts

- `scripts/validate_skill.py`: 检查文件结构、中文显示名、reference 链接、禁止项、脚本可用性。
- `scripts/validate_report.py`: 检查报告是否包含证据等级、Quick Filter、红队、结构化 edges、来源清单和 PDF QA 标记。
- `scripts/graph_edges.py`: 验证结构化 edges JSON，并生成 Mermaid 依赖图。
- `scripts/evidence_matrix.py`: 从 JSON 证据项生成瓶颈评分表。
- `scripts/valuation_rating.py`: 从 JSON 公司项生成中文评级表。
- `scripts/price_position.py`: 从历史行情 JSON 生成价格位置与交易赔率页。
- `scripts/fetch_a_stock_data.py`: 显式抓取 A 股公开数据快照和可选研报 PDF，输出带来源、日期、证据等级和状态的 JSON；默认不做全量扫描。
- `scripts/freshness_check.py`: 检查市场数据和来源时效。
- `scripts/render_pdf.py`: 将 Markdown 中文研报渲染为 PDF；默认不生成目录，需要目录时显式传 `--toc-mode auto` 或 `--toc-mode always`。
- `scripts/validate_pdf_layout.py`: 检查 PDF 字体、粘连、目录、stock code 断行和页面预览。
- `scripts/cross_verify.py`: 高风险离散事实的多模型交叉验证（OpenCode Go 单密钥，三家不同谱系，不投票）；仅高风险触发时使用，需 `config/opencode.env`。

## External Absorption Boundary

- `a-stock-data` 的公开数据端点已经复制/改写进 `scripts/data_sources/a_stock.py`，保留 Apache-2.0 来源说明（见 `references/third-party-notices.md`）；后续使用本仓库代码。
- `TradingAgents`、`UZI-Skill`、`financial-services`、`ai-berkshire`、`buffett-skills`、`serenity-skill`、`zhengxi-views` 只吸收方法论、错误处理、来源纪律和 QA 边界；不吸收固定多 agent、多模型、收益展示、交易动作、仓位/止损/再平衡、人物语料或报告正文。
- 第三方代码归属和许可证边界见 [third-party-notices.md](references/third-party-notices.md)。

## Completion Standard

完成一次正式任务前，用以下问题自检：

- 报告是否先回答普通投资者最关心的研究问题，而不是先铺百科？
- 元信息后的第一个二级标题是否是 `## 结论`？
- 每条关键结论是否能追到来源、日期和证据等级？
- 首页核心结论是否排除了 `待核验/线索级` 和 `无支撑`？
- 评分是否执行了框架推演 64、待核验/线索级 49 的封顶？
- 反方论点是否足够强，而不是礼貌性风险提示？
- 价值链是否适配公司类型，而不是硬套供应链？
- 高风险核心结论是否经过交叉验证或降级？
- 本地引用的 PDF/JSON 是否全部来自本轮 `manifest.json`，而不是其它会话的历史下载目录？
- PDF 是否经过渲染和视觉/文本 QA，并写入 `交付QA_YYYYMMDD.md`？
- 正式交付产物是否使用中文 Markdown/PDF/交付 QA 命名？
- 是否避免了 skill 自身的买入、卖出、加仓、减仓、仓位、止损、无脑买等指令性表达？
- 读者是否会觉得这份材料比免费概念整理更值得付费？
