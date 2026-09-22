"""记账命令行工具：一行命令把自然语言转成交易并写入。

用法：
    python ledger_cli.py "午饭花了25"
    python ledger_cli.py add "打车30块"
    python ledger_cli.py summary
    python ledger_cli.py list --limit 5

数据写入口：dist\\data（与记账本 exe 一致）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

# 数据目录固定指向 exe 同级 data（与打包版一致）
DIST_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "data")

# 把 analyzer / models / storage 纳入导入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage  # noqa: E402
from analyzer import analyze  # noqa: E402


def _ensure_data_dir():
    os.makedirs(DIST_DATA, exist_ok=True)


def _load_categories():
    storage.DATA_DIR = DIST_DATA
    # storage 模块全局路径在导入时已固定，这里重新计算文件路径
    import models
    cats_file = os.path.join(DIST_DATA, "categories.json")
    if not os.path.isfile(cats_file):
        return []
    data = json.load(open(cats_file, encoding="utf-8"))
    return [models.Category.from_dict(x) for x in data]


def _load_transactions():
    import models
    tx_file = os.path.join(DIST_DATA, "transactions.json")
    if not os.path.isfile(tx_file):
        return []
    data = json.load(open(tx_file, encoding="utf-8"))
    return [models.Transaction.from_dict(x) for x in data]


def _save_transactions(txs):
    import models
    tx_file = os.path.join(DIST_DATA, "transactions.json")
    ordered = sorted(txs, key=lambda t: (t.date, t.created_at), reverse=True)
    json.dump([t.to_dict() for t in ordered], open(tx_file, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def cmd_add(text: str):
    _ensure_data_dir()
    cats = _load_categories()
    if not cats:
        print("错误：dist/data 下没有分类文件，请先运行一次记账本 exe 初始化。")
        return 1
    result = analyze(text, cats)
    if result is None:
        print(f"无法识别金额：{text!r}")
        return 1
    # 找分类 id
    cat_id = None
    for c in cats:
        if c.name == result.category_name:
            cat_id = c.id
            break
    if cat_id is None:
        fallback = "其他收入" if result.type == "income" else "其他支出"
        for c in cats:
            if c.name == fallback:
                cat_id = c.id
                break
    if cat_id is None:
        cat_id = cats[0].id

    from datetime import date
    import models
    t = models.Transaction(
        amount=result.amount,
        type=result.type,
        category_id=cat_id,
        date=result.date or date.today().isoformat(),
        note=result.note,
    )
    txs = _load_transactions()
    txs.append(t)
    _save_transactions(txs)

    type_cn = "收入" if result.type == "income" else "支出"
    print(f"已记账：{type_cn} ¥{result.amount:.2f}  [{result.category_name}] {result.note}")
    return 0


def cmd_summary():
    txs = _load_transactions()
    income = sum(t.amount for t in txs if t.type == "income")
    expense = sum(t.amount for t in txs if t.type == "expense")
    print(f"本月记账 {len(txs)} 笔 | 收入 ¥{income:.2f} | 支出 ¥{expense:.2f} | 结余 ¥{income-expense:.2f}")
    return 0


def cmd_list(limit: int):
    txs = _load_transactions()
    cats = {c.id: c.name for c in _load_categories()}
    for t in txs[:limit]:
        cn = cats.get(t.category_id, "(已删除)")
        tc = "收入" if t.type == "income" else "支出"
        print(f"{t.date}  {tc}  {cn}  ¥{t.amount:.2f}  {t.note}")
    return 0


def main():
    p = argparse.ArgumentParser(description="记账命令行工具")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="记一笔（自然语言）")
    a.add_argument("text", help="如「午饭花了25」")

    sub.add_parser("summary", help="本月汇总")

    l = sub.add_parser("list", help="列出最近交易")
    l.add_argument("--limit", type=int, default=10)

    args = p.parse_args()

    if args.cmd in ("add", None) and getattr(args, "text", None):
        return cmd_add(args.text)
    if args.cmd == "add":
        return cmd_add(getattr(args, "text", ""))
    if args.cmd == "summary":
        return cmd_summary()
    if args.cmd == "list":
        return cmd_list(args.limit)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
