# Ledger

基于 PySide6 的本地记账桌面软件。数据全部以 JSON 文件存放在本机，不依赖任何网络服务。

最大的特点是**按发薪周期记账**：预算、报表、每日消费建议都围绕「发薪日 → 下个发薪日」计算，而不是自然月。

---

## 功能

| 页面 | 说明 |
| --- | --- |
| **记账** | 收支记录的增删改查，支持按月份 / 类型 / 分类筛选 |
| **分类管理** | 自定义收支分类，可为每个分类指定颜色（用于报表配色） |
| **预算管理** | 按发薪周期、按分类设置预算上限，实时显示使用进度 |
| **统计报表** | 近 6 个周期收支对比、当期支出分类占比、支出趋势、数字摘要 |

**每日消费建议**（预算页）：根据剩余预算和剩余天数算出「今天还能花多少」，并按健康度变色——宽松（绿）、正常（蓝）、偏紧（橙）、告急（红）。另有「今日汇总 + 明日可用」卡片，把今天的实际支出从剩余额度里扣掉后再规划明天。

---

## 技术栈

- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/) 6.5+ — GUI
- [matplotlib](https://pypi.org/project/matplotlib/) 3.7+ — 图表（QtAgg 后端嵌入界面）

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

打包成独立 exe（产物 `dist/记账本.exe`）：

```bash
pyinstaller ledger.spec
```

生成应用图标并创建桌面快捷方式：

```bash
python make_shortcut.py   # 需要 Pillow: pip install pillow
```

---

## 核心概念：发薪周期

默认发薪日是每月 **8 号**（可在 `设置 → 发薪日` 中修改，取值范围 1~28）。

一个周期指「本月发薪日（含）→ 下月发薪日（不含）」。例如 payday=8 时，当前周期是 `2026-09-08 ~ 2026-10-07`。

这个概念贯穿全局：

- 预算是按**周期**设置的，不是按月
- 报表按周期汇总收支
- 状态栏显示的是当前周期的收入 / 支出 / 结余

改发薪日后，所有周期相关的统计会立即按新口径重算。

---

## 数据存储与备份

数据文件位于 `data/` 目录（打包运行时位于 exe 同级的 `data/`）：

```
data/
├── transactions.json   交易记录
├── categories.json     收支分类
├── budgets.json        预算
├── settings.json       设置（如 payday）
└── backup/             本地历史备份
```

**写入是原子的**：先写 `.tmp` 临时文件，再用 `os.replace` 替换，中途崩溃不会损坏原文件。

**三层保护**：

1. 每次写入前，自动把上一版本备份到 `data/backup/`，每类文件保留最近 20 份
2. 关闭程序时全量同步到异地备份目录（在 `storage.py` 的 `REMOTE_BACKUP_DIR` 中配置）
3. 需要回滚时，用 `设置 → 从备份恢复` 选择历史版本覆盖当前数据

> 异地备份目录默认是本机另一个磁盘路径，使用前请先改成你自己的位置。找不到该目录时备份会静默跳过，不影响主流程。

---

## 项目结构

```
main.py            入口：AppContext 数据上下文 + MainWindow 主窗口
models.py          数据模型：Transaction / Category / Budget
storage.py         JSON 持久化、原子写入、备份与恢复
widgets/
  transactions.py   记账页
  categories.py     分类管理页
  budgets.py        预算管理页
  reports.py        统计报表页
ledger.spec        PyInstaller 打包配置
make_shortcut.py   图标生成 + 桌面快捷方式
```

架构上，`AppContext` 是唯一数据源：任何页面修改数据后调用 `save_all()`，写盘并广播 `data_changed` 信号，各页面订阅该信号自动刷新。页面之间不直接传递数据。

---

## 使用提示

- **Ctrl+S** 手动保存，**Ctrl+Q** 退出（退出时自动保存并备份）
- 交易列表中双击行可直接编辑
- 分类被交易引用时不可删除，需先迁移或删除相关交易
- 分类的 `color` 字段会用在报表饼图里，建议设置区分度高的颜色
