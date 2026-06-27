# Output Standards

## 付费级标准

报告要让普通投资者觉得“比免费概念整理更值钱”。最低要求：

- 首页先回答 alpha，而不是先铺行业百科。
- 正式 Markdown/PDF 在元信息后必须先写 `## 结论`，直接列瓶颈结论、推荐/观察标的、方向、期限风格、证据等级、新闻触发背景和失效条件。
- 首页结论表默认 3-5 行，一行只放一个公开标的和一个代码；不要把多家公司、多代码合并到同一格，避免首屏挤压和股票代码断行。
- 明确区分已验证、待验证、无支持。
- 每个核心候选都有财务传导和反证。
- 链路图不是装饰，必须能解释价值如何进入公司。
- 每个进入观察的公开标的都要有方向判断字段，并在正式 Markdown/PDF 中按固定颜色展示：看多红、看空绿、中性灰、待验证/双向橙。
- 标准/深度模式的公开标的要有 `target_price_range`、`target_time_horizon`、`target_price_basis`；证据不足时写 `N/A`，不得编造数字。
- 正式深度研报必须包含评分分层：30/30/25/15 的研究强度分、证据封顶、扣分项和失效条件。
- `待核验/线索级` 不得进入首页核心结论；`框架推演` 最高 64 分，`待核验/线索级` 最高 49 分，`无支撑` 不给分。
- 正文只能出现投资者语言，不得出现 `Graph Gate`、`edges.json`、`source/target/relationship/evidence_level` 这类内部流程痕迹。
- 剔除名单要有用，说明为什么热门名字不能进入核心研究。
- 跟踪清单能指导未来 1-4 个季度继续验证。
- 不输出买入、卖出、加仓、减仓、仓位、止损、无脑买等指令性建议；引用、否定、合规说明语境可以出现相关词，但必须明确不是本报告建议。

## Markdown QA

正式深度研报必须有：

- `结论`
- `报告摘要`
- `提问背景`
- `叙事逻辑`
- `投资者答案`
- `评分分层与证据封顶`
- `价值传导链` 或 `供应链地图`
- `Chokepoint Quick Filter`
- `公司证据与财务传导`
- `红队与硬性否决`
- `附录：来源清单`
- `directional_bias`、`research_rating`、`expected_price_reaction`、`invalidation_condition`
- `target_price_range`、`target_time_horizon`、`target_price_basis`（若证据不足可写 `N/A`）

深度/PDF 还必须有：

- 投资者可读的链路证据表或价值传导图；结构化 edges 作为 sidecar/验证材料，不要写进正式 PDF 正文。
- 高风险交叉验证记录或降级说明。
- PDF 渲染命令和 PDF QA 结果应记录在 sidecar 验证摘要或交付说明中，不要污染正式投资者报告正文。

事件快评和普通复盘验证不强制完整评分表、PDF 或交付 QA；只有用户明确要求正式交付、PDF 或保存版时才升级为深度瓶颈研报契约。

## 中文命名与交付收敛

正式深度研报默认只登记 3 个主产物：

- 中文 Markdown：`{中文主题}深度研报_YYYYMMDD.md`
- 中文 PDF：`{中文主题}深度研报_YYYYMMDD.pdf`
- 中文 QA sidecar：`交付QA_YYYYMMDD.md`

可选或内部 sidecar 可以使用中文名，例如 `证据清单_YYYYMMDD.json`、`价值传导链_YYYYMMDD.json`、`价值传导剖解图_YYYYMMDD.md`、`价格位置分析_YYYYMMDD.md`、`观点复盘快照_YYYYMMDD.md`、`催化验证日历_YYYYMMDD.md`、`数据源清单_YYYYMMDD.md`。这些不默认算主交付物。

`研究提纲/待验证版` 默认只交付 Markdown。用户明确要求 PDF 时可以生成，但标题、首页和 QA 必须显著标注“待验证版/非正式研报”。

## 交付 QA sidecar

`交付QA_YYYYMMDD.md` 默认包含：

