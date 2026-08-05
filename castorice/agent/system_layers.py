"""
SystemLayers 聚合器 —— 解决 CastoriceAgent God Object 问题

将 15+ 子系统引用按逻辑分组为 4 层：
- cognitive_layer:  认知层（自我感知、元认知、思考策略、对话策略）
- planning_layer:   规划层（任务规划、任务执行、工作流选择）
- memory_layer:     记忆层（短期记忆、长期记忆、统一检索、意图追踪、自传体、技能记忆）
- evolution_layer:  进化层（情感引擎、经历日志、自我概念、反思引擎、动机系统、行动队列、社会关系、工具学习）

使用方式：
    # 新代码推荐
    agent.layers.evolution_layer.emotion_engine

    # 旧代码兼容（self.xxx 属性仍然保留）
    agent.emotion_engine
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class CognitiveLayer:
    self_awareness: Any = None
    metacognition: Any = None
    thinking_strategy: Any = None
    dialogue_strategy: Any = None


@dataclass
class PlanningLayer:
    task_planner: Any = None
    task_executor: Any = None
    workflow_selector: Any = None


@dataclass
class MemoryLayer:
    short_term: Any = None
    long_term: Any = None
    unified_memory: Any = None
    intent_tracker: Any = None
    autobiographical: Any = None
    skill_memory: Any = None


@dataclass
class EvolutionLayer:
    emotion_engine: Any = None
    experience_journal: Any = None
    self_concept: Any = None
    reflection_engine: Any = None
    motivation_system: Any = None
    action_queue: Any = None
    social_relation: Any = None
    tool_learning: Any = None


@dataclass
class SystemLayers:
    cognitive_layer: CognitiveLayer = field(default_factory=CognitiveLayer)
    planning_layer: PlanningLayer = field(default_factory=PlanningLayer)
    memory_layer: MemoryLayer = field(default_factory=MemoryLayer)
    evolution_layer: EvolutionLayer = field(default_factory=EvolutionLayer)

    def to_dict(self) -> Dict[str, Any]:
        return {
            # cognitive_layer
            "self_awareness": self.cognitive_layer.self_awareness,
            "metacognition": self.cognitive_layer.metacognition,
            "thinking_strategy": self.cognitive_layer.thinking_strategy,
            "dialogue_strategy": self.cognitive_layer.dialogue_strategy,
            # planning_layer
            "task_planner": self.planning_layer.task_planner,
            "task_executor": self.planning_layer.task_executor,
            "workflow_selector": self.planning_layer.workflow_selector,
            # memory_layer
            "short_term": self.memory_layer.short_term,
            "long_term": self.memory_layer.long_term,
            "unified_memory": self.memory_layer.unified_memory,
            "intent_tracker": self.memory_layer.intent_tracker,
            "autobiographical": self.memory_layer.autobiographical,
            "skill_memory": self.memory_layer.skill_memory,
            # evolution_layer
            "emotion_engine": self.evolution_layer.emotion_engine,
            "experience_journal": self.evolution_layer.experience_journal,
            "self_concept": self.evolution_layer.self_concept,
            "reflection_engine": self.evolution_layer.reflection_engine,
            "motivation_system": self.evolution_layer.motivation_system,
            "action_queue": self.evolution_layer.action_queue,
            "social_relation": self.evolution_layer.social_relation,
            "tool_learning": self.evolution_layer.tool_learning,
        }