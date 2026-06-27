# Source Playbook

## 来源优先级

1. 一手披露与交易所文件：年报、中报、季报、公告、招股书、10-K/10-Q/8-K、问询回复。
2. 监管与政府数据：补贴、招标、采购、出口管制、海关、标准组织、政策原文。
3. 客户/供应商技术文件：认证清单、产品手册、白皮书、会议材料、标准参与。
4. 科学与专利证据：论文、专利、工艺说明；必须连接商业化证据。
5. 可信财经与产业媒体：用于发现线索和时间线，不作为最终证明。
6. 社媒与 KOL：只能作为线索。
7. 无来源传闻：排除。

## A/H/US 映射

- A股：优先交易所公告、巨潮/上交所/深交所、年报/问询回复、招投标与政府数据。
- H股：优先港交所披露易、公司 IR、年报/中报、监管公告。
- US：优先 SEC 10-K/10-Q/8-K、公司 IR、earnings release/call、监管与行业组织。
- 全球赢家与本地映射分开写。海外公司证据强，不等于 A/H 股映射自动成立；A/H 股有政策或供应链位置，也不等于收入会兑现。

## A股数据获取

本仓库已从 `a-stock-data` 复制并改写公开端点逻辑到 `scripts/data_sources/a_stock.py`，调用入口为：

```bash
python3 scripts/fetch_a_stock_data.py 600519 --include quote,stock-info,announcements,reports,financials --output /tmp/600519_snapshot.json
```

默认策略：

- 显式抓取，不做全量扫描；`--include all` 只能在用户明确要求或研究确有必要时使用。
- 不限制死：`fetch_a_stock_data.py` 是 A 股结构化数据入口，不替代浏览器、搜索引擎、交易所官网、公司 IR、监管网站、券商/行业研报网页或其它实时联网查询。
- 需要“最新/今天/刚发布/原文/PDF/网页证据”时，仍按原来方式联网查询并优先引用一手来源。
- 东方财富请求必须走节流 helper，串行请求，不做并发批量轰炸。
- 每个 dataset 都必须带 `source`、`endpoint`、`retrieved`、`evidence_level`、`status` 和 `data`，用于写入报告数据源清单和 QA sidecar。
- 抓取失败时记录 `status=unavailable` 或 `empty`，不得把缺失数据伪装成事实。

已内置数据源：

| Dataset | 来源 | 用途 | 注意 |
| --- | --- | --- | --- |
| `quote` | 腾讯财经 | 价格、PE/PB、市值、换手、涨跌停 | 市场数据需同日或最近交易日 |
| `stock-info` | 东方财富 push2 | 行业、股本、市值、上市日期 | 和腾讯市值可做交叉检查 |
| `reports` | 东方财富 reportapi | 个股研报列表和机构预测线索 | 研报观点不能替代公司公告 |
| `industry-reports` | 东方财富 reportapi | 行业研报列表 | 行业码需先用全行业结果反查 |
| `--download-report-pdfs` | 东方财富 PDF | 可选下载个股/行业研报 PDF | 默认不下载，避免带宽和历史产物堆积 |
| `announcements` | 巨潮资讯 | 公告全文检索 | 优先用于直接证据 |
| `financials` | 新浪财经 | 利润表/资产负债表/现金流量表 | 关键财务数要和年报/公告交叉验证 |
| `concepts` | 东方财富 slist | 板块/概念归属 | 只能做题材定位，不直接证明瓶颈 |
| `kline-ma` | 百度股市通 | K 线和 MA5/MA10/MA20 | 技术位置辅助，不是核心证据 |
| `fund-flow` | 东方财富 push2his | 120 日资金流 | 只作交易热度/资金面背景 |
| `fund-flow-minute` | 东方财富 push2 | 盘中分钟级资金流 | 只作事件热度背景 |
| `margin` | 东方财富 datacenter | 融资融券 | 只作交易热度/风险背景 |
| `block-trade` | 东方财富 datacenter | 大宗交易 | 只作交易结构/筹码背景 |
| `holders` | 东方财富 datacenter | 股东户数 | 只作筹码背景，不能单独成为核心结论 |
| `dividends` | 东方财富 datacenter | 分红送转 | 业务质量与现金回报辅助证据 |
| `dragon-tiger` | 东方财富 datacenter | 个股龙虎榜和席位 | 只作资金/短线情绪背景 |
| `daily-dragon-tiger` | 东方财富 datacenter | 全市场龙虎榜 | 只作市场热度背景 |
| `lockup` | 东方财富 datacenter | 限售解禁 | 用于供给压力和风险验证 |
| `industry-comparison` | 东方财富 clist | 行业涨跌与领涨 | 只作行业轮动背景 |
| `ths-hot` | 同花顺 | 当日强势股题材归因 | 题材线索，需公告/财报核验 |
| `northbound` | 同花顺 | 沪深股通分钟流向 | 资金面背景 |
| `stock-news` | 东方财富搜索 | 个股新闻 | 新闻线索，需更强来源核验 |
| `global-news` | 东方财富快讯 | 7x24 快讯 | 事件线索，需原始来源核验 |

数据源错误模型：

- `NoUsableDataError`：源返回空或不可解析，报告中写“未取得/待验证”。
- `DataSourceRateLimitError`：源限流或封禁，停止批量请求并降级，不换成未经选择的源静默填充。
- `DataSourceUnavailableError`：依赖、网络或配置不可用，写入 QA sidecar。

禁止事项：

- 不默认安装或启用 akshare、baostock、tushare、iwencai、Wind/Choice/iFinD/Bloomberg 等额外数据源。
- 不把资金流、概念归属、龙虎榜或社媒热度当作直接投资结论。
- 不为补齐漂亮表格而编造价格、估值、客户、订单、份额或产能。

## 时效规则

- 股票价格、市值、成交、涨跌、估值：同日或最近交易日。
- 公告与财报：最新年度/中期/季度报告，并查后续重大公告。
- 政策与补贴：最新官方版本。
- 技术标准：最新正式版或公开草案。
- 媒体文章：记录发布日期，并用更高等级来源核验。

## 引用规则

每条来源必须记录：

- title
- publisher
- URL
- published
- retrieved
- source_rank
- exact claim supported
- evidence_level
- confidence

不要引用一个来源去支持它没有直接证明的结论。

## 典型红旗

- 只有“国产替代”“受益行业发展”等文字。
- 公司提到热词，但没有收入、客户、订单或产能。
- 收入真实，但来自低端或无关产品。
- 券商/媒体点名公司，但公司文件没有对应披露。
- 微盘股因社媒传播大涨，没有新增一手证据。
- thesis 依赖一个未披露客户。
