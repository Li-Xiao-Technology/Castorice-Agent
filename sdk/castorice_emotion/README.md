# Castorice Emotion SDK

> 情感计算与元认知引擎 —— 让任意 Agent 拥有"有性格、会反思"的能力

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 简介

Castorice Emotion SDK 是从 [Castorice Agent](https://github.com/castorice/castorice-agent) 解耦的独立情感计算与元认知引擎，可被任意 Python Agent 框架集成（NoneBot2 / Koishi / 自研客服系统等）。

### 核心能力

**L1-L4 情感系统**：
- L1 静态人格（性格设定 prompt）
- L2 PAD 三维状态机（Pleasure/Arousal/Dominance，带衰减）
- L3 决策影响（情绪影响工具选择/工作流/元认知阈值）
- L4 共情记忆（情感事件归档 + 主动关心）

**元认知模块**：
- 置信度评估（工具证据 + 不确定性词汇 + 推理质量 + 幻觉风险）
- 一致性检测（前后回答矛盾检测）
- 推理链追踪（deque 滑动窗口）
- 自我修正建议

## 安装

```bash
# 从源码安装（开发模式）
cd sdk/castorice_emotion
pip install -e .

# 或从 PyPI 安装（发布后）
pip install castorice-emotion
```

## 快速开始

### 情感引擎

```python
from castorice_emotion import EmotionEngine

engine = EmotionEngine(
    storage_path="./emotion_state.json",  # 持久化路径
    enabled=True,
)
engine.load()

# 检测用户情绪并更新状态
result = engine.update("我今天好开心啊！")
print(result)
# {"emotion": "happy", "keywords": ["开心"], "is_followup": False}

# 获取情绪 prompt（注入到 LLM system prompt）
print(engine.get_emotion_prompt())

# 获取性格 prompt
print(engine.get_personality_prompt())

# 持久化
engine.save()
```

### 元认知反思

```python
from castorice_emotion import Metacognition

meta = Metacognition()

# 评估回答置信度
assessment = meta.assess_confidence(
    answer="根据最新数据，今天是周五。",
    tool_results=["2026-07-18 是周六"],
    has_tools=True,
)
print(f"置信度: {assessment.overall_score}")
print(f"幻觉风险: {assessment.hallucination_risk}")

# 一致性检测
result = meta.check_consistency(
    new_answer="今天是周六",
    previous_answers=["今天是周五"],
)
print(f"一致性: {result['consistent']}")
```

### 角色卡

```python
from castorice_emotion import CharacterCard, CharacterCardLoader

loader = CharacterCardLoader("./characters")
loader.load_all()

# 列出所有角色卡
for card in loader.list_cards():
    print(f"{card['id']}: {card['name']} - {card['description']}")

# 应用角色卡到引擎
card = loader.get_card("tsundere_castorice")
card.apply_to_emotion_engine(engine)
```

## 角色卡 JSON 格式

```json
{
  "id": "tsundere_castorice",
  "name": "Castorice",
  "nickname": "小傲娇",
  "version": "1.0.0",
  "description": "默认傲娇性格",
  "personality_prompt": "## 你的性格设定\n你是 Castorice...",
  "initial_emotion": {
    "pleasure": 0.6,
    "arousal": 0.3,
    "dominance": 0.5
  },
  "emotion_keywords": {
    "开心": ["开心", "高兴", "快乐"]
  },
  "emotion_emojis": {
    "开心": "❤️"
  },
  "voice_style": {
    "颜文字": ["(´• ω •`)"],
    "语气词": ["嗯...", "哎呀"]
  },
  "refuse_tools_when_low": ["generate_image"]
}
```

## 集成示例

### 集成到 NoneBot2

```python
from castorice_emotion import EmotionEngine
from nonebot import on_message

engine = EmotionEngine(storage_path="./emotion.json")
engine.load()

@on_message()
async def handle_message(event):
    emotion = engine.update(event.get_plaintext())
    # 根据 emotion 调整回复风格...
    engine.save()
```

### 集成到自定义 Agent

```python
from castorice_emotion import EmotionEngine, Metacognition

class MyAgent:
    def __init__(self):
        self.emotion = EmotionEngine(storage_path="./emotion.json")
        self.emotion.load()
        self.meta = Metacognition()

    async def chat(self, user_input: str) -> str:
        # 1. 情感更新
        self.emotion.update(user_input)

        # 2. 构建 system prompt（注入性格 + 情绪）
        system_prompt = (
            self.emotion.get_personality_prompt()
            + "\n" + self.emotion.get_emotion_prompt()
        )

        # 3. 调用 LLM
        answer = await self.llm_call(system_prompt, user_input)

        # 4. 元认知反思
        assessment = self.meta.assess_confidence(answer)
        if assessment.overall_score < 0.4:
            answer += "\n\n（注：我对这个回答不太确定，建议核实）"

        # 5. 持久化
        self.emotion.save()
        return answer
```

## API 文档

### EmotionEngine

| 方法 | 说明 |
|------|------|
| `load()` | 加载持久化状态 |
| `save()` | 保存状态到 JSON |
| `update(user_input, task_success=None, is_followup=False)` | 更新情感状态 |
| `get_emotion_prompt()` | 获取情绪 prompt（注入 LLM） |
| `get_personality_prompt()` | 获取性格 prompt |
| `should_refuse_tool(tool_name)` | 判断是否拒绝工具（低情绪时） |
| `get_workflow_adjustment()` | 获取工作流调整建议 |

### Metacognition

| 方法 | 说明 |
|------|------|
| `assess_confidence(answer, tool_results, has_tools)` | 评估置信度 |
| `check_consistency(new_answer, previous_answers)` | 一致性检测 |
| `record_reasoning(description, evidence, confidence)` | 记录推理步骤 |
| `record_claim(claim, evidence, confidence)` | 记录事实声明 |
| `assess_quality(answer, user_input, tool_results)` | 评估回答质量 |

## License

MIT
