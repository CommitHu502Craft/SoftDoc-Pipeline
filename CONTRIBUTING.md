# Contributing

感谢你考虑为 SoftDoc Pipeline 做贡献。这个公开仓库目前更偏源码展示和结构参考，提交前请先确认改动范围，并尽量保持变更聚焦。

## 开始之前

建议先阅读以下文件：

- `README.md`
- `docs/V2.1_ARCHITECTURE.md`
- `docs/V2.2_PROCESS_UPGRADE.md`

如果你的改动会影响生成流程、配置格式、输出产物或 API，请先开 issue 讨论，再开始实现。

## 本地运行

说明：本仓库已做公开化裁剪，不保证所有流程在脱敏状态下都可直接运行。以下步骤仅供需要本地研究代码时参考。

### Python 环境

```powershell
uv venv .venv
.\.venv\Scripts\activate
uv pip install -r requirements.txt
playwright install chromium
```

### 启动 API

```powershell
uv run python run_api.py
```

### 启动桌面端

```powershell
uv run python gui/app.py
```

### 启动 Web UI

```powershell
cd web_ui
npm install
npm run dev
```

## 提交前检查

提交 PR 前请至少完成下面这些检查：

- 只提交和当前目标相关的改动
- 不要提交真实 `API Key`、账号密码、Cookie、token、浏览器会话
- 不要提交 `output/`、`temp_build/`、`logs/`、`data/` 中的运行态数据
- 如果环境允许，改了 Python 逻辑后建议至少运行一次 `pytest -q`
- 如果环境允许，改了 `web_ui/` 后建议至少运行一次 `npm run build`
- 如果改了 API、配置或输出结构，请同步更新 README 或相关文档

## Commit 与 PR 约定

不强制使用复杂的提交规范，但请遵守下面几点：

- 一个 PR 只解决一类问题
- commit message 写清楚“改了什么”
- PR 标题尽量直接，例如：`fix: handle missing browser session file`
- PR 描述至少说明：
  - 改了什么
  - 为什么改
  - 怎么验证
  - 是否影响配置、API、模板或输出产物

## Issue 与 PR 的期望方式

默认建议：

- `Bug 修复`：先提 issue，再提 PR
- `新功能`：先提 issue 讨论
- `小型文档修正`、`明显拼写错误`、`注释修复`：可以直接提 PR

如果改动会影响以下任一项，请不要直接提大 PR：

- 流水线阶段定义
- 配置文件结构
- 数据文件格式
- API 路由或响应字段
- 模板占位符

## 欢迎的 Issue

- 可稳定复现的 bug
- 文档缺失或说明不准确
- 测试失败或兼容性问题
- 性能问题
- 可论证的架构改进建议

## 不建议直接提交的内容

- 无法复现、没有上下文的“不能用”
- 含真实密钥、账号、Cookie、项目数据的截图或日志
- 大范围无说明重构
- 把个人环境、生成产物或本地缓存一起提交

## 安全问题

如果你发现的是安全问题，不要公开提 issue。请阅读 `SECURITY.md`。
