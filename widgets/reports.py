"""统计报表页面：matplotlib 与 PySide6 集成。

包含：
- 周期收支对比柱状图（最近6个发薪周期）
- 当期支出分类占比饼图
- 支出趋势折线图
- 当期数字摘要
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# matplotlib Qt 后端
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from models import TYPE_EXPENSE, TYPE_INCOME


# 中文字体回退，避免中文乱码
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
matplotlib.rcParams["axes.unicode_minus"] = False


class ReportsPage(QWidget):
    """报表页面：周期选择 + 四张图表。"""

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._build_ui()
        self.ctx.data_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("统计报表", self)
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("查看周期："))
        self.cycle_combo = QComboBox(self)
        self.cycle_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.cycle_combo)
        bar.addStretch(1)
        self.btn_refresh = QPushButton("刷新", self)
        self.btn_refresh.setProperty("role", "secondary")
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.btn_refresh)
        root.addLayout(bar)

        # matplotlib Figure
        self.figure = Figure(figsize=(10, 7))
        self.canvas = FigureCanvas(self.figure)
        root.addWidget(self.canvas, 1)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._refresh_cycles()
        cs = self.cycle_combo.currentData() or self.ctx.current_cycle_start()
        self._draw(cs)

    def _refresh_cycles(self) -> None:
        # 收集交易涉及的周期 + 最近12个周期，去重后按时间倒序
        cycle_set = set()
        for t in self.ctx.transactions:
            try:
                d = date.fromisoformat(t.date)
            except ValueError:
                continue
            cycle_set.add(self.ctx.cycle_for_date(d))
        for c in self.ctx.recent_cycles(12):
            cycle_set.add(c)

        def _key(cs: str):
            try:
                return date.fromisoformat(cs)
            except ValueError:
                return date.min

        ordered = sorted(cycle_set, key=_key, reverse=True)

        prev = self.cycle_combo.currentData() or ""
        self.cycle_combo.blockSignals(True)
        self.cycle_combo.clear()
        for c in ordered:
            self.cycle_combo.addItem(self.ctx.cycle_label(c), c)
        idx = self.cycle_combo.findData(prev)
        if idx < 0:
            idx = self.cycle_combo.findData(self.ctx.current_cycle_start())
        self.cycle_combo.setCurrentIndex(max(idx, 0))
        self.cycle_combo.blockSignals(False)

    def _recent_cycles_around(self, cs: str, n: int = 6) -> List[str]:
        """返回以 cs 为末项的最近 n 个周期(由远及近)。"""
        out = [cs]
        for _ in range(n - 1):
            s, _e = self.ctx.cycle_range(out[-1])
            from datetime import timedelta
            prev_day = s - timedelta(days=1)
            out.append(self.ctx.cycle_for_date(prev_day))
        return list(reversed(out))

    def _draw(self, cs: str) -> None:
        self.figure.clear()

        # === 子图1：周期收支对比柱状图（最近6个周期）===
        ax1 = self.figure.add_subplot(2, 2, 1)
        cycles = self._recent_cycles_around(cs, 6)
        incomes, expenses = [], []
        for c in cycles:
            inc, exp = self.ctx.cycle_summary(c)
            incomes.append(inc)
            expenses.append(exp)
        x = range(len(cycles))
        width = 0.38
        ax1.bar([i - width / 2 for i in x], incomes, width, label="收入", color="#27ae60")
        ax1.bar([i + width / 2 for i in x], expenses, width, label="支出", color="#e74c3c")
        ax1.set_xticks(list(x))
        # x 轴标签用起始日短格式(09-08)
        short_labels = [c[5:] for c in cycles]
        ax1.set_xticklabels(short_labels, rotation=30, fontsize=8)
        ax1.set_title("近6个周期收支对比", fontsize=10)
        ax1.legend(fontsize=8)
        ax1.grid(axis="y", linestyle="--", alpha=0.3)

        # === 子图2：当期支出分类占比饼图 ===
        ax2 = self.figure.add_subplot(2, 2, 2)
        cat_totals = defaultdict(float)
        s, e = self.ctx.cycle_range(cs)
        for t in self.ctx.transactions:
            try:
                td = date.fromisoformat(t.date)
            except ValueError:
                continue
            if not (s <= td < e):
                continue
            if t.type == TYPE_EXPENSE:
                cat_totals[t.category_id] += t.amount
        if cat_totals:
            labels, sizes, colors = [], [], []
            for cid, val in cat_totals.items():
                cat = self.ctx.category_by_id(cid)
                labels.append(cat.name if cat else "?")
                sizes.append(val)
                colors.append(cat.color if cat else "#999999")
            ax2.pie(
                sizes,
                labels=labels,
                colors=colors,
                autopct=lambda p: f"{p:.1f}%" if p > 3 else "",
                startangle=90,
                textprops={"fontsize": 8},
            )
            ax2.set_title(f"{cs[5:]} 周期支出分类占比", fontsize=10)
        else:
            ax2.text(0.5, 0.5, "本周期暂无支出", ha="center", va="center")
            ax2.set_title(f"{cs[5:]} 周期支出分类占比", fontsize=10)
            ax2.axis("off")

        # === 子图3：支出趋势折线图（最近6个周期）===
        ax3 = self.figure.add_subplot(2, 2, 3)
        ax3.plot(short_labels, expenses, marker="o", color="#e74c3c", linewidth=2)
        ax3.fill_between(range(len(short_labels)), expenses, alpha=0.15, color="#e74c3c")
        ax3.set_title("近6个周期支出趋势", fontsize=10)
        ax3.tick_params(axis="x", labelrotation=30, labelsize=8)
        ax3.grid(linestyle="--", alpha=0.3)

        # === 子图4：当期数字摘要 ===
        ax4 = self.figure.add_subplot(2, 2, 4)
        ax4.axis("off")
        income, expense = self.ctx.cycle_summary(cs)
        balance = income - expense
        top = sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:3]
        label = self.ctx.cycle_label(cs)
        summary_text = f"{label}\n\n"
        summary_text += f"收入：¥{income:,.2f}\n"
        summary_text += f"支出：¥{expense:,.2f}\n"
        summary_text += f"结余：¥{balance:,.2f}\n"
        if top:
            summary_text += "\n支出 Top3：\n"
            for cid, val in top:
                cat = self.ctx.category_by_id(cid)
                summary_text += f"  · {cat.name if cat else '?'}  ¥{val:,.2f}\n"
        ax4.text(
            0.05,
            0.95,
            summary_text,
            transform=ax4.transAxes,
            fontsize=11,
            verticalalignment="top",
            family="sans-serif",
            bbox=dict(boxstyle="round", facecolor="#f5f6f8", edgecolor="#bdc3c7"),
        )

        self.figure.tight_layout(pad=2.0)
        self.canvas.draw()