- 交付状态：Markdown、PDF、PDF 版式检查、证据清单、价值传导链、建议拆解图是否完成或不适用。
- 核心闸门：首页结论、交易话术、证据等级、待核验线索、目标价依据、裸 Mermaid/内部字段是否通过。
- QA 问题清单：`Severity / Category / Issue / Suggested Fix / Status`。
- 本报告数据源清单：来源、用途、日期、证据等级、状态和 fallback。
- PDF 检查摘要：页数、字体、首页结论、股票代码断行、粘连、缺字方块、图表可读性、预览图目录。
- 降级与例外：是否为待验证版、是否用户要求待验证 PDF、未获取数据和对结论的影响。

Severity 口径：`Critical` 影响核心结论、合规边界或 PDF 是否可交付；`Warning` 需要降级、标注或补证；`Info` 是版式、命名、可读性或后续优化。

## PDF QA

正式 PDF 必须：

- 默认用 `scripts/render_pdf.py <report.md> <report.pdf>` 渲染；默认不生成目录，让第一页承载关键结果。
- 只有用户明确需要目录或报告归档需要目录时，才使用 `--toc-mode auto` 或 `--toc-mode always`。
- 普通 Markdown 分隔线 `---` 不得触发分页；只有显式 `<!-- pagebreak -->` 才允许强制分页。
- 用 `scripts/validate_pdf_layout.py <report.pdf> --render-dir <check_dir>` 验证并生成页面预览。
- 目录不是默认交付要求；如开启目录，必须是真实目录，不得出现股票代码断行或点状引导符异常。
- 不出现裸 Mermaid、flowchart 代码、机器时间戳、数字粘连、股票代码断行。
- 不出现缺字方块或无法复制的乱码。
- 不出现内部流程痕迹：`Graph Gate`、`edge 记录`、`edges.json`、`source, target`、`source、target`、`relationship`、`evidence_level`、`bypass_risk`。
- `作者：Lh` 只低调出现在报告元信息，不重复污染页眉页脚。
- 任何已经存在的 PDF 文件也必须重新跑布局 QA；不能因为文件存在就登记为已完成或进入二次推送。

## 正式交付识别

以下表达默认视为正式交付，进入深度/PDF，除非用户明确说快速、初筛或不要 PDF：

- `投资标的分析`
- `中国投资标的分析`
- `可投标的分析`
- `深度分析`
- `付费级分析`
- `正式研报`
- `可保存材料`

以下表达默认轻量，不强制 PDF、完整评分表或交付 QA：

- `事件快评`
- `这条新闻利好谁`
- `这个政策怎么看`
- `财报后验证`
- `观点复盘`
- `催化日历`
- `快速初筛`

## 失败处理

- PDF 渲染失败：交付 Markdown、失败命令、失败原因。
- PDF QA 失败：修复后重跑；如果无法修复，不得声称 PDF 完成，也不得登记为已完成产物。
- 来源不足：降级结论并列出必须补的来源；`待核验`、`线索级`、`Unsupported` 来源不得计入来源数量。
- 高风险未交叉验证：不得给 `核心研究`。
- 正式深度研报无法检索关键事实：降级为 `研究提纲/待验证版`，默认只交付 Markdown。

## 数据源清单与抓取边界

- A 股公开数据抓取使用 `scripts/fetch_a_stock_data.py`，它是从 `a-stock-data` 复制并改写到本仓库的显式工具，不运行时引用外部项目。
- 它是结构化抓取入口，不是唯一证据入口；仍可按原流程联网搜索、浏览官网、交易所、公司 IR、监管页面、行业报告和新闻原文。
- 报告引用抓取结果时，必须把每个 dataset 的 `source`、`endpoint`、`retrieved`、`evidence_level`、`status` 写进数据源清单或 `交付QA_YYYYMMDD.md`。
- `status=empty/unavailable` 只能触发降级、N/A 或待验证，不能算作已验证来源。
- `--include all` 不是默认流程；只在用户明确要求或正式深度研报确有必要时使用，并应说明为什么需要扩展抓取。
- 默认不启用 UZI/TradingAgents/ai-berkshire 等项目的多 provider、多 agent、全量扫描或交易流程。

## 默认成本边界

默认仍为单 agent 高质量研究。不要把多 agent、多模型、全量数据源扫描或付费数据源调用写成固定前置步骤；只有高风险事实冲突、不可信资料隔离或用户明确要求时，才作为可选核验手段。
