"""记账页面：交易记录的增删改查与筛选。"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import TYPE_EXPENSE, TYPE_INCOME, Category, Transaction


class TransactionDialog(QDialog):
    """新增/编辑交易对话框。"""

    def __init__(self, ctx, transaction: Optional[Transaction] = None, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._editing = transaction
        self.setWindowTitle("编辑交易" if transaction else "新增交易")
        self._build_ui()
        if transaction:
            self._load(transaction)

    def _build_ui(self) -> None:
        layout = QFormLayout(self)

        self.type_combo = QComboBox(self)
        self.type_combo.addItem("支出", TYPE_EXPENSE)
        self.type_combo.addItem("收入", TYPE_INCOME)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.category_combo = QComboBox(self)

        self.amount_spin = QDoubleSpinBox(self)
        self.amount_spin.setRange(0.0, 1e9)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setSingleStep(10.0)
        self.amount_spin.setPrefix("¥ ")

        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy-MM-dd")

        self.note_edit = QLineEdit(self)
        self.note_edit.setPlaceholderText("备注（可选）")

        layout.addRow("类型：", self.type_combo)
        layout.addRow("分类：", self.category_combo)
        layout.addRow("金额：", self.amount_spin)
        layout.addRow("日期：", self.date_edit)
        layout.addRow("备注：", self.note_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._on_type_changed()

    def _on_type_changed(self) -> None:
        type_ = self.type_combo.currentData()
        self.category_combo.clear()
        for c in self.ctx.categories_of_type(type_):
            self.category_combo.addItem(c.name, c.id)
        # 编辑模式时尝试回选
        if self._editing and self._editing.type == type_:
            idx = self.category_combo.findData(self._editing.category_id)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)

    def _load(self, t: Transaction) -> None:
        idx = self.type_combo.findData(t.type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        # 触发类型切换重建分类后，再选分类
        idx = self.category_combo.findData(t.category_id)
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        self.amount_spin.setValue(t.amount)
        d = QDate.fromString(t.date, "yyyy-MM-dd")
        if d.isValid():
            self.date_edit.setDate(d)
        self.note_edit.setText(t.note)

    def build_transaction(self) -> Transaction:
        cat_id = self.category_combo.currentData()
        if not cat_id:
            raise ValueError("请选择分类")
        if self._editing:
            t = self._editing
            t.amount = round(self.amount_spin.value(), 2)
            t.type = self.type_combo.currentData()
            t.category_id = cat_id
            t.date = self.date_edit.date().toString("yyyy-MM-dd")
            t.note = self.note_edit.text().strip()
            return t
        return Transaction(
            amount=round(self.amount_spin.value(), 2),
            type=self.type_combo.currentData(),
            category_id=cat_id,
            date=self.date_edit.date().toString("yyyy-MM-dd"),
            note=self.note_edit.text().strip(),
        )


class TransactionsPage(QWidget):
    """记账主页面：表格 + 工具栏 + 筛选。"""

    COLUMNS = ["日期", "类型", "分类", "金额", "备注"]

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

        title = QLabel("记账", self)
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        # 工具栏：新增/编辑/删除 + 筛选
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_add = QPushButton("新增", self)
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

        bar.addWidget(QLabel("月份："))
        self.month_combo = QComboBox(self)
        self.month_combo.addItem("全部", "")
        self.month_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.month_combo)

        bar.addWidget(QLabel("类型："))
        self.type_combo = QComboBox(self)
        self.type_combo.addItem("全部", "")
        self.type_combo.addItem("支出", TYPE_EXPENSE)
        self.type_combo.addItem("收入", TYPE_INCOME)
        self.type_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.type_combo)

        bar.addWidget(QLabel("分类："))
        self.cat_combo = QComboBox(self)
        self.cat_combo.addItem("全部", "")
        self.cat_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.cat_combo)

        root.addLayout(bar)

        # 表格
        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._on_edit)
        root.addWidget(self.table, 1)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        # 重建月份/分类筛选下拉
        self._refresh_filters()

        sel_month = self.month_combo.currentData() or ""
        sel_type = self.type_combo.currentData() or ""
        sel_cat = self.cat_combo.currentData() or ""

        # 按筛选条件过滤
        rows: List[Transaction] = []
        for t in self.ctx.transactions:
            if sel_month and not t.date.startswith(sel_month):
                continue
            if sel_type and t.type != sel_type:
                continue
            if sel_cat and t.category_id != sel_cat:
                continue
            rows.append(t)
        rows.sort(key=lambda t: (t.date, t.created_at), reverse=True)

        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for i, t in enumerate(rows):
            cat = self.ctx.category_by_id(t.category_id)
            cat_name = cat.name if cat else "(已删除)"
            type_text = "收入" if t.type == TYPE_INCOME else "支出"
            amount_text = ("+¥" if t.type == TYPE_INCOME else "-¥") + f"{t.amount:,.2f}"
            items = [t.date, type_text, cat_name, amount_text, t.note]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, t.id)
                if col == 3:
                    color = "#27ae60" if t.type == TYPE_INCOME else "#c0392b"
                    item.setForeground(Qt.GlobalColor.dark) if False else None
                    # 使用 QBrush 着色更稳妥，但这里用 stylesheet 已足够
                    from PySide6.QtGui import QBrush, QColor
                    item.setForeground(QBrush(QColor(color)))
                if col == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, col, item)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

    def _refresh_filters(self) -> None:
        # 月份：从已有交易里提取，补上当前月
        months = set()
        for t in self.ctx.transactions:
            months.add(t.date[:7])
        months.add(date.today().strftime("%Y-%m"))
        ordered = sorted(months, reverse=True)
        # 月份下拉
        prev = self.month_combo.currentData() or ""
        self.month_combo.blockSignals(True)
        self.month_combo.clear()
        self.month_combo.addItem("全部", "")
        for m in ordered:
            self.month_combo.addItem(m, m)
        idx = self.month_combo.findData(prev)
        self.month_combo.setCurrentIndex(max(idx, 0))
        self.month_combo.blockSignals(False)
        # 分类下拉
        prev_cat = self.cat_combo.currentData() or ""
        self.cat_combo.blockSignals(True)
        self.cat_combo.clear()
        self.cat_combo.addItem("全部", "")
        for c in self.ctx.categories:
            self.cat_combo.addItem(c.name, c.id)
        idx = self.cat_combo.findData(prev_cat)
        self.cat_combo.setCurrentIndex(max(idx, 0))
        self.cat_combo.blockSignals(False)

    def _current_transaction(self) -> Optional[Transaction]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        tid = item.data(Qt.UserRole)
        for t in self.ctx.transactions:
            if t.id == tid:
                return t
        return None

    def _on_add(self) -> None:
        dlg = TransactionDialog(self.ctx, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                t = dlg.build_transaction()
            except ValueError as e:
                QMessageBox.warning(self, "提示", str(e))
                return
            self.ctx.transactions.append(t)
            self.ctx.save_all()

    def _on_edit(self, *args) -> None:
        t = self._current_transaction()
        if not t:
            QMessageBox.information(self, "提示", "请先选择一条交易")
            return
        dlg = TransactionDialog(self.ctx, t, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                dlg.build_transaction()  # 已就地修改 self._editing
            except ValueError as e:
                QMessageBox.warning(self, "提示", str(e))
                return
            self.ctx.save_all()

    def _on_delete(self) -> None:
        t = self._current_transaction()
        if not t:
            QMessageBox.information(self, "提示", "请先选择一条交易")
            return
        ok = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除该交易吗？\n{t.date} ¥{t.amount:.2f} {t.note}",
        )
        if ok != QMessageBox.Yes:
            return
        self.ctx.transactions = [x for x in self.ctx.transactions if x.id != t.id]
        self.ctx.save_all()
