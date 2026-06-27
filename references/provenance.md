# Provenance

## 吸收来源

- Serenity / chokepoint 投研类 skills 的方法论纪律（只吸收方法，不吸收语料与人设）。
- 老版 bottleneck-scout 的工作流、来源纪律、PDF 脚本、价格位置、报告模板。
- 一批开源量化/投研项目的工程纪律（数据源错误分类、provider fallback、交付 QA、事实/推演分离等），明细见 `references/third-party-notices.md`。

## 吸收内容

- 请求路由与轻量/标准/深度模式。
- 证据等级与来源库存。
- Demand / Transmission / Bottleneck / Elasticity 四问过滤。
- design-out、二供、稀释、估值透支、报表不落地等红队闸门。
- 结构化 edges，再渲染链路图。
- 高风险自动交叉验证或降级。
- 价值传导链，覆盖硬件、软件、医药、能源、消费、金融平台。
- 老版中文机构风格、价格位置、PDF 渲染和排版校验。
- zhengxi-views 的方法论纪律：可溯源回答、原话与推演分离、言行对照、语料外声明。
- Anthropic financial-services 的工程纪律：任务入口分层、观点复盘快照、催化验证日历、QA findings table、数据源清单和权限边界。
- a-stock-data 的 A 股公开数据获取方式：腾讯行情、东方财富研报/股本/板块/资金/融资融券/股东户数/分红、巨潮公告、 新浪三表，并改写成本仓库 `scripts/data_sources/a_stock.py` 与 `scripts/fetch_a_stock_data.py`，不再运行时引用外部项目。
- TradingAgents 的行为型数据源错误模型：`NoUsableData`、`RateLimit`、`NotConfigured/Unavailable` 这类按路由反应分类的错误，不吸收其交易 agent 流程。
- UZI-Skill 的 provider health、fallback 纪律和 trap 检查清单思路；不吸收其多 investor panel、HTML war report、DCF/LBO、仓位或交易建议模板。
- ai-berkshire 的财务数据交叉验证、手算市值校验、业务质量 checklist 思路；不吸收其收益展示、Kelly/仓位、多 agent 团队或买卖话术。
- buffett-skills 的护城河、现金转换、管理层诚信、owner earnings 等业务质量问题清单；不吸收 “recommended buy price / sell / hold” 等动作性输出。

## 明确未吸收

- Serenity 人格、口吻、身份扮演或表达 DNA。
- 自述收益、粉丝数、截图、胜率。
- 仓位建议、Kelly sizing、个性化买卖命令。
- KOL 热度或社媒 price action 作为核心推荐依据。
- 占位结构数据伪装成真实市场结论。
- Monte Carlo / EV stress 主流程。
- 郑希个人语料、基金数据、基金经理人设、模仿口吻或个人观点库问答。
- 投行式 DCF/LBO/三表模型、30-50 页 initiation report、固定 25 张图或固定 1 万字指标。
- trade ideas、stop-loss、increase、trim、exit、组合再平衡等交易动作和仓位话术。
- 默认多 agent、多模型投票、全量数据源扫描或付费数据源调用。
- a-stock-data 之外的外部仓库代码、报告正文、截图、人物语料、基金数据和历史产物。
- UZI/TradingAgents/ai-berkshire 的交易执行、组合再平衡、buy zone、stop loss、仓位 sizing、returns marketing 或固定多 agent 架构。
- financial-services 的 LSEG/S&P 等付费 connector、托管 agent cookbook、30-50 页 initiation report 和强制 XLS/PPT/DOCX 交付。

## quant 项目吸收矩阵

| 项目 | 已读入口/关键文件 | 吸收 | 不吸收 |
| --- | --- | --- | --- |
| `a-stock-data` | `SKILL.md`、`README.md`、`LICENSE` | 复制/改写公开数据端点为本仓库 Python 模块，保留 Apache-2.0 归属 | 运行时引用外部目录、iwencai key、全量高频抓取 |
| `TradingAgents` | `dataflows/errors.py`、`tests/test_vendor_errors.py`、`tests/test_vendor_routing.py` | 数据源错误分类、显式 vendor chain、不静默吞错 | 多 agent trader、portfolio/risk debater、交易图 |
| `UZI-Skill` | `SKILL.md`、`docs/DATA-PROVIDERS.md`、`data-contracts.md`、`trap-detector/SKILL.md` | provider 健康度、fallback 纪律、来源契约、风险推广检测清单 | 65 投资人投票、DCF/LBO、rebalance、HTML 战报、买卖/仓位 |
| `financial-services` | `initiating-coverage/SKILL.md`、`quality-checklist.md` | 单任务闸门、交付 QA、source/date/hyperlink discipline | 托管多 agent、付费 connector、投行三表/PPT/DOCX 全流程 |
| `ai-berkshire` | `CLAUDE.md`、`README.md` | 财务数据双源核对、事实/观点区分、业务质量问题 | 收益宣传、四大师多 agent、Kelly/仓位、买入价/卖出价话术 |
| `buffett-skills` | `SKILL.md`、`03-business-moat.md`、`05-financial-metrics.md` | 护城河、现金转换、owner earnings、管理层诚信问题 | Buffett 人格化决策、buy/sell/hold/recommended price |
| `serenity-skill` | `SKILL.md` | 先排产业链层级再排公司、scarce layer 工作流 | 人格/口吻/身份包装 |
| `zhengxi-views` | `SKILL.md` | 原话、事实、框架推演、待核验分离 | 郑希语料、基金数据、口吻模拟、观点库问答 |

## 原因

v2 的目标不是复制某个 KOL，而是把有价值的研究流程制度化：证据优先、可降级、可反证、可复用、能产出普通投资者愿意付费的中文投研。

## 吸收边界

- 外部项目只吸收方法论和工程纪律，不吸收原文语料、人物风格、观点库或交易动作。
- 默认路径保持轻量：普通问题不启动多 agent、多模型或全量数据扫描。
- 深度路径只在用户明确要求正式交付、证据冲突、高风险事实核验或 PDF 交付时，加深检索、反证和 QA。
- 正式输出必须能说明用了哪些来源、哪些推演、哪些校验，不靠堆文本制造“深度感”。
- 第三方代码归属见 [third-party-notices.md](third-party-notices.md)；后续若继续复制外部代码，必须同步记录来源、许可证、改写范围和测试方式。
