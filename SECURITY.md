# Security Policy

SoftDoc Pipeline is published mainly as a sanitized public snapshot. It is not operated as a public online service.

## 支持范围

当前优先处理以下类型的安全问题：

- 凭据泄露
- 会话、Cookie、token 暴露
- 未预期的敏感文件暴露
- 可被利用的接口权限问题
- 本地文件读写边界错误

## 报告方式

请不要公开提交安全 issue。

如需联系仓库维护者，请优先通过 GitHub 账号主页私下联系：

- `https://github.com/CommitHu502Craft`

如果你发现的是历史脱敏遗漏、凭据暴露或真实业务数据残留，请不要公开描述具体内容。

## 建议附带的信息

- 问题类型
- 影响范围
- 复现步骤
- 可能的利用方式
- 如有必要，可附最小复现样例

## 响应时间

- 目标是在 `7` 天内首次回复
- 如果问题被确认，会在修复方案明确后继续同步进展

## 处理原则

- 安全问题在修复前不建议公开讨论
- 如果报告中包含密钥、Cookie、账号或真实业务数据，请先做脱敏
