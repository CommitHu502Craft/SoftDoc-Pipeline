# 说明书模板手动补丁（审查版 A03/A04/A05）

适用模板：`templates/manual_template.docx`

目标：把系统自动生成的“审查员可见材料”直接渲染进说明书主文档，避免图文不符和功能无证据。

## 1. 你需要手动改的内容（按当前模板结构）

你的模板当前是：
1. 第一章 系统简介
2. 第二章 系统运行
3. 第三章 系统主要功能

所以不要新增“第九章”。建议新增为：
1. `第四章 审查补充材料`（`Heading 1` 样式）
2. 章节内新增 4 个二级标题（`Heading 2`）：
   - `1. 审查摘要`
   - `2. 功能对应表（A03）`
   - `3. 开发时间说明（A04）`
   - `4. 版本与新增点说明（A05）`
3. 该章建议放在“第三章系统主要功能”与“总结”之间。
4. 将下方占位符放到对应位置（必须一字不差）。

## 2. 占位符清单（直接复制到 Word 模板）

### 2.1 审查摘要（第四章-1）

```
{{ examiner_summary }}
```

### 2.2 功能对应表（A03）（第四章-2）

先插入一个 8 列表格，表头建议：

`序号 | 页面/流程 | 功能声明 | 截图编号 | 接口 | 代码位置 | 运行回放 | 状态`

然后在表头下方插入循环行（建议先用普通循环，稳定性更高）：

```
{% for row in feature_evidence_rows %}
{{ row.index }} | {{ row.page_or_flow }} | {{ row.claim_text }} | {{ row.screenshot_refs }} | {{ row.api_refs }} | {{ row.code_refs }} | {{ row.runtime_refs }} | {{ row.binding_status }}
{% endfor %}
```

如果你不想用表格循环，也可改为纯文本占位：

```
{{ feature_evidence_text }}
```

### 2.3 开发时间说明（A04）（第四章-3）

```
{{ timeline_review_text }}
```

### 2.4 版本与新增点说明（A05）（第四章-4）

先放总结：

```
{{ novelty_review_text }}
```

再放新增点列表：

```
{% for point in version_increment_points %}
{{ loop.index }}. {{ point }}
{% endfor %}
```

## 3. 改完模板后如何验证

1. 运行一次说明书生成。
2. 检查项目目录是否出现：
   - `examiner_material_sections.md`
   - `examiner_material_report.json`
3. 打开生成的 Word，确认“第四章 审查补充材料”已被填充（不是空白占位符）。
4. 若 `examiner_material_report.json` 中 `passed=false`，提交门禁会阻断，并自动触发修复链。

## 4. 常见错误

1. 占位符拼写不一致，导致渲染为空。
2. 使用 `{%tr ... %}` 但位置不在表格行内，会触发模板解析错误（建议统一使用普通 `{% for %}`）。
3. 模板章节名与正文目录样式不匹配，导致目录不更新。

## 5. 可直接粘贴的章节骨架（与你当前模板一致）

```jinja
第四章 审查补充材料

1. 审查摘要
{{ examiner_summary }}

2. 功能对应表（A03）
{% for row in feature_evidence_rows %}
{{ row.index }} | {{ row.page_or_flow }} | {{ row.claim_text }} | {{ row.screenshot_refs }} | {{ row.api_refs }} | {{ row.code_refs }} | {{ row.runtime_refs }} | {{ row.binding_status }}
{% endfor %}

3. 开发时间说明（A04）
{{ timeline_review_text }}

4. 版本与新增点说明（A05）
{{ novelty_review_text }}
{% for point in version_increment_points %}
{{ loop.index }}. {{ point }}
{% endfor %}
```
