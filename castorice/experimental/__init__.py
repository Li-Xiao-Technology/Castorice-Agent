"""
实验模块 - 为Agent提供自由探索的空间

包含：
- sandbox.py: 实验沙盒——隔离环境中自由修改代码
"""

from .sandbox import ExperimentalSandbox, ExperimentResult

__all__ = ["ExperimentalSandbox", "ExperimentResult"]