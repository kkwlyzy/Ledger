"""AI 记账分析器：把自然语言解析成结构化交易。

设计为「规则 + 可选 LLM」两级：
1. 规则层（analyze_with_rules）：关键词映射，零成本离线可用。
2. LLM 层（analyze_with_llm）：调用大模型做语义理解，需配置 API Key。

analyze() 是统一入口：若配置了 LLM 则优先 LLM、规则兜底；
否则直接走规则。规则匹配不到分类时回退到「其他支出/其他收入」。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from typing import List, Optional

# 复用现有数据模型与存储层，保证写入格式与桌面端完全一致
from models import Category, Transaction, TYPE_EXPENSE, TYPE_INCOME

# ---- 关键词规则表（可自行扩充）----
# 匹配到即归类；按列表顺序优先
_EXPENSE_RULES: List[tuple] = [
    ("餐饮", ["吃", "饭", "餐", "外卖", "午饭", "晚饭", "早饭", "早餐", "午餐", "晚餐", "咖啡", "奶茶", "饮料", "烧烤", "火锅", "聚餐", "零食", "夜宵", "奶茶", "买菜", "食堂", "麦当劳", "肯德基", "必胜客", "汉堡"]),
    ("交通", ["打车", "滴滴", "地铁", "公交", "高铁", "火车", "飞机", "机票", "加油", "停车", "出租车", "网约车", "共享单车", "打的", "车票", "油费", "过路费"]),
    ("住房", ["房租", "水电", "电费", "水费", "燃气", "物业", "房贷", "维修", "宽带", "网费", "暖气", "气费"]),
    ("医疗", ["看病", "医院", "药", "挂号", "体检", "牙医", "诊所", "医保", "口罩", "理疗", "检查"]),
    ("教育", ["书", "课程", "培训", "学费", "考试", "报名", "网课", "学习", "文具", "考研", "考证", "买书", "买课"]),
    ("娱乐", ["电影", "游戏", "唱歌", "KTV", "旅游", "景点", "门票", "演出", "会员", "视频会员", "直播", "健身", "游泳", "运动", "桌游", "剧本杀"]),
    ("购物", ["淘宝", "京东", "拼多多", "衣服", "鞋", "包", "化妆品", "日用品", "超市", "网购", "下单", "数码", "手机", "电脑", "家具", "电器", "买了", "买"]),
]

_INCOME_RULES: List[tuple] = [
    ("工资", ["工资", "薪水", "发工资", "薪资", "奖金", "绩效", "年终奖", "补贴", "报销"]),
    ("兼职", ["兼职", "副业", "外快", "接单", "私活", "家教", "代购"]),
    ("投资收益", ["利息", "分红", "股票", "基金", "理财", "收益", "投资", "利息收入", "房租收入", "租金"]),
]

# 中文数字 → 阿拉伯数字（「十百千」作为进位单独处理，不在此表）
_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(s: str) -> Optional[int]:
    """把「二十三」「一百二」等中文数字转成 int，失败返回 None。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total = 0
    unit = 1
    acc = 0
    for ch in s:
        if ch in _CN_NUM:
            acc = _CN_NUM[ch]
        elif ch == "十":
            total += (acc if acc else 1) * 10
            acc = 0
        elif ch == "百":
            total += (acc if acc else 1) * 100
            acc = 0
        elif ch == "千":
            total += (acc if acc else 1) * 1000
            acc = 0
        else:
            return None
    return total + acc


@dataclass
class AnalysisResult:
    """分析结果：金额、类型、分类、备注、置信度。"""
    amount: float
    type: str
    category_name: str
    note: str = ""
    confidence: str = "rule"
    date: str = ""  # ISO 日期，空表示用今天

    def to_dict(self) -> dict:
        return asdict(self)


