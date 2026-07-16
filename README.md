# Castorice Agent v2.0

> **自进化智能体** —— 复刻 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 架构设计
> 
> 自研主循环、零 LangGraph 依赖、原生 SDK 对接多模型、一键启动

---

## 项目简介

Castorice Agent 是一个轻量级自进化智能体框架，核心特点：

- **自研主循环**：手写 Agent 执行流程，无 LangGraph 等第三方编排框架依赖
- **原生 SDK 对接**：直接使用 `openai` / `anthropic` 官方 SDK，告别 LangChain 碎片化分包
- **三层记忆系统**：SQLite 短期记忆 + Chroma 长期记忆 + JSON 技能库
- **LLM 驱动工具调用**：让模型决定调用哪个工具、传什么参数，而非硬编码规则
- **一键部署**：Windows 双击 `start.bat` 自动检测环境、创建虚拟环境、安装依赖、启动程序

---

## 一、核心特性

| 维度 | v1.0（LangGraph） | **v2.0（本版本）** |
|------|------------------|-------------------|
| 流程编排 | 依赖 `langgraph` 第三方框架 | **自研** `CastoriceAgent` 主循环 + `State` 数据类 |
| 模型适配 | `langchain-openai` / `langchain-anthropic` 拆分包 | **官方原生 SDK**：`openai` / `anthropic` 直接对接 |
| 依赖管理 | `requirements.txt` + 零散 pip | **`pyproject.toml` + uv**，依赖统一管理 |
| 部署体验 | 手动 `python -m venv` + `pip install -r` | **Windows 双击 `start.bat` 一键完成** |
| 打包分发 | 仅本地运行 | 支持 **pipx 全局安装**、**Docker 容器化** |
| 配置分层 | 密钥与业务配置混在 yaml | `.env` 仅存密钥，`.yaml` 仅存业务配置，职责清晰 |

---

## 二、目录结构

```
Castorice Agent/
├── castorice/                    # 核心包（自研，无 LangGraph 依赖）
│   ├── __init__.py
│   ├── main.py                   # CLI 入口（test / interactive / batch）
│   ├── config.py                 # .env + yaml 统一配置加载器
│   ├── model_adapter.py          # 多模型适配层（OpenAI/Anthropic/Ollama/OpenRouter）
│   ├── agent.py                  # 【核心】自研主循环 Agent
│   │
│   ├── memory/                   # 三层记忆系统
│   │   ├── short_term.py         #   短期记忆（SQLite）
│   │   ├── long_term.py          #   长期记忆（Chroma）
│   │   ├── skill.py              #   技能库（JSON + 版本管理）
│   │   └── user_profile.py       #   用户画像
│   │
│   └── tools/                    # 工具集
│       └── base_tools.py         #   7 个基础工具
│
├── castorice_data/               # 运行时数据（自动生成）
│   ├── sessions.db               #   SQLite 会话库
│   ├── chroma_db/                #   Chroma 向量库
│   ├── skill_library.json        #   技能库
│   ├── user_profile.json         #   用户画像
│   └── castorice.log             #   运行日志
│
├── pyproject.toml                # ★ 统一依赖声明
├── .env.example                  # ★ API 密钥模板
├── castorice_config.yaml         # ★ 业务配置
│
├── start.bat                     # ★ Windows 一键启动
├── install.bat                   #   仅安装不启动
├── Dockerfile                    # ★ Docker 容器化部署
├── docker-compose.yml            #   Docker Compose 编排
│
└── README.md                     #   本文档
```

---

## 三、功能亮点

### 1. LLM 驱动工具调用

Agent 不再依赖硬编码的规则，而是把可用工具列表告诉 LLM，让模型自主决定：
- 调用哪个工具
- 传什么参数
- 是否继续调用还是给出最终答案

### 2. 7 个内置工具

| 工具 | 功能 |
|------|------|
| `web_search` | DuckDuckGo 联网搜索 |
| `get_weather` | **实时天气查询**（wttr.in API，中文描述） |
| `read_file` | 读取文本文件 |
| `write_file` | 写入文件 |
| `terminal` | 执行 shell 命令（带安全拦截） |
| `python_repl` | 执行 Python 代码片段（沙箱隔离） |
| `read_document` | 读取 PDF/Word/Excel 文档 |

### 3. 多模型支持

通过 `.env` 配置即可切换：
- **百度千帆 Token Plan**（OpenAI 协议兼容）
- **阿里云百炼**（OpenAI 协议兼容）
- **OpenAI 官方**
- **Anthropic Claude**
- **Ollama 本地模型**
- **OpenRouter 聚合**

### 4. 三层记忆系统

- **短期记忆**：SQLite 会话管理，支持多会话、归档、摘要
- **长期记忆**：Chroma 向量库，相似度检索历史经验
- **技能库**：JSON 存储，支持触发关键词、版本管理、自动生成

---

## 四、快速开始

### Windows 用户：双击 `start.bat`

