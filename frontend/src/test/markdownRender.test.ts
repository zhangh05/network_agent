import { describe, expect, it } from "vitest";
import { renderAssistantHtml } from "../utils/displayText";

describe("assistant markdown rendering", () => {
  it("keeps post-table sections outside the table when later lines still contain pipes", () => {
    const html = renderAssistantHtml([
      "二、数据对比",
      "| 项目 | 数值 | 说明 |",
      "| --- | --- | --- |",
      "| A | 15 | 正常 |",
      "| B | 20 | 稳定 |",
      "",
      "| 数量关系 | 10题 | 保留广东特色的数字推理 |",
      "三、整体趋势总结",
      "从分卷到统一：最大变化发生在2024年。",
    ].join("\n"));

    expect(html.match(/<table>/g)).toHaveLength(1);
    expect(html).toContain("<h3>三、整体趋势总结</h3>");
    expect(html).toContain("<p>从分卷到统一：最大变化发生在2024年。</p>");
    expect(html).not.toContain("<td style=\"text-align:left\">三、整体趋势总结</td>");
  });

  it("preserves empty table cells instead of shifting later columns left", () => {
    const html = renderAssistantHtml([
      "| 项目 | 题量（当前） | 分值 | 趋势 |",
      "| --- | --- | --- | --- |",
      "| 科学推理5题 | 1分/题 |  | 近年题型稳定 |",
      "| 判断推理 | 图形推理5题 |  |  |",
    ].join("\n"));

    expect(html).toContain("<td style=\"text-align:left\">科学推理5题</td>");
    expect(html).toContain("<td style=\"text-align:left\">1分/题</td>");
    expect(html).toContain("<td style=\"text-align:left\"></td>");
    expect(html).toContain("<td style=\"text-align:left\">近年题型稳定</td>");
    expect(html).toContain("<td style=\"text-align:left\">判断推理</td>");
    expect(html).toContain("<td style=\"text-align:left\">图形推理5题</td>");
  });

  it("merges single-cell bullet continuation rows into the previous table row", () => {
    const html = renderAssistantHtml([
      "| 模块 | 题量 | 主要变化趋势 |",
      "| --- | --- | --- |",
      "| 常识判断 | 约15-20题 | 近年来变化最明显： |",
      "| · 政治/时政占比稳定在较高水平，重点考查中央大政方针和国家重大战略 |  |  |",
      "| 资料分析 | 约15-20题 | 考查方式稳定 |",
    ].join("\n"));

    expect(html).toContain('class="report-card"');
    expect(html).toContain("近年来变化最明显：<br />· 政治/时政占比稳定在较高水平");
    expect(html).not.toContain("<table>");
  });

  it("renders loose pipe summary rows as readable fact blocks", () => {
    const html = renderAssistantHtml([
      "| 语言理解与表达 | 约30-35题 | 整体结构稳定，仍是分值占比最大的模块之一 |",
      "| 判断推理 | 约35-40题 | 整体题量占比最大，近年命题呈现综合性趋势 |",
    ].join("\n"));

    expect(html).toContain('class="pipe-card"');
    expect(html).toContain('class="pipe-card-title">语言理解与表达</span>');
    expect(html).toContain('class="pipe-card-meta">约30-35题</span>');
    expect(html).toContain('class="pipe-card-body">整体结构稳定，仍是分值占比最大的模块之一</span>');
    expect(html).not.toContain("| 语言理解与表达 |");
  });

  it("renders report-style module tables as unified cards with attached bullet details", () => {
    const html = renderAssistantHtml([
      "二、近年五大模块题量及知识点变化（当前稳定格局）",
      "| 模块 | 题量（近年联考） | 主要变化趋势 |",
      "| --- | --- | --- |",
      "| 常识判断 | 约15-20题 | 近年来变化最明显： |",
      "· 科技类题目占比持续上升，2026年达到约40%",
      "· 跨学科融合命题成为新趋势，常见如经济与法律、医学与时政结合考查",
      "| 语言理解与表达 | 约30-35题 | 整体结构稳定，仍是分值占比最大的模块之一 |",
      "| 数量关系 | 约10-15题 | 考点保持稳定，以数学运算为主 |",
      "",
      "三、整体趋势总结",
      "**题型稳定，局部创新：** 整体命题框架近八年保持稳定。",
    ].join("\n"));

    expect(html).toContain('class="report-grid"');
    expect(html.match(/class="report-card"/g)).toHaveLength(3);
    expect(html).toContain('class="report-card-title">常识判断</span>');
    expect(html).toContain('class="report-card-meta">约15-20题</span>');
    expect(html).toContain("近年来变化最明显：<br />· 科技类题目占比持续上升");
    expect(html).toContain("<h3>三、整体趋势总结</h3>");
    expect(html).not.toContain("<table>");
  });

  it("renders labeled conclusion paragraphs as scannable insight items", () => {
    const html = renderAssistantHtml([
      "三、整体趋势总结",
      "**题型稳定，局部创新：** 整体命题框架近八年保持稳定。",
      "**难度稳中有升：** 命题对考生的知识广度和综合思维能力要求越来越高。",
      "**紧跟联考趋势：** 广西作为联考省份，题型变化与全国大方向一致。",
    ].join("\n"));

    expect(html).toContain('class="insight-list"');
    expect(html.match(/class="insight-item"/g)).toHaveLength(3);
    expect(html).toContain('class="insight-label">题型稳定，局部创新：</span>');
    expect(html).toContain('class="insight-text">整体命题框架近八年保持稳定。</span>');
    expect(html).not.toContain("<br />**难度稳中有升");
  });
});
