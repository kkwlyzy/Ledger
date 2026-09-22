# API 使用说明

## 启动服务

```bash
# 需先安装依赖
pip install fastapi "uvicorn[standard]" pydantic

# 启动（默认 127.0.0.1:8000）
python api_server.py
```

启动后：
- 交互式文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health

自定义地址/端口：
```bash
LEDGER_HOST=0.0.0.0 LEDGER_PORT=9000 python api_server.py
```

## 核心接口：自然语言记账

```bash
curl -X POST http://127.0.0.1:8000/api/ledger/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "午饭花了25"}'
```

返回示例：
```json
{
  "ok": true,
  "message": "已记账",
  "analyzed": {
    "amount": 25.0,
    "type": "expense",
    "category_name": "餐饮",
    "note": "午饭",
    "confidence": "rule"
  },
  "transaction": {
    "id": "xxx",
    "amount": 25.0,
    "type": "expense",
    "category_id": "xxx",
    "category_name": "餐饮",
    "date": "2026-09-21",
    "note": "午饭"
  }
}
```

## 查询接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/transactions` | 查交易，支持 `start` `end` `type` `category_id` `limit` 参数 |
| GET | `/api/summary` | 区间收支汇总（默认当月），返回收入/支出/结余/笔数 |
| GET | `/api/categories` | 列出全部分类 |
| GET | `/api/health` | 健康检查 |

## 分析方式

默认用**内置规则**（关键词映射，离线零成本）。可选接入大模型：

1. 在 `data/` 下新建 `llm.json`：
```json
{
  "api_key": "你的Key",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-3.5-turbo"
}
```
2. 配置后自动走 LLM 语义分析，失败时回退到规则。

> `base_url` 兼容所有 OpenAI 风格的 `/chat/completions` 服务（OpenAI / 通义 / DeepSeek 等）。

## 数据写入位置

API 读写的是**源码目录** `data/`（与 `python main.py` 一致）。

> 注意：打包版 exe 读写的是 `dist/data/`，两者是不同目录。若你的桌面端用的是 exe，
> 而 API 写进了 `data/`，两边数据不会互通。需要的话可改 `storage.py` 的 `DATA_DIR` 指向。
