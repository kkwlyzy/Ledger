"""数据模型定义。

使用 dataclass 描述记账软件的核心业务对象：
- Transaction: 一笔收支记录
- Category:     收支分类
- Budget:       月度预算(按分类)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import List, Optional


# 收支类型常量，使用字符串便于 JSON 序列化
TYPE_INCOME = "income"
TYPE_EXPENSE = "expense"
ALL_TYPES = (TYPE_INCOME, TYPE_EXPENSE)


def _new_id() -> str:
    """生成不带连字符的短 uuid。"""
    return uuid.uuid4().hex[:12]


@dataclass
class Category:
    """收支分类。

    name:  显示名称
    type:  income / expense
    color: 用于报表配色，#RRGGBB 字符串
    """
    name: str
    type: str = TYPE_EXPENSE
    color: str = "#7E9BE6"
    id: str = field(default_factory=_new_id)

    @classmethod
    def from_dict(cls, data: dict) -> "Category":
        return cls(
            id=data.get("id") or _new_id(),
            name=data["name"],
            type=data.get("type", TYPE_EXPENSE),
            color=data.get("color", "#7E9BE6"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Transaction:
    """一笔收支记录。

    date: ISO 格式 YYYY-MM-DD
    amount: 金额(正数)
    """
    amount: float
    category_id: str
    type: str = TYPE_EXPENSE
    date: str = field(default_factory=lambda: date.today().isoformat())
    note: str = ""
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        return cls(
            id=data.get("id") or _new_id(),
            amount=float(data["amount"]),
            category_id=data["category_id"],
            type=data.get("type", TYPE_EXPENSE),
            date=data.get("date") or date.today().isoformat(),
            note=data.get("note", ""),
            created_at=data.get("created_at") or datetime.now().isoformat(timespec="seconds"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Budget:
    """月度预算，按分类设置金额上限。

    year_month: YYYY-MM
    """
    year_month: str
    category_id: str
    amount: float
    id: str = field(default_factory=_new_id)

    @classmethod
    def from_dict(cls, data: dict) -> "Budget":
        return cls(
            id=data.get("id") or _new_id(),
            year_month=data["year_month"],
            category_id=data["category_id"],
            amount=float(data["amount"]),
        )

    def to_dict(self) -> dict:
        return asdict(self)
