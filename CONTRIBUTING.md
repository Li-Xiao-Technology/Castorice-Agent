# 贡献指南

感谢你考虑为 Castorice Agent 贡献代码或反馈！这是一个个人独立开发的项目，任何形式的帮助都欢迎。

## 🐛 报告 Bug

1. 先搜索 [现有 Issue](https://github.com/Li-Xiao-Technology/Castorice-Agent/issues) 确认没人报过
2. 点击 [New Issue](https://github.com/Li-Xiao-Technology/Castorice-Agent/issues/new/choose)，选择「🐛 Bug 报告」模板
3. 尽量填全模板字段，尤其是**复现步骤**和**环境信息**

> ⚠️ 如果是安全漏洞，请勿开公开 Issue，参考 [SECURITY.md](../SECURITY.md) 的私密报告流程。

## 💡 功能建议

同样通过 [New Issue](https://github.com/Li-Xiao-Technology/Castorice-Agent/issues/new/choose) → 「💡 功能建议」提交。请说清楚你的使用场景和期望的方案。

## 🔧 提交代码

### 开发环境搭建

```bash
git clone https://github.com/Li-Xiao-Technology/Castorice-Agent.git
cd Castorice-Agent
pip install -e ".[http,dev]"
```

### 代码规范

- 使用 **Ruff** 做 lint：`ruff check .`
- 使用 **Black** 风格格式化（Ruff 自带）
- Python 版本最低支持 **3.10**
- 类型标注尽量补全（重要接口必须，内部辅助函数可省略）

### Commit Message 规范

```
feat:     新功能
fix:      Bug 修复
docs:     文档变更
refactor: 重构（不改功能）
chore:    构建 / 依赖 / 杂项
```

示例：`feat: 支持自定义供应商的 Base URL 前缀`

### PR 流程

1. Fork 仓库 → 新建分支（`feat-xxx` / `fix-xxx`）
2. 改代码，跑 `ruff check .`
3. 填写 PR 模板的自检清单
4. 如果关联了 Issue，在 PR 描述里写 `Closes #编号`
5. 等待 Review

### 注意事项

- **不要在代码、日志、commit 里泄露 API Key** 或任何个人凭据
- 不要提交 `.env`、`personastore/`、`venv/`、构建产物等本地文件（`.gitignore` 已覆盖，但请留意）
- 如果改动涉及架构调整，建议先开 Issue 讨论方向，再动手写代码

## 🌐 项目官网

官网源码在 `docs/index.html`，是单页静态站，改完 push 到 main 即会自动部署到 GitHub Pages。

## 📮 联系

- 一般问题：[Issue](https://github.com/Li-Xiao-Technology/Castorice-Agent/issues)
- 开放讨论：[Discussions](https://github.com/Li-Xiao-Technology/Castorice-Agent/discussions)
- 安全问题：lixiao@acyam.top（见 [SECURITY.md](../SECURITY.md)）

---

再次感谢你的贡献 🙏
