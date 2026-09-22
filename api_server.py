"""FastAPI 记账服务：把自然语言转成交易并写入，提供查询与统计。

运行：
    python api_server.py            # 默认 http://127.0.0.1:8000
    uvicorn api_server:app --host 0.0.0.0 --port 8000

数据复用 storage.py 的读写逻辑，写入源码目录 data/（与 python main.py 一致）。
交互式文档：启动后访问 http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import storage
from analyzer import analyze
from models import Category, Transaction, TYPE_EXPENSE, TYPE_INCOME


app = FastAPI(
    title="记账本 API",
    description="自然语言记账 + 查询统计。POST /api/ledger/analyze 输入一句话即可自动归类写入。",
    version="1.2.0",
)


# ---- 请求/响应模型 ----

class AnalyzeRequest(BaseModel):
    text: str = Field(..., description="自然语言描述，如「午饭花了25」「发工资8000」")


class TransactionOut(BaseModel):
    id: str
    amount: float
    type: str
    category_id: str
    category_name: str
    date: str
    note: str


class AnalyzeResponse(BaseModel):
    ok: bool
    message: str
    analyzed: Optional[dict] = None   # 分析结果
    transaction: Optional[TransactionOut] = None


class Summary(BaseModel):
    period: str
    income: float
    expense: float
    balance: float
    count: int


# ---- 内部工具 ----

def _load_all():
    """从磁盘加载最新数据。"""
    return storage.load_categories(), storage.load_transactions()


def _cat_name(cid: str, categories: List[Category]) -> str:
    for c in categories:
        if c.id == cid:
            return c.name
    return "(已删除)"


def _to_out(t: Transaction, categories: List[Category]) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        amount=t.amount,
        type=t.type,
        category_id=t.category_id,
        category_name=_cat_name(t.category_id, categories),
        date=t.date,
        note=t.note,
    )


# ---- 智能记账入口 ----

@app.post("/api/ledger/analyze", response_model=AnalyzeResponse)
def ledger_analyze(req: AnalyzeRequest):
    """输入自然语言，AI 分析金额/用途/分类后写入一条交易。"""
    categories, _ = _load_all()
    if not categories:
        raise HTTPException(status_code=500, detail="暂无分类，请先在桌面端初始化分类")

    result = analyze(req.text, categories)
    if result is None:
        return AnalyzeResponse(ok=False, message="无法从这句话中识别出金额，请补充金额信息")

    # 找到分类 id（按名称匹配）
    cat_id = None
    for c in categories:
        if c.name == result.category_name:
            cat_id = c.id
            break
    if cat_id is None:
        # 名称对不上，退回「其他支出/其他收入」
        fallback = "其他收入" if result.type == TYPE_INCOME else "其他支出"
        for c in categories:
            if c.name == fallback:
                cat_id = c.id
                break
    if cat_id is None:
        cat_id = categories[0].id  # 最终兜底

    # 构造交易
    today = date.today().isoformat()
    t = Transaction(
        amount=result.amount,
        type=result.type,
        category_id=cat_id,
        date=today,
        note=result.note,
    )

    # 写入（复用 storage，保证与桌面端格式一致，自动备份）
    _, transactions = _load_all()
    transactions.append(t)
    storage.save_transactions(transactions)

    return AnalyzeResponse(
        ok=True,
        message="已记账",
        analyzed=result.to_dict(),
        transaction=_to_out(t, categories),
    )


# ---- 查询 ----

@app.get("/api/transactions", response_model=List[TransactionOut])
def list_transactions(
    start: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    type_: Optional[str] = Query(None, alias="type", description="income / expense"),
    category_id: Optional[str] = Query(None, description="分类 id"),
    limit: int = Query(100, ge=1, le=1000),
):
    """查询交易，支持日期/类型/分类过滤。"""
    categories, transactions = _load_all()
    rows = []
    for t in transactions:
        if start and t.date < start:
            continue
        if end and t.date > end:
            continue
        if type_ and t.type != type_:
            continue
        if category_id and t.category_id != category_id:
            continue
        rows.append(t)
    rows.sort(key=lambda t: (t.date, t.created_at), reverse=True)
    return [_to_out(t, categories) for t in rows[:limit]]


@app.get("/api/summary", response_model=Summary)
def get_summary(
    start: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
):
    """区间收支汇总。不传日期则统计当月。"""
    if not start:
        start = date.today().replace(day=1).isoformat()
    if not end:
        end = date.today().isoformat()
    _, transactions = _load_all()
    income = expense = 0.0
    cnt = 0
    for t in transactions:
        if t.date < start or t.date > end:
            continue
        cnt += 1
        if t.type == TYPE_INCOME:
            income += t.amount
        else:
            expense += t.amount
    return Summary(
        period=f"{start} ~ {end}",
        income=round(income, 2),
        expense=round(expense, 2),
        balance=round(income - expense, 2),
        count=cnt,
    )


@app.get("/api/categories", response_model=List[dict])
def list_categories():
    """列出所有分类。"""
    categories, _ = _load_all()
    return [
        {"id": c.id, "name": c.name, "type": c.type, "color": c.color}
        for c in categories
    ]


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat(timespec="seconds")}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("LEDGER_HOST", "127.0.0.1")
    port = int(os.environ.get("LEDGER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