def extract_date(text: str) -> Optional[str]:
    """从文本中提取日期，返回 ISO 格式 YYYY-MM-DD。

    支持：「9月21日」「9月21」「2026年9月21日」「9-21」「09-21」。
    缺少年份时补当前年份；返回 None 表示未识别到日期。
    """
    from datetime import date as _date

    today = _date.today()
    # 带年份：2026年9月21日 / 2026-9-21
    m = re.search(r"(\d{4})\s*[年\-/\.]\s*(\d{1,2})\s*[月\-/\.]\s*(\d{1,2})\s*日?", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        # 无年份：9月21日 / 9-21
        m = re.search(r"(\d{1,2})\s*[月\-/\.]\s*(\d{1,2})\s*日?", text)
        if not m:
            return None
        y, mo, d = today.year, int(m.group(1)), int(m.group(2))
    try:
        return _date(y, mo, d).isoformat()
    except ValueError:
        return None


def extract_amount(text: str) -> Optional[float]:
    """从文本中提取金额，支持阿拉伯数字、小数、中文数字。

    优先取「元/块」前的数字；否则取首个出现的数字。
    例：午饭25 → 25；打车花了三十块 → 30；买菜20.5元 → 20.5。
    """
    # 带货币单位的数字，如 25元 / 25块 / 25.5元
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|块钱|rmb|RMB)", text)
    if m:
        return float(m.group(1))
    # 「xx花了xx」这类
    m = re.search(r"(?:花了|花费|用了|付了|消费|支出|发了|收入)\s*(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    # 纯数字（第一个出现的浮点数）
    m = re.search(r"\d+(?:\.\d+)?", text)
    if m:
        return float(m.group(0))
    # 中文数字 + 元/块，如「三十块」「二十三块五」
    m = re.search(r"([零一二两三四五六七八九十百千]+)\s*(?:元|块|块钱)", text)
    if m:
        v = _cn_to_int(m.group(1))
        if v is not None:
            return float(v)
    return None


def infer_type(text: str) -> str:
    """判断收入还是支出，默认支出。"""
    income_words = ["收入", "入账", "赚", "到账", "发了", "发工资", "工资", "奖金", "报销", "退款", "收到", "转入", "分红", "利息", "租金", "收益", "理财"]
    for w in income_words:
        if w in text:
            return TYPE_INCOME
    return TYPE_EXPENSE


def classify(text: str, type_: str, categories: List[Category]) -> str:
    """根据关键词把文本映射到现有分类名。"""
    rules = _INCOME_RULES if type_ == TYPE_INCOME else _EXPENSE_RULES
    for name, words in rules:
        for w in words:
            if w in text:
                return name
    # 回退：找同类型下的兜底分类
    fallback = {"expense": "其他支出", "income": "其他收入"}.get(type_, "其他支出")
    existing = {c.name for c in categories if c.type == type_}
    if fallback in existing:
        return fallback
    # 若兜底分类都不存在，取该类型第一个分类
    for c in categories:
        if c.type == type_:
            return c.name
    return fallback


def analyze_with_rules(text: str, categories: List[Category]) -> Optional[AnalysisResult]:
    """规则分析：金额必填，分类按关键词匹配。"""
    amount = extract_amount(text)
    if amount is None or amount <= 0:
        return None
    type_ = infer_type(text)
    name = classify(text, type_, categories)
    tx_date = extract_date(text) or ""
    # 备注：去掉金额、金额单位、日期、冗余词后的原文，尽量精简
    note = re.sub(r"\d+(?:\.\d+)?\s*(?:元|块|块钱|rmb|RMB)?", "", text)
    # 去掉日期表达（含数字+年月日字），如 9月21日 / 2026年9月21日 / 9-21
    note = re.sub(r"\d{1,4}\s*[年\-/\.]\s*\d{1,2}\s*[月\-/\.]\s*\d{1,2}\s*日?", "", note)
    note = re.sub(r"\d{1,2}\s*[月\-/\.]\s*\d{1,2}\s*日?", "", note)
    # 残留的孤立年月日字
    note = re.sub(r"[年月日]", "", note)
    note = re.sub(r"花了|花费|用了|付了|消费|支出|收入|入账|今天|昨天|早上|中午|晚上|花了钱|钱", "", note)
    note = note.strip(" ，。,.、~- ")
    note = re.sub(r"\s+", " ", note)
    return AnalysisResult(
        amount=round(amount, 2),
        type=type_,
        category_name=name,
        note=note,
        confidence="rule",
        date=tx_date,
    )


def analyze_with_llm(text: str, categories: List[Category], config: dict) -> Optional[AnalysisResult]:
    """调用 OpenAI 兼容接口做语义分析（可选）。

    通过 HTTP 直接调用，避免额外依赖 openai 包。
    支持 OpenAI / 通义(兼容模式) / DeepSeek 等兼容 /chat/completions 的服务。
    """
    import urllib.request

    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "https://api.openai.com/v1").rstrip("/")
    model = config.get("model", "gpt-3.5-turbo")
    if not api_key:
        return None

    cat_list = "、".join(f"{c.name}({c.type})" for c in categories)
    prompt = (
        f"你是记账助手。请从用户这句话里提取：金额、收支类型(income/expense)、"
        f"分类、备注。可选分类：{cat_list}。\n"
        f"只返回 JSON，不要多余文字，格式："
        f'{{"amount": 数字, "type": "expense|income", "category_name": "分类名", "note": "备注"}}\n'
        f'用户输入：{text}'
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        # 去掉可能的 markdown 代码块包裹
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            content = content.replace("json", "", 1).strip()
        parsed = json.loads(content)
        amount = float(parsed.get("amount", 0))
        type_ = parsed.get("type", TYPE_EXPENSE)
        if type_ not in (TYPE_EXPENSE, TYPE_INCOME):
            type_ = TYPE_EXPENSE
        return AnalysisResult(
            amount=round(amount, 2),
            type=type_,
            category_name=str(parsed.get("category_name", "其他支出")),
            note=str(parsed.get("note", "")),
            confidence="llm",
        )
    except Exception:
        return None


def load_llm_config() -> dict:
    """从 data/llm.json 读取 LLM 配置（不存在则返回空）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "llm.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def analyze(text: str, categories: List[Category]) -> Optional[AnalysisResult]:
    """统一分析入口：LLM 优先，规则兜底。"""
    text = (text or "").strip()
    if not text:
        return None
    cfg = load_llm_config()
    if cfg.get("api_key"):
        r = analyze_with_llm(text, categories, cfg)
        if r and r.amount > 0:
            return r
    return analyze_with_rules(text, categories)
