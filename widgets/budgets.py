"""预算管理页面：按发薪周期、按支出分类设置预算上限，并显示使用情况。

额外提供「每日建议」卡片：
- 日均预算 = 周期总预算 / 周期天数
- 今日建议消费 = 剩余预算 / 剩余天数（实时，仅当前周期生效）
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import TYPE_EXPENSE, Budget


class BudgetDialog(QDialog):
    """新增/编辑预算对话框：选月份+分类+金额。"""

    def __init__(self, ctx, budget: Optional[Budget] = None, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._editing = budget
        self.setWindowTitle("编辑预算" if budget else "新增预算")
        self._build_ui()
        if budget:
            self._load(budget)

    def _build_ui(self) -> None:
        form = QFormLayout(self)

        self.cycle_combo = QComboBox(self)
        self._fill_cycles()

        self.cat_combo = QComboBox(self)
        for c in self.ctx.categories_of_type(TYPE_EXPENSE):
            self.cat_combo.addItem(c.name, c.id)

        self.amount_spin = QDoubleSpinBox(self)
        self.amount_spin.setRange(0.0, 1e9)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setSingleStep(100.0)
        self.amount_spin.setPrefix("¥ ")

        form.addRow("周期：", self.cycle_combo)
        form.addRow("分类（支出）：", self.cat_combo)
        form.addRow("预算金额：", self.amount_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _fill_cycles(self) -> None:
        # 最近 12 个发薪周期，当前周期排在最前
        cycles = self.ctx.recent_cycles(12)
        # 当前周期作为默认
        cur = self.ctx.current_cycle_start()
        for c in cycles:
            self.cycle_combo.addItem(self.ctx.cycle_label(c), c)
        idx = self.cycle_combo.findData(cur)
        if idx >= 0:
            self.cycle_combo.setCurrentIndex(idx)

    def _load(self, b: Budget) -> None:
        idx = self.cycle_combo.findData(b.year_month)
        if idx >= 0:
            self.cycle_combo.setCurrentIndex(idx)
        else:
            # 周期不在最近12个之内，补一项
            self.cycle_combo.addItem(self.ctx.cycle_label(b.year_month), b.year_month)
            self.cycle_combo.setCurrentIndex(self.cycle_combo.count() - 1)
        idx = self.cat_combo.findData(b.category_id)
        if idx >= 0:
            self.cat_combo.setCurrentIndex(idx)
        self.amount_spin.setValue(b.amount)

    def build_budget(self) -> Budget:
        cat_id = self.cat_combo.currentData()
        if not cat_id:
            raise ValueError("请选择分类")
        if self._editing:
            b = self._editing
            b.year_month = self.cycle_combo.currentData()
            b.category_id = cat_id
            b.amount = round(self.amount_spin.value(), 2)
            return b
        return Budget(
            year_month=self.cycle_combo.currentData(),
            category_id=cat_id,
            amount=round(self.amount_spin.value(), 2),
        )


class BudgetsPage(QWidget):
    """预算列表：周期切换、按分类展示使用/预算/进度条。"""

    COLUMNS = ["分类", "预算", "已用", "剩余", "进度"]

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

        title = QLabel("预算管理", self)
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        bar = QHBoxLayout()
        self.btn_add = QPushButton("新增预算", self)
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit = QPushButton("编辑", self)
        self.btn_edit.setProperty("role", "secondary")
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_del = QPushButton("删除", self)
        self.btn_del.setProperty("role", "danger")
        self.btn_del.clicked.connect(self._on_delete)

        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_edit)
        bar.addWidget(self.btn_del)
        bar.addStretch(1)

        bar.addWidget(QLabel("周期："))
        self.cycle_combo = QComboBox(self)
        self.cycle_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.cycle_combo)

        root.addLayout(bar)

        self.summary = QLabel("", self)
        self.summary.setStyleSheet("color:#7f8c8d; font-size:13px;")
        root.addWidget(self.summary)

        # 每日建议卡片
        self.advice_card = QFrame(self)
        self.advice_card.setObjectName("adviceCard")
        self.advice_card.setStyleSheet(
            "#adviceCard { background:#ffffff; border:1px solid #ecf0f1;"
            " border-left:4px solid #3498db; border-radius:6px; }"
        )
        advice_layout = QVBoxLayout(self.advice_card)
        advice_layout.setContentsMargins(16, 12, 16, 12)
        advice_layout.setSpacing(6)

        advice_title = QLabel("每日建议", self.advice_card)
        advice_title.setStyleSheet(
            "font-size:14px; font-weight:600; color:#2c3e50; border:none;"
        )
        self.advice_main = QLabel("", self.advice_card)
        self.advice_main.setStyleSheet(
            "font-size:20px; font-weight:700; color:#2980b9; border:none;"
        )
        self.advice_detail = QLabel("", self.advice_card)
        self.advice_detail.setStyleSheet(
            "font-size:12px; color:#7f8c8d; border:none;"
        )
        advice_layout.addWidget(advice_title)
        advice_layout.addWidget(self.advice_main)
        advice_layout.addWidget(self.advice_detail)
        root.addWidget(self.advice_card)

        # 今日汇总 + 明日建议卡片
        self.today_card = QFrame(self)
        self.today_card.setObjectName("todayCard")
        self.today_card.setStyleSheet(
            "#todayCard { background:#ffffff; border:1px solid #ecf0f1;"
            " border-left:4px solid #27ae60; border-radius:6px; }"
        )
        today_layout = QVBoxLayout(self.today_card)
        today_layout.setContentsMargins(16, 12, 16, 12)
        today_layout.setSpacing(6)

        today_title = QLabel("今日汇总 + 明日建议", self.today_card)
        today_title.setStyleSheet(
            "font-size:14px; font-weight:600; color:#2c3e50; border:none;"
        )
        self.today_main = QLabel("", self.today_card)
        self.today_main.setStyleSheet(
            "font-size:16px; font-weight:700; color:#27ae60; border:none;"
        )
        self.today_detail = QLabel("", self.today_card)
        self.today_detail.setStyleSheet(
            "font-size:12px; color:#7f8c8d; border:none;"
        )
        self.tomorrow_main = QLabel("", self.today_card)
        self.tomorrow_main.setStyleSheet(
            "font-size:18px; font-weight:700; color:#2980b9; border:none;"
        )
        self.tomorrow_detail = QLabel("", self.today_card)
        self.tomorrow_detail.setStyleSheet(
            "font-size:12px; color:#7f8c8d; border:none;"
        )
        today_layout.addWidget(today_title)
        today_layout.addWidget(self.today_main)
        today_layout.addWidget(self.today_detail)
        today_layout.addWidget(self.tomorrow_main)
        today_layout.addWidget(self.tomorrow_detail)
        root.addWidget(self.today_card)

        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 3):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

    def on_show(self) -> None:
        self._refresh_cycles()
        self.refresh()

    def _refresh_cycles(self) -> None:
        # 收集预算中出现的周期 + 最近12个周期，去重后按时间倒序
        from datetime import date as _date

        cycle_set = set(b.year_month for b in self.ctx.budgets)
        for c in self.ctx.recent_cycles(12):
            cycle_set.add(c)
        # 按日期排序
        def _key(cs: str):
            try:
                return _date.fromisoformat(cs)
            except ValueError:
                return _date.min
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

    def refresh(self) -> None:
        self._refresh_cycles()
        cs = self.cycle_combo.currentData() or self.ctx.current_cycle_start()
        rows = [b for b in self.ctx.budgets if b.year_month == cs]
        rows.sort(key=lambda b: b.category_id)

        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))

        total_budget = 0.0
        total_used = 0.0
        for i, b in enumerate(rows):
            cat = self.ctx.category_by_id(b.category_id)
            cat_name = cat.name if cat else "(已删除)"
            used = self.ctx.cycle_category_total(cs, b.category_id)
            remain = b.amount - used
            pct = int(used / b.amount * 100) if b.amount > 0 else 0
            total_budget += b.amount
            total_used += used

            name_item = QTableWidgetItem(cat_name)
            name_item.setData(Qt.UserRole, b.id)
            budget_item = QTableWidgetItem(f"¥{b.amount:,.2f}")
            used_item = QTableWidgetItem(f"¥{used:,.2f}")
            remain_item = QTableWidgetItem(f"¥{remain:,.2f}")

            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, budget_item)
            self.table.setItem(i, 2, used_item)
            self.table.setItem(i, 3, remain_item)

            bar = QProgressBar()
            bar.setRange(0, max(b.amount, 1))
            bar.setValue(int(used))
            bar.setFormat(f"{pct}%")
            # 超支红色、临界橙色、正常绿色
            if pct >= 100:
                bar.setStyleSheet(
                    "QProgressBar::chunk { background:#e74c3c; }"
                )
            elif pct >= 80:
                bar.setStyleSheet(
                    "QProgressBar::chunk { background:#f39c12; }"
                )
            self.table.setCellWidget(i, 4, bar)

        # 概览
        label = self.ctx.cycle_label(cs)
        if total_budget > 0:
            total_pct = total_used / total_budget * 100
            self.summary.setText(
                f"{label} 总预算 ¥{total_budget:,.2f}，"
                f"已用 ¥{total_used:,.2f}（{total_pct:.1f}%），"
                f"剩余 ¥{total_budget - total_used:,.2f}"
            )
        else:
            self.summary.setText(f"{label} 暂无预算，点击右上角【新增预算】开始")

        self._refresh_advice(cs, total_budget, total_used)
        self._refresh_today(cs, total_budget, total_used)

    def _refresh_advice(self, cs: str, total_budget: float, total_used: float) -> None:
        """根据预算与剩余天数，刷新每日建议卡片。

        - 日均预算 = 总预算 / 周期天数
        - 今日建议消费 = 剩余预算 / 剩余天数（仅对当前周期生效）
        """
        if total_budget <= 0:
            self.advice_main.setText("暂无预算")
            self.advice_main.setStyleSheet(
                "font-size:20px; font-weight:700; color:#95a5a6; border:none;"
            )
            self.advice_detail.setText("先在上方新增预算，即可获得每日消费建议。")
            return

        s, e = self.ctx.cycle_range(cs)
        days_in_cycle = self.ctx.cycle_days(cs)
        daily_avg = total_budget / days_in_cycle if days_in_cycle > 0 else 0
        remain_budget = total_budget - total_used

        today = date.today()
        is_current = (cs == self.ctx.current_cycle_start())

        if is_current:
            # 当前周期：剩余天数包含今天
            days_left = (e - today).days + 1 if today < e else 0
            if remain_budget <= 0:
                # 已超支
                self.advice_main.setText("本周期已超支，建议暂停非必要支出")
                self.advice_main.setStyleSheet(
                    "font-size:18px; font-weight:700; color:#e74c3c; border:none;"
                )
                self.advice_detail.setText(
                    f"已超出预算 ¥{-remain_budget:,.2f}；"
                    f"日均预算 ¥{daily_avg:,.2f}，剩余 {days_left} 天。"
                )
            elif days_left <= 0:
                self.advice_main.setText("本周期最后一天")
                self.advice_main.setStyleSheet(
                    "font-size:18px; font-weight:700; color:#7f8c8d; border:none;"
                )
                self.advice_detail.setText(
                    f"剩余预算 ¥{remain_budget:,.2f}，明日开启新周期。"
                )
            else:
                suggest = remain_budget / days_left
                # 健康度：建议值 vs 日均预算
                ratio = suggest / daily_avg if daily_avg > 0 else 0
                if ratio >= 1.2:
                    color = "#27ae60"
                    tip = "节余充足，可适当宽松消费。"
                elif ratio >= 0.8:
                    color = "#2980b9"
                    tip = "节奏正常，保持即可。"
                elif ratio >= 0.3:
                    color = "#f39c12"
                    tip = "偏紧，注意控制非必要支出。"
                else:
                    color = "#e74c3c"
                    tip = "告急，建议仅保留必要支出。"
                self.advice_main.setText(f"今日建议消费 ¥{suggest:,.2f}")
                self.advice_main.setStyleSheet(
                    f"font-size:20px; font-weight:700; color:{color}; border:none;"
                )
                self.advice_detail.setText(
                    f"日均预算 ¥{daily_avg:,.2f}；剩余预算 ¥{remain_budget:,.2f}，"
                    f"剩余 {days_left} 天（含今日）。{tip}"
                )
        else:
            # 非当前周期：仅展示日均预算与最终状态
            self.advice_main.setText(f"日均预算 ¥{daily_avg:,.2f}")
            if remain_budget >= 0:
                self.advice_main.setStyleSheet(
                    "font-size:20px; font-weight:700; color:#2980b9; border:none;"
                )
                self.advice_detail.setText(
                    f"该周期共 {days_in_cycle} 天；总预算 ¥{total_budget:,.2f}，"
                    f"实际支出 ¥{total_used:,.2f}，结余 ¥{remain_budget:,.2f}。"
                )
            else:
                self.advice_main.setStyleSheet(
                    "font-size:20px; font-weight:700; color:#e74c3c; border:none;"
                )
                self.advice_detail.setText(
                    f"该周期共 {days_in_cycle} 天；总预算 ¥{total_budget:,.2f}，"
                    f"实际支出 ¥{total_used:,.2f}，超支 ¥{-remain_budget:,.2f}。"
                )

    def _refresh_today(self, cs: str, total_budget: float, total_used: float) -> None:
        """刷新今日汇总 + 明日建议卡片。

        - 今日已消费：从交易里按今日日期统计支出总额与笔数
        - 明日可用 = (剩余预算 - 今日已消费) / (剩余天数 - 1)
          其中剩余天数含今日，故明日开始的天数为「剩余天数 - 1」
        """
        today = date.today()
        is_current = (cs == self.ctx.current_cycle_start())

        # 非当前周期不显示今日/明日建议
        if not is_current or total_budget <= 0:
            self.today_main.setText("--")
            self.today_main.setStyleSheet(
                "font-size:16px; font-weight:700; color:#95a5a6; border:none;"
            )
            self.today_detail.setText("仅当前周期显示今日汇总与明日建议。")
            self.tomorrow_main.setText("--")
            self.tomorrow_main.setStyleSheet(
                "font-size:18px; font-weight:700; color:#95a5a6; border:none;"
            )
            self.tomorrow_detail.setText("")
            return

        s, e = self.ctx.cycle_range(cs)
        days_in_cycle = self.ctx.cycle_days(cs)
        daily_avg = total_budget / days_in_cycle if days_in_cycle > 0 else 0
        remain_budget = total_budget - total_used
        today_expense, today_count = self.ctx.day_expense(today)
        days_left_incl_today = (e - today).days + 1 if today < e else 0

        # 今日汇总
        diff = today_expense - daily_avg
        if diff <= 0:
            today_color = "#27ae60"
            today_tip = f"低于日均预算 ¥{-diff:,.2f}，节奏良好。"
        elif diff <= daily_avg * 0.5:
            today_color = "#f39c12"
            today_tip = f"超出日均预算 ¥{diff:,.2f}，明日预算会相应减少。"
        else:
            today_color = "#e74c3c"
            today_tip = f"超出日均预算 ¥{diff:,.2f}，建议明日控制消费。"

        self.today_main.setText(
            f"今日已消费 ¥{today_expense:,.2f}（{today_count} 笔）"
        )
        self.today_main.setStyleSheet(
            f"font-size:16px; font-weight:700; color:{today_color}; border:none;"
        )
        self.today_detail.setText(
            f"日均预算 ¥{daily_avg:,.2f}；{today_tip}"
        )

        # 明日建议
        # 剩余天数(含今日)，明天开始剩余 = days_left_incl_today - 1
        days_after_today = max(days_left_incl_today - 1, 0)
        # 明日剩余预算 = 周期剩余预算 - 今日已消费
        remain_after_today = remain_budget - today_expense

        if days_left_incl_today <= 0:
            # 今日是周期最后一天
            self.tomorrow_main.setText("明日开启新周期")
            self.tomorrow_main.setStyleSheet(
                "font-size:18px; font-weight:700; color:#7f8c8d; border:none;"
            )
            self.tomorrow_detail.setText(
                f"本周期剩余 ¥{remain_budget:,.2f}；明日切到下一周期请重新设定预算。"
            )
        elif remain_after_today <= 0:
            # 今日消费后周期已超支
            self.tomorrow_main.setText("明日预算 ¥0.00")
            self.tomorrow_main.setStyleSheet(
                "font-size:18px; font-weight:700; color:#e74c3c; border:none;"
            )
            self.tomorrow_detail.setText(
                f"本周期已超支 ¥{-remain_after_today:,.2f}，"
                f"明日建议暂停非必要支出，剩余 {days_after_today} 天。"
            )
        elif days_after_today <= 0:
            # 仅今天剩余，明日开启新周期
            self.tomorrow_main.setText("明日开启新周期")
            self.tomorrow_main.setStyleSheet(
                "font-size:18px; font-weight:700; color:#7f8c8d; border:none;"
            )
            self.tomorrow_detail.setText(
                f"本周期剩余 ¥{remain_after_today:,.2f}；明日切到下一周期。"
            )
        else:
            tomorrow_suggest = remain_after_today / days_after_today
            ratio = tomorrow_suggest / daily_avg if daily_avg > 0 else 0
            if ratio >= 1.2:
                tom_color = "#27ae60"
                tom_tip = "明日预算宽松，可适当消费。"
            elif ratio >= 0.8:
                tom_color = "#2980b9"
                tom_tip = "明日预算正常，保持节奏。"
            elif ratio >= 0.3:
                tom_color = "#f39c12"
                tom_tip = "明日预算偏紧，控制非必要支出。"
            else:
                tom_color = "#e74c3c"
                tom_tip = "明日预算告急，仅保留必要支出。"
            self.tomorrow_main.setText(f"明日可用 ¥{tomorrow_suggest:,.2f}")
            self.tomorrow_main.setStyleSheet(
                f"font-size:18px; font-weight:700; color:{tom_color}; border:none;"
            )
            self.tomorrow_detail.setText(
                f"剩余预算 ¥{remain_after_today:,.2f} ÷ 剩余 {days_after_today} 天。{tom_tip}"
            )

    def _current(self) -> Optional[Budget]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        bid = item.data(Qt.UserRole)
        for b in self.ctx.budgets:
            if b.id == bid:
                return b
        return None

    def _on_add(self) -> None:
        dlg = BudgetDialog(self.ctx, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                b = dlg.build_budget()
            except ValueError as e:
                QMessageBox.warning(self, "提示", str(e))
                return
            # 同月同分类去重
            for ex in self.ctx.budgets:
                if ex.year_month == b.year_month and ex.category_id == b.category_id:
                    QMessageBox.warning(self, "提示", "该月份与分类的预算已存在，请编辑已有项")
                    return
            self.ctx.budgets.append(b)
            self.ctx.save_all()

    def _on_edit(self, *args) -> None:
        b = self._current()
        if not b:
            QMessageBox.information(self, "提示", "请先选择一个预算项")
            return
        dlg = BudgetDialog(self.ctx, b, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                dlg.build_budget()
            except ValueError as e:
                QMessageBox.warning(self, "提示", str(e))
                return
            self.ctx.save_all()

    def _on_delete(self) -> None:
        b = self._current()
        if not b:
            QMessageBox.information(self, "提示", "请先选择一个预算项")
            return
        ok = QMessageBox.question(self, "确认删除", "删除该预算项吗？")
        if ok != QMessageBox.Yes:
            return
        self.ctx.budgets = [x for x in self.ctx.budgets if x.id != b.id]
        self.ctx.save_all()
