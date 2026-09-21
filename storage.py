"""数据持久化层。

使用 JSON 文件存储交易、分类、预算三类数据。
所有文件保存在项目根目录下的 data/ 子目录中，首次运行时自动创建目录并写入默认分类。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional

from models import (
    ALL_TYPES,
    TYPE_EXPENSE,
    TYPE_INCOME,
    Budget,
    Category,
    Transaction,
    _new_id,
)


# 数据目录解析：
# - 开发模式(从源码运行)：项目根目录/data
# - 打包模式(PyInstaller)：exe 同级目录/data，方便用户读写与备份
import sys as _sys
if getattr(_sys, "frozen", False):
    # PyInstaller 打包后：sys.executable 是 exe 路径
    BASE_DIR = os.path.dirname(_sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

_TRANSACTIONS_FILE = os.path.join(DATA_DIR, "transactions.json")
_CATEGORIES_FILE = os.path.join(DATA_DIR, "categories.json")
_BUDGETS_FILE = os.path.join(DATA_DIR, "budgets.json")
_SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


# 默认设置
DEFAULT_SETTINGS: Dict = {
    "payday": 8,  # 发薪日，1~28 之间的整数
}

# 异地备份目录(每次保存时同步一份带时间戳的历史版本)
REMOTE_BACKUP_DIR = r"D:\system storage\systemStorage\配分json"
REMOTE_BACKUP_HISTORY_DIR = os.path.join(REMOTE_BACKUP_DIR, "backup")
_MAX_REMOTE_BACKUPS = 20


def _remote_backup(path: str) -> None:
    """把指定文件以带时间戳的形式复制到异地备份目录。

    - 最新快照：覆盖式写入 REMOTE_BACKUP_DIR/{filename}（用于恢复最新状态）
    - 历史版本：写入 REMOTE_BACKUP_HISTORY_DIR/{filename}.{ts}.bak（最多保留 _MAX_REMOTE_BACKUPS 份）
    失败时静默跳过，不阻断主流程。
    """
    if not os.path.exists(path):
        return
    try:
        os.makedirs(REMOTE_BACKUP_DIR, exist_ok=True)
        base = os.path.basename(path)
        # 1. 最新快照(覆盖式)
        shutil.copy2(path, os.path.join(REMOTE_BACKUP_DIR, base))
        # 2. 历史版本(带时间戳)
        os.makedirs(REMOTE_BACKUP_HISTORY_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(
            path,
            os.path.join(REMOTE_BACKUP_HISTORY_DIR, f"{base}.{ts}.bak"),
        )
        _prune_remote_backups(base)
    except OSError:
        pass


def _prune_remote_backups(base: str) -> None:
    """清理异地备份目录，保留最近 _MAX_REMOTE_BACKUPS 份同名备份。"""
    if not os.path.isdir(REMOTE_BACKUP_HISTORY_DIR):
        return
    prefix = base + "."
    suffix = ".bak"
    backups = [
        os.path.join(REMOTE_BACKUP_HISTORY_DIR, n)
        for n in os.listdir(REMOTE_BACKUP_HISTORY_DIR)
        if n.startswith(prefix) and n.endswith(suffix)
    ]
    backups.sort(key=os.path.getmtime, reverse=True)
    for old in backups[_MAX_REMOTE_BACKUPS:]:
        try:
            os.remove(old)
        except OSError:
            pass


def backup_to_remote() -> bool:
    """把当前 data/ 目录下的 4 个 JSON 文件复制到异地备份目录(全量同步)。

    退出应用时调用：把所有数据文件以最新快照形式覆盖到异地目录。
    成功返回 True。
    """
    try:
        os.makedirs(REMOTE_BACKUP_DIR, exist_ok=True)
        for name in ("transactions.json", "budgets.json",
                     "categories.json", "settings.json"):
            src = os.path.join(DATA_DIR, name)
            if os.path.exists(src):
                _remote_backup(src)
        return True
    except OSError:
        return False


# 默认分类(首次运行时初始化)
DEFAULT_CATEGORIES: List[Dict] = [
    # 支出
    {"name": "餐饮", "type": TYPE_EXPENSE, "color": "#FF6B6B"},
    {"name": "交通", "type": TYPE_EXPENSE, "color": "#4ECDC4"},
    {"name": "购物", "type": TYPE_EXPENSE, "color": "#FFD93D"},
    {"name": "住房", "type": TYPE_EXPENSE, "color": "#A8E6CF"},
    {"name": "娱乐", "type": TYPE_EXPENSE, "color": "#FF8A65"},
    {"name": "医疗", "type": TYPE_EXPENSE, "color": "#B39DDB"},
    {"name": "教育", "type": TYPE_EXPENSE, "color": "#90CAF9"},
    {"name": "其他支出", "type": TYPE_EXPENSE, "color": "#BDBDBD"},
    # 收入
    {"name": "工资", "type": TYPE_INCOME, "color": "#66BB6A"},
    {"name": "兼职", "type": TYPE_INCOME, "color": "#26C6DA"},
    {"name": "投资收益", "type": TYPE_INCOME, "color": "#FFB74D"},
    {"name": "其他收入", "type": TYPE_INCOME, "color": "#BDBDBD"},
]


def _ensure_dir() -> None:
    """确保 data 目录存在。"""
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path: str, default: list) -> list:
    """读取 JSON 文件，文件不存在或损坏时返回 default。"""
    if not os.path.exists(path):
        return list(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return list(default)
            return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return list(default)


def _write_json(path: str, data: list) -> None:
    """原子化写入 JSON 文件：先写临时文件再替换。

    覆盖前自动备份上一版本到 data/backup/，文件名带时间戳，
    最多保留最近 20 份备份，超过自动清理最旧的。
    写入完成后同步一份带时间戳的历史版本到 D 盘异地备份目录。
    """
    _ensure_dir()
    _backup_if_exists(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Windows 下 os.replace 可原子替换已存在文件
    os.replace(tmp, path)
    # 同步一份到异地备份目录(带时间戳历史版本 + 最新快照)
    _remote_backup(path)


_BACKUP_DIR = os.path.join(DATA_DIR, "backup")
_MAX_BACKUPS = 20


def _backup_if_exists(path: str) -> None:
    """若文件已存在且非空，复制一份带时间戳的备份。"""
    if not os.path.exists(path):
        return
    try:
        if os.path.getsize(path) <= 0:
            return
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        base = os.path.basename(path)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = os.path.join(_BACKUP_DIR, f"{base}.{ts}.bak")
        shutil.copy2(path, bak)
        _prune_backups(base)
    except OSError:
        # 备份失败不阻断主流程
        pass


def _prune_backups(base: str) -> None:
    """保留最近 _MAX_BACKUPS 份同名备份，删除更旧的。"""
    if not os.path.isdir(_BACKUP_DIR):
        return
    prefix = base + "."
    suffix = ".bak"
    backups = [
        os.path.join(_BACKUP_DIR, n)
        for n in os.listdir(_BACKUP_DIR)
        if n.startswith(prefix) and n.endswith(suffix)
    ]
    backups.sort(key=os.path.getmtime, reverse=True)
    for old in backups[_MAX_BACKUPS:]:
        try:
            os.remove(old)
        except OSError:
            pass


# ---- 分类 ----

def load_categories() -> List[Category]:
    """加载所有分类，若文件不存在则写入默认分类并返回。"""
    raw = _read_json(_CATEGORIES_FILE, [])
    if not raw:
        # 初始化默认分类
        cats = [Category(id=_new_id(), **c) for c in DEFAULT_CATEGORIES]
        save_categories(cats)
        return cats
    return [Category.from_dict(item) for item in raw]


def save_categories(categories: List[Category]) -> None:
    """写入分类，按 type(支出在前) + name 排序，方便阅读。"""
    type_order = {TYPE_EXPENSE: 0, TYPE_INCOME: 1}
    ordered = sorted(
        categories,
        key=lambda c: (type_order.get(c.type, 99), c.name),
    )
    _write_json(_CATEGORIES_FILE, [c.to_dict() for c in ordered])


# ---- 交易 ----

def load_transactions() -> List[Transaction]:
    raw = _read_json(_TRANSACTIONS_FILE, [])
    return [Transaction.from_dict(item) for item in raw]


def save_transactions(transactions: List[Transaction]) -> None:
    """写入交易，按 date(近→远) + created_at 排序，方便阅读。"""
    ordered = sorted(
        transactions,
        key=lambda t: (t.date, t.created_at),
        reverse=True,
    )
    _write_json(_TRANSACTIONS_FILE, [t.to_dict() for t in ordered])


# ---- 预算 ----

def load_budgets() -> List[Budget]:
    raw = _read_json(_BUDGETS_FILE, [])
    return [Budget.from_dict(item) for item in raw]


def save_budgets(budgets: List[Budget]) -> None:
    """写入预算，按 year_month(近→远) + category_id 排序，方便阅读。"""
    ordered = sorted(
        budgets,
        key=lambda b: (b.year_month, b.category_id),
        reverse=True,
    )
    _write_json(_BUDGETS_FILE, [b.to_dict() for b in ordered])


# ---- 设置 ----

def load_settings() -> Dict:
    """读取设置，缺失字段用默认值补齐。"""
    if not os.path.exists(_SETTINGS_FILE):
        data = dict(DEFAULT_SETTINGS)
        save_settings(data)
        return data
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return dict(DEFAULT_SETTINGS)
            data = json.loads(content)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)
    # 合并默认值，保证新字段存在
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    return merged


def save_settings(settings: Dict) -> None:
    _ensure_dir()
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
