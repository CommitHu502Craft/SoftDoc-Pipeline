# 项目基因图谱 (Project Genome) 技术规范

## 1. 概述

项目基因图谱（Project Genome）是软著AI生成系统的核心随机化机制。它利用项目名称的MD5哈希值作为随机种子，为每个项目生成一组确定性但差异化极大的配置参数。这组参数（即"基因"）贯穿项目的整个生命周期，确保同一项目每次生成的结果一致，而不同项目之间展现出显著的差异。

## 2. 核心原理

### 2.1 随机种子计算

基因图谱的随机性完全依赖于项目名称，实现"伪随机但确定性"的效果。

```python
# 伪代码逻辑
seed_int = int(md5(project_name).hexdigest()[:8], 16)
random_engine = Random(seed_int)
```

### 2.2 数据流向

1. **生成阶段**：`RandomEngine` -> `ProjectPlanner` -> `project_plan.json`
2. **消费阶段**：`project_plan.json` -> 各个下游生成模块
   - `CodeGenerator`: 读取目标语言和框架
   - `HTMLGenerator`: 读取UI框架和配色
   - `DocumentGenerator`: 读取叙述风格

## 3. Genome 字段结构定义

在 `project_plan.json` 中，`genome` 字段位于根节点，结构如下：

```json
{
  "genome": {
    "project_name": "智慧林业管理系统",  // 原始项目名
    "seed": 28472910,                   // 计算出的整数种子
    "target_language": "Java",          // 目标后端语言
    "ui_framework": "Tailwind",         // 前端UI框架
    "layout_mode": "sidebar-left",      // 页面布局模式
    "narrative_style": "technical",     // 文档叙述风格
    "color_scheme": {                   // 配色方案 (HSL)
      "name": "ocean",
      "primary": "hsl(210, 79%, 46%)",
      "secondary": "hsl(199, 89%, 48%)",
      "accent": "hsl(187, 100%, 42%)",
      "background": "hsl(210, 17%, 98%)",
      "text": "hsl(210, 24%, 16%)",
      "border": "hsl(210, 14%, 89%)",
      "success": "hsl(142, 71%, 45%)",
      "warning": "hsl(45, 93%, 47%)",
      "error": "hsl(0, 65%, 51%)",
      "industry_fit": ["金融", "科技", "医疗"]
    },
    "database_type": "MySQL",           // 数据库类型
    "architecture_pattern": "mvc",      // 架构模式
    "generated_at": "2023-11-02T10:30:00" // 生成时间
  }
}
```

## 4. 参数取值范围

所有参数配置定义在 `config/genome_config.json` 中。

### 4.1 目标语言 (target_language)
- **Java**: Spring Boot (Maven)
- **Python**: FastAPI (Pip)
- **Go**: Gin (Go Modules)
- **Node.js**: Express (npm)
- **PHP**: Laravel (Composer)

### 4.2 UI 框架 (ui_framework)
- **Tailwind**: 实用优先CSS框架
- **Bootstrap**: 经典组件库 (v5.3)

### 4.3 布局模式 (layout_mode)
- **sidebar-left**: 左侧垂直导航（适合管理后台）
- **sidebar-right**: 右侧垂直导航（适合文档类）
- **topbar**: 顶部水平导航（适合门户）
- **mixed**: 混合式导航（适合大型系统）

### 4.4 叙述风格 (narrative_style)
用于 `DocumentGenerator` 生成差异化的说明书文案。
- **technical**: 技术导向，术语丰富，简洁精确
- **business**: 商业导向，强调价值，正式权威
- **tutorial**: 教程导向，步骤详细，友好易懂

### 4.5 配色方案 (color_scheme)
包含 12 种预设主题，覆盖不同行业风格：
- **ocean/cyan/indigo**: 科技、互联网
- **forest/teal**: 农业、环保、健康
- **ruby/rose**: 媒体、时尚、活动
- **amber/slate**: 金融、企业服务、地产

## 5. 下游模块集成指南

### 5.1 代码生成模块 (modules/code_generator.py)
应读取 `genome.target_language` 来决定加载哪个目录下的模板。

```python
# 示例逻辑
lang = plan['genome']['target_language']
if lang == 'Java':
    self._generate_java_code()
elif lang == 'Python':
    self._generate_python_code()
```

### 5.2 HTML 生成模块 (modules/html_generator.py)
应读取 `genome.ui_framework` 和 `genome.color_scheme`。

- 在 HTML `<head>` 中引入对应的 CSS CDN
- 使用 `color_scheme.primary` 等变量设置 ECharts 图表的主题色
- 根据 `layout_mode` 选择不同的 HTML 骨架模板

### 5.3 文档生成模块 (modules/document_generator.py)
应读取 `genome.narrative_style`。

- 传递给 `DocumentDifferentiator`
- 根据风格选择不同的段落模板（如：技术风格用"系统架构"，商业风格用"产品价值"）

## 6. 扩展开发

如需添加新的随机参数：
1. 在 `config/genome_config.json` 中添加配置池。
2. 在 `core/random_engine.py` 中添加对应的 `get_xxx()` 方法。
3. 在 `get_genome()` 方法中注册新字段。
