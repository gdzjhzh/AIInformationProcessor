"""专有名词库模块

提供专有名词的加载、查询和 LLM prompt 注入功能。
"""

from .terminology_db import TerminologyDB, get_terminology_db

__all__ = ["TerminologyDB", "get_terminology_db"]