脚本自动完成：
1. 检测 Python ≥ 3.10
2. 检测 `uv`（未安装则降级使用 pip）
3. 创建 `venv/` 虚拟环境
4. 一键批量安装所有依赖
5. 检测 `.env`（缺失则从 `.env.example` 复制）
6. 启动交互模式

> **首次运行** 会从 PyPI 拉取依赖，约 2-5 分钟；之后秒开。

### 跨平台安装

```bash
# 方式 1：uv（推荐）
pip install uv
uv venv .venv --python 3.10
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e .

# 方式 2：pip
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 方式 3：pipx 全局安装
pipx install .
castorice

# 方式 4：Docker
docker build -t castorice-agent:2.0 .
docker run -it --rm -v $(pwd)/.env:/app/.env castorice-agent:2.0
```

---

## 五、配置说明

### 1. `.env` —— API 密钥（不要提交到 Git）

```ini
# 默认 LLM 提供商
CASTORICE_LLM_PROVIDER=openai

# 百度千帆（OpenAI 协议）
OPENAI_API_KEY=你的百度千帆key
OPENAI_BASE_URL=https://qianfan.baidubce.com/v2/tokenplan/personal
OPENAI_MODEL=deepseek-v4-pro

# 或 OpenAI 官方
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# Ollama 本地
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
```

### 2. `castorice_config.yaml` —— 业务配置

```yaml
agent:
  name: "Castorice"
  role: "自进化个人智能体"

runtime:
  max_iterations: 10
  enable_reflection: true
  enable_skill_generation: true

memory:
  short_term: { db_path, max_turns }
  long_term:  { persist_directory, top_k }
  skill:      { auto_generate, min_trigger_count }

tools:
  web_search:  { enabled, max_results }
  file_io:    { enabled, allowed_paths }
  terminal:   { enabled }

security:
  sandbox: { enabled, timeout_seconds }
```

---

## 六、运行模式

```bash
# 测试模式：验证 LLM 连接 + 组件状态
python -m castorice.main --mode test

# 交互式终端（默认）
python -m castorice.main --mode interactive
# 终端指令：/help /exit /new /history /skills /profile /clear_memory

# 批量模式
python -m castorice.main --mode batch --input tasks.txt
```

---

## 七、核心架构

```
用户输入
   │
   ▼
CastoriceAgent.run()
   │
   ├── _step_intent()        判断意图（chat / task）
   │
   ├── _step_tool_loop()     LLM 驱动工具调用循环
   │      ├── LLM 决定调用哪个工具
   │      ├── 执行工具
   │      └── LLM 决定继续调用或回答
   │
   ├── _step_answer()        生成最终回答
   │
   ├── _step_reflection()    反思（提取经验）
   │
   ├── _step_memory()        长期记忆归档
   │
   └── _step_skill()         经验转 Skill
```

完整状态用 `State` dataclass 在方法间传递，**无任何 LangGraph 节点/边/状态图概念**。

---

## 八、依赖说明

所有核心依赖统一在 `pyproject.toml` 中声明：

| 依赖 | 用途 |
|------|------|
| `openai` / `anthropic` | LLM 官方 SDK |
| `httpx` | HTTP 客户端 |
| `pyyaml` / `python-dotenv` | 配置加载 |
| `pydantic` | 数据校验 |
| `rich` | 终端美化 |
| `ddgs` | DuckDuckGo 搜索 |
| `chromadb` / `sentence-transformers` | 向量记忆 |
| `pypdf` / `python-docx` / `openpyxl` | 文档解析 |

可选扩展：
- `[ollama]`：Ollama 本地模型支持
- `[im]`：Telegram / Discord 机器人
- `[dev]`：开发调试工具

---

## 九、常见问题

**Q1: 启动报错 `未找到 .env 文件`？**
A: 复制 `.env.example` 为 `.env` 并填入 API Key。

**Q2: 长期记忆 Chroma 初始化失败？**
A: chromadb 已默认安装，首次运行会下载嵌入模型（约 80MB）。若网络受限，会自动降级为 ONNX 默认嵌入。

**Q3: 如何切换模型？**
A: 修改 `.env` 中的 `CASTORICE_LLM_PROVIDER` + 对应 `*_MODEL`，无需改代码。

**Q4: 天气查询返回英文描述？**
A: 新版已内置 60+ 条天气状况中英对照表，自动翻译。若仍有英文，请提 Issue 反馈。

**Q5: 如何添加自定义工具？**
A: 在 `castorice/tools/base_tools.py` 中仿写 `Tool` 类，添加到 `get_base_tools()` 返回列表即可。

---

## 十、许可证

代码完全独立编写，仅参考 Hermes Agent 架构思想。MIT 协议。

---

## 十一、致谢

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) —— 架构设计灵感来源
- [wttr.in](https://wttr.in) —— 免费天气 API
- [DuckDuckGo](https://duckduckgo.com) —— 搜索引擎