# 瓶颈侦察 v3 · bottleneck-scout-v3

[![CI](https://github.com/callhong/bottleneck-scout-v3/actions/workflows/ci.yml/badge.svg)](https://github.com/callhong/bottleneck-scout-v3/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

把市场叙事、政策变化、技术路线或单个公司，拆成**可验证的价值传导链**，找真正稀缺的**瓶颈节点**，再输出中文投研报告。

它的核心不是堆数据，而是回答一句话：

> 如果这个 thesis 成立，价值到底会通过哪条链路进入收入、利润、现金流或估值重分类？

如果这个项目帮你少走一次低质量调研弯路，欢迎 Star；也欢迎提 Issue/PR，一起优化数据源、报告模板和真实案例流程。

> 仅供研究学习，不构成投资建议。skill 只输出研究评级、证据强度、价格位置、验证窗口和失效条件，不输出买入/卖出/仓位/止损。

## 支持的 Agent

标准结构 skill（`SKILL.md` 带 frontmatter），与具体模型无关。

| Agent / 工具 | 状态 | 用途 |
| --- | --- | --- |
| Codex | 已验证 | 主力执行、代码/脚本/报告交付 |
| Claude Code | 已验证 | 主力执行、独立第二意见 |
| Codex CLI / Claude CLI | 可选 | 交叉验证链路、候选公司和反方证据；不作为默认固定成本 |
| OpenCode Go | 可选 | 三大国产模型发散/红队：DeepSeek、Qwen、MiniMax |
| Cursor / WorkBuddy / trae / qoder | 理论支持，待实测 | 可读标准 skill 的 agent 可尝试使用 |

默认单 agent 就能跑；只有深度研报、主题较宽或高风险事实较多时，才建议打开多模型或 CLI 交叉验证。

## 实战记录

5 个已验证样本均为正，展示口径最高 **+47%**。

| 标的（代码） | 口径 | 比例 |
| --- | --- | ---: |
| 云南锗业（002428） | 区间涨幅 | **+47%** |
| 欧陆通（300870） | 盈亏比例 | **+36%** |
| 中国巨石（600176） | 盈亏比例 | +30% |
| 华海诚科（688535） | 盈亏比例 | +6% |
| 石英股份（603688） | 盈亏比例 | +4% |

<p align="center">
  <img src="examples/cases/screenshots/IMG_5458.PNG" alt="欧陆通行情截图" width="230">
  <br>
  <sub>欧陆通截图：只展示比例口径，不展示金额；完整 2×3 图墙见 <a href="examples/track-record.md">track-record</a>。</sub>
</p>

云南锗业按区间涨幅展示；其它标的均为本人实际持仓盈亏比例（截至约 2026-06），只展示比例，不展示金额。同期报告还点出多只未买入的标的。仅为方法演示，不构成投资建议；过往不预示未来。

## 适合什么

- **主题瓶颈扫描**：AI、液冷、先进封装、出口管制、电子特气、小材料国产替代，谁才是真瓶颈。
- **事件快评**：突发涨价、政策、禁运、财报、订单，对哪些环节利多/利空/中性。
- **A 股映射**：默认优先找 A 股真实暴露，同时诚实列出港股/美股/全球赢家作对照。
- **深度研报**：中文 Markdown + PDF + 交付 QA，首页先给结论，再给证据链和红队反证。

## 快速开始

需要 Python 3.10+。

```bash
git clone https://github.com/callhong/bottleneck-scout-v3.git
cd bottleneck-scout-v3
python3 scripts/validate_skill.py . --skip-git
```

看到 `VALIDATE_SKILL_PASSED` 即表示结构校验通过。

也可以把这句话丢给 Codex / Claude Code：

```text
请把 https://github.com/callhong/bottleneck-scout-v3 安装为本地 skill；
自动 clone 到合适的 skills 目录或创建软链接，并运行
python3 scripts/validate_skill.py . --skip-git 校验。
```

自然语言触发：

```text
$bottleneck-scout-v3 深度分析：高纯度二氧化碳涨价，是否构成 AI 供应链真实瓶颈？
默认 A 股优先，找真实暴露标的；证据不足就剔除，不要硬凑。
输出中文 Markdown/PDF/交付 QA。
```

## 一个案例看流程

案例：**高纯度二氧化碳涨价，是否构成 AI 供应链真实瓶颈？A 股有没有真实暴露标的？**

- 产物：[Markdown](examples/cases/案例_电子级CO2_AI半导体瓶颈深度研报_20260628.md) / [PDF](examples/cases/案例_电子级CO2_AI半导体瓶颈深度研报_20260628.pdf) / [交付 QA](examples/cases/案例_电子级CO2_AI半导体瓶颈交付QA_20260628.md)
- 结论：**高纯/电子级 CO2 是真实半导体材料，但证据不足以证明它已经构成 AI 半导体供应链真实瓶颈；A 股暂无核心研究标的。** 凯美特气为 CO2 收入事件弹性，广钢气体/金宏气体/华特气体为电子级 CO2 观察，其它映射按证据不足降级或剔除。
- 成本：全流程约 **26 分钟**；PDF 9 页；验证来源 13 个；结构化 JSON 26 份；PDF 主口径 15 份（官方公告/年报 8 份、券商研报 7 份）。模型工具未暴露 exact token，只记录 `max_tokens` 上限。

| 阶段 | 做什么 | 数据 / token / 耗时 | 取舍 |
| --- | --- | --- | --- |
| 1. 定义问题 | 区分工业级、食品级、干冰、电子级/高纯 CO2 | 纳入总耗时 | 先拆变量，避免把普通 CO2 涨价误当半导体瓶颈 |
| 2. 可选发散 | DeepSeek、Qwen、MiniMax、Claude CLI 提候选；Codex CLI 超时则跳过 | `max_tokens=3500/模型` | 只当待查清单，不直接进结论 |
| 3. 价值链与取证 | 查 SEMI、Entegris、TSMC、媒体触发源、公司公告/年报 | 验证来源 13 个 | 一手披露优先；韩国涨价仍降级为媒体线索 |
| 4. A 股候选 | 初筛并核验 8 家公司 | 纳入总耗时 | 无 CO2 单品收入、客户、订单证据就降级 |
| 5. 结构化抓取 | 行情、公告、财务、研报、EPS、互动易、价格位置 | 26 份 JSON；脚本抓取约 0 模型 token | 用低 token 数据底座，减少整页网页塞上下文 |
| 6. 红队与闸门 | 多模型攻击“不是核心瓶颈”的结论；跑 Demand / Transmission / Bottleneck / Elasticity | `max_tokens=2500/模型` | 证据不足则写“暂无核心研究”，不硬凑标的 |
| 7. 交付 | Markdown、PDF、交付 QA、manifest | 全流程约 26 分钟 | PDF 与 QA 校验通过后再交付 |

**A 股结构化抓取会抓什么**

```bash
python3 scripts/fetch_a_stock_data.py 688268 \
  --preset deep \
  --download-report-pdfs \
  --pdf-limit 3 \
  --artifact-root reports/runs \
  --topic high_purity_co2_ai
```

| 数据 | 来源 | 用途 |
| --- | --- | --- |
| 行情/市值/估值 | 腾讯财经、东方财富 | 价格位置和估值底座 |
| 公司资料/资金/热度 | 东方财富 | 公司快照、市场温度、拥挤度 |
| 公告/互动易 | 巨潮资讯、互动易 | 公司一手披露和公开口径 |
| 财务报表 | 新浪财经，关键数回公告核验 | 收入、利润、现金流底座 |
| EPS/热榜/涨停原因 | 同花顺 | 估值输入或题材线索 |
| 个股/行业研报 PDF | 东方财富研报 API | 线索和交叉验证，不能替代公告 |

正式研究会写入独立 `reports/runs/<run_id>/manifest.json`。报告只能引用本轮 manifest 里的 JSON/PDF；其它会话旧研报不会被直接扫描复用。同一篇东方财富研报可按 `infoCode` 在 1 天内缓存复用，但仍会写入本轮 manifest 并标记 `reused_from_cache=true`。

<details>
<summary>展开：A 股结构化数据 preset</summary>

| Preset | 什么时候用 | 包含 |
| --- | --- | --- |
| `company`（默认） | 公司事实和估值底座 | `quote, stock-info, announcements, financials` |
| `deep` | 正式深度研报候选公司 | `company + reports, ths-eps-forecast, answered-irm` |
| `leads` | 找题材线索和市场叙事 | 新闻、快讯、概念、热榜、行业研报 |
| `market` | 看交易温度和拥挤度 | 资金流、龙虎榜、涨跌停池、热门股、北向资金 |

`leads` 和 `market` 只能帮助发现线索或解释市场温度，不能单独进入首页核心结论。

</details>

## 输出长什么样

正式深度研报默认交付三件套：

- **Markdown**：第一个二级标题就是 `## 结论`，先给候选排序、证据等级、方向、阶段位置和失效条件。
- **PDF**：把价值传导图、评分分层、红队反证和来源清单渲染成可读版式。
- **交付 QA**：记录数据源、PDF 检查、未解决问题和证据降级原因。

轻量场景（事件快评、复盘验证）只出短结论，不强制 PDF。

## 方法纪律

- **价值传导链优先**：先看价值如何进入收入/利润/估值，而不是直接点股票。
- **瓶颈定位**：找稀缺、难替代、扩产慢、认证强绑定的节点。
- **证据闸门**：五级证据；框架推演封顶 64，待核验线索封顶 49。
- **A 股优先但不硬凑**：真实暴露才进入核心；没有好标的就直接写没有。
- **红队反证**：关键结论必须写失效条件和反方解释。
- **合规边界**：不输出买卖、仓位、止损等交易指令。

## 示例

主示例：

- [示例_AI产业链全链路卡脖子深度研报.md](examples/示例_AI产业链全链路卡脖子深度研报.md)
- [示例_AI产业链全链路卡脖子深度研报.pdf](examples/示例_AI产业链全链路卡脖子深度研报.pdf)

新增实测案例：

- [案例_电子级CO2_AI半导体瓶颈深度研报_20260628.md](examples/cases/案例_电子级CO2_AI半导体瓶颈深度研报_20260628.md)
- [案例_电子级CO2_AI半导体瓶颈深度研报_20260628.pdf](examples/cases/案例_电子级CO2_AI半导体瓶颈深度研报_20260628.pdf)
- [案例_电子级CO2_AI半导体瓶颈交付QA_20260628.md](examples/cases/案例_电子级CO2_AI半导体瓶颈交付QA_20260628.md)

`examples/cases/` 里还有覆铜板涨价、AI 电力、InP 出口管制、先进封装材料等案例。

<details>
<summary>展开：可复制提示词</summary>

```text
$bottleneck-scout-v3 分析【主题/事件/公司】。默认 A 股优先，必要时列全球赢家对照。请先给赛道阶段、该看谁、各自价格位置；再拆价值传导链、真实瓶颈、证据等级、评分封顶、红队反证、失效条件。不要输出买卖/仓位建议；证据不足就降级，不硬凑核心推荐。
```

```text
$bottleneck-scout-v3 做一份 AI 算力硬件瓶颈扫描：从 GPU/服务器需求出发，拆到 PCB、光模块、液冷、电源、功率半导体、先进封装、材料和设备。默认 A 股优先，找低估隐形冠军和小基数高弹性标的；如果没有核心推荐，直接说没有。首页先给结论和赛道阶段。
```

```text
$bottleneck-scout-v3 深度分析：2025 年铟/InP 出口管制、2023 年镓锗管制，对 AI 光通信供应链的真实瓶颈在哪里？默认找 A 股可投标的，区分 InP 衬底、镓锗资源、光芯片、电子特气、泛材料概念。给赛道阶段、A 股候选排序、全球赢家对照、证据等级、评分封顶、价格位置、失效条件，并生成正式中文 Markdown/PDF/交付 QA。
```

```text
$bottleneck-scout-v3 复盘验证：前面关于存储涨价、HBM、DDR/NAND、模组和控制芯片的 thesis 现在是否还成立？比较兆易创新、澜起科技、佰维存储、江波龙、普冉股份、聚辰股份等，按“价格上涨能否进入收入/利润/估值重分类”排序。默认不生成 PDF，输出一次性复盘快照和下一验证窗口。
```

</details>

<details>
<summary>展开：主示例原始提示词</summary>

```text
重新从零做一份《AI 产业链全链路卡脖子深度研报》。不要沿用旧报告、旧 PDF、旧候选排序或旧结论。

我不是要 AI 概念股清单，也不是要一级产业链罗列。请从 AI 需求爆发出发，沿价值传导链向上游和隐蔽环节深挖：算力、服务器、GPU、HBM、光模块、先进封装、PCB、液冷、电力、数据中心、半导体设备，再继续追到材料、气体、化学品、前驱体、容器、储运、纯化、回收、检测、认证、环保、安全、关键工艺和设备部件等更细节点。

必须先做全链路扫描，再收敛到最值得深挖的 5-8 条瓶颈链。不要预设结论，也不要停在“光模块、液冷、先进封装、半导体材料”这种大词。要尽量追到最细分、最难替代、最难扩产、最难认证、供给最集中的节点。

必须使用多模型发散：先让多模型提出候选瓶颈和盲区，但只把它们当作“待验证线索”，所有进入报告的结论都必须重新用公开证据验证。

重点关注但不限于：稀有气体、电子特气、氦氖氙氪、混配气；气体储运、液化、纯化、回收、低温容器、阀门仪表；半导体前驱体、电子化学品、光刻胶配套材料；先进封装材料；ABF/BT/玻璃基板、陶瓷、石英、靶材、CMP、掩膜版、检测量测；光通信上游材料；AI 电力与散热里的细分材料和设备；任何市场讨论不充分但能被证据验证的上游小瓶颈。

每条入选瓶颈链都要回答：AI 需求如何传导；真正卡在哪里；全球供应格局和集中度；国产替代阶段；A 股是否有真实暴露；如果 A 股没有好标的，全球最直接赢家是谁；市场是否已经充分定价；未来 1-4 个季度该跟踪哪些验证信号。

最终特别回答：哪些细分瓶颈最可能被市场低估；哪些瓶颈真实但 A 股没有好标的；哪些 A 股只是概念映射应剔除；哪些公司可能是小基数高弹性或低估值真实暴露；下一阶段最该跟踪哪些验证信号。

默认以 A 股可投标的为主，但必须诚实：真实暴露才进入核心或弹性关注；只有概念映射、没有收入/客户/订单/产能证据的要剔除；瓶颈真实但 A 股无标的，要直接说明。
```

</details>

## 多模型与 OpenCode Go（可选）

默认单 agent 就能完成研究。遇到宽主题、关键事实冲突、候选标的很多时，可以打开多模型发散/红队；它只提供候选和反证，最终仍按公开证据裁决。

```bash
python3 scripts/cross_verify.py --diverge "AI 服务器电源谁最卡"
python3 scripts/cross_verify.py --redteam "公司X份额≥90%"
python3 scripts/cross_verify.py --evidence snapshot.txt "某结论"
```

三大国产模型默认是 `deepseek-v4-pro`、`qwen3.7-max`、`minimax-m3`；Codex CLI / Claude CLI 可作为独立第二意见。任一模型失败、超时或额度不足，都只降级该路结果，不阻塞主流程。

为什么推荐 OpenCode Go：做多模型核验要的是**谱系多样 + 量大管够 + 成本低**。官方当前标价为首月 **$5**、之后 **$10/月**，并提供较宽松的使用额度；模型池覆盖 DeepSeek、Qwen、MiniMax、Kimi、GLM、MiMo 等开源/国产模型，适合用来做候选发散、红队反证和第二意见。价格、模型和额度以官方页面实时展示为准。

OpenCode Go 配置：

```bash
cp config/opencode.env.example config/opencode.env
```

参考文档：<https://opencode.ai/docs/zh-cn/go/>。邀请链接：<https://opencode.ai/go?ref=SS2P5BQPM7>，通过邀请链接订阅通常你我各得 **$5 额度**（以页面实际展示为准）；不用也完全不影响本 skill。

## PDF 渲染

- 默认 WeasyPrint 层级版式；系统依赖缺失时自动降级 ReportLab。
- 交付前运行 `scripts/validate_pdf_layout.py`，检查字体、粘连、股票代码断行、缺字和内部字段。
- `BOTTLENECK_NO_AUTOINSTALL=1` 可关闭自动安装。

## 目录结构

```text
SKILL.md                  主入口与硬规则
README.md                 项目说明与使用入口
NOTICE / LICENSE          开源许可与第三方说明
.github/workflows/        CI
.githooks/                提交前安全检查
agents/                   agent 配置示例
assets/fonts/             PDF 渲染字体资源
config/                   多模型密钥占位，真实密钥本地填
examples/                 示例研报与 track record
examples/cases/           真实案例 Markdown/PDF 与截图
licenses/                 第三方许可证
references/               方法论：路由、价值链、证据闸门、红队、模板
reports/runs/             本地研究 run、manifest 与 PDF 缓存
scripts/                  渲染、校验、价格位置、交叉验证、抓取入口
scripts/data_sources/     A 股结构化公开数据源
tests/fixtures/           测试夹具
```

## 贡献

欢迎提 Issue/PR，尤其欢迎这些方向：

- 修复失效数据源或补充更好的公开数据源。
- 优化报告模板、PDF 版式、QA 检查和证据闸门。
- 增加真实案例复盘，尤其是“证据不足所以剔除”的反例。
- 改进 A 股映射、港美股对照、行业数据和 PDF 解析流程。

提交前建议先跑：

```bash
python3 scripts/validate_skill.py . --skip-git
python3 scripts/test_a_stock_data.py
```

## 安全与隐私

- API 密钥永不进仓库：只发 `.example`，真实密钥已 gitignore。
- 自带提交防护钩子：`git config core.hooksPath .githooks`。
- 个人研究产物（`reports/`）、本地配置不入库。

## 许可 · 致谢 · 免责

Apache-2.0（见 `LICENSE`）。整合了 Apache-2.0 的 [a-stock-data](https://github.com/simonlin1212/a-stock-data) 公开数据端点（见 `NOTICE`），并参考若干开源投研项目的工程纪律，只吸收方法，不吸收语料、人设或交易动作。

再次感谢 Serenity（[@aleabitoreddit](https://x.com/aleabitoreddit)）的瓶颈投研启发，也感谢所有愿意提交数据源修复、案例复盘和模板优化的人。

免责声明：仅供研究学习，不构成任何投资建议；涉及的公司、标的和数字仅为方法演示。投资有风险，决策自负盈亏。
