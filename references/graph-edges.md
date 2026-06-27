# Graph Gate

所有链路图必须先有结构化 edges，再渲染为 Mermaid 或 PDF 图形。图不能只是漂亮装饰，它必须承载证据等级和绕开风险。

## Edge Schema

```json
{
  "source": "需求或上游节点",
  "target": "下游或公司节点",
  "relationship": "供应/客户/价值传导/监管/渠道",
  "evidence_level": "直接证据",
  "english_label": "Direct",
  "confidence": "high",
  "citation": "S01",
  "status": "confirmed",
  "bypass_risk": "low",
  "numbers": [
    {
      "metric": "产能",
      "value": "N/A",
      "source": "S01",
      "date": "YYYY-MM-DD",
      "evidence_level": "直接证据"
    }
  ]
}
```

允许值：

- `evidence_level`: `直接证据`、`交叉印证`、`框架推演`、`待核验/线索级`、`无支撑`；兼容内部英文 `Direct`、`Corroborated`、`Framework Inference`、`Unsupported`
- `confidence`: `high`、`medium`、`low`
- `status`: `confirmed`、`inferred`、`hypothesis`、`lead`
- `bypass_risk`: `low`、`medium`、`high`

## 建议拆解图 Gate

正式深度研报可以加入建议拆解图或价值传导剖解图，但必须先判断是否适用。

通过条件：

- 至少能标出一个真实瓶颈节点。
- 至少能说明该节点的卡点来源：产能、工艺、认证、客户、资源、标准、监管或数据优势。
- 瓶颈节点至少有 `交叉印证（Corroborated）` 或更强证据支持；只有 `框架推演` 时默认改用文字说明。
- 图中关键数字必须有来源、日期和证据等级；没有可靠来源写 `N/A` 或 `待验证`。

不适用或证据不足时，不画图，改用 2-3 句文字链路，不需要为省略图单独道歉。

最小可读结构：`需求/事件 -> 瓶颈节点 -> 公开标的映射`。有可靠证据时再展开成本/利润池、竞争格局和证伪条件。

## 图形规则

- 硬件主题：供应链/系统依赖图。
- 软件、医药、能源、消费、金融平台：价值传导图。
- `无支撑（Unsupported）` 边不得支撑核心研究。
- `待核验/线索级` 边不得进入首页核心结论。
- `框架推演` 边可以解释假设链路，但必须标注推演，不能单独支撑核心研究。
- `bypass_risk=high` 的边必须进入 Red-team Gate。
- 最终 PDF 不能露出裸 Mermaid 或代码块。
- 最终 PDF 不能出现 `Graph Gate`、`edges.json`、原始 JSON、英文字段清单或“edge 记录”。这些只属于 sidecar 验证材料。
- PDF 正文用中文投资者语言：`链路证据表`、`起点`、`传导到`、`关系`、`证据等级`、`来源`、`绕开风险`。
- PDF 中的图或表必须能在 1 页内读完；复杂主题可以拆成总链路和关键瓶颈放大图，但不能堆叠装饰性图表。

## 工具

用 `scripts/graph_edges.py edges.json --output graph.md` 验证 edges 并生成 Mermaid。
