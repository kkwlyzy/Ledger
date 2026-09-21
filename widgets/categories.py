"""分类管理页面：增删改收支分类、设置颜色。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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

from models import TYPE_EXPENSE, TYPE_INCOME, Category


class CategoryDialog(QDialog):
    """新增/编辑分类对话框。"""

    def __init__(self, ctx, category: Optional[Category] = None, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._editing = category
        self.setWindowTitle("编辑分类" if category else "新增分类")
        self._build_ui()
        if category:
            self._load(category)

    def _build_ui(self) -> None:
        form = QFormLayout(self)

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("分类名称")

        self.type_combo = QComboBox(self)
        self.type_combo.addItem("支出", TYPE_EXPENSE)
        self.type_combo.addItem("收入", TYPE_INCOME)

        self.color_btn = QPushButton("选择颜色", self)
        self.color_btn.clicked.connect(self._pick_color)
        self._color = "#7E9BE6"
        self._sync_color_btn()

        form.addRow("名称：", self.name_edit)
        form.addRow("类型：", self.type_combo)
        form.addRow("颜色：", self.color_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _sync_color_btn(self) -> None:
        self.color_btn.setStyleSheet(
            f"background:{self._color}; color:white; padding:6px 14px; border:none;"
        )

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "选择颜色")
        if c.isValid():
            self._color = c.name()
            self._sync_color_btn()

    def _load(self, c: Category) -> None:
        self.name_edit.setText(c.name)
        idx = self.type_combo.findData(c.type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self._color = c.color
        self._sync_color_btn()

    def build_category(self) -> Category:
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("请填写名称")
        if self._editing:
            c = self._editing
            c.name = name
            c.type = self.type_combo.currentData()
            c.color = self._color
            return c
        return Category(
            name=name,
            type=self.type_combo.currentData(),
            color=self._color,
        )


class CategoriesPage(QWidget):
    """分类管理页面：表格 + 新增/编辑/删除。"""

    COLUMNS = ["名称", "类型", "颜色"]

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

        title = QLabel("分类管理", self)
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        bar = QHBoxLayout()
        self.btn_add = QPushButton("新增分类", self)
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
        root.addLayout(bar)

        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(self._on_edit)
        root.addWidget(self.table, 1)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        cats = sorted(self.ctx.categories, key=lambda c: (c.type, c.name))
        self.table.setRowCount(0)
        self.table.setRowCount(len(cats))
        for i, c in enumerate(cats):
            name_item = QTableWidgetItem(c.name)
            name_item.setData(Qt.UserRole, c.id)
            type_item = QTableWidgetItem("收入" if c.type == TYPE_INCOME else "支出")
            type_item.setTextAlignment(Qt.AlignCenter)
            color_item = QTableWidgetItem("")
            color_item.setData(Qt.BackgroundRole, QColor(c.color))
            color_item.setData(Qt.UserRole, c.id)
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, type_item)
            self.table.setItem(i, 2, color_item)

    def _current(self) -> Optional[Category]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        cid = item.data(Qt.UserRole)
        for c in self.ctx.categories:
            if c.id == cid:
                return c
        return None

    def _on_add(self) -> None:
        dlg = CategoryDialog(self.ctx, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                c = dlg.build_category()
            except ValueError as e:
                QMessageBox.warning(self, "提示", str(e))
                return
            self.ctx.categories.append(c)
            self.ctx.save_all()

    def _on_edit(self, *args) -> None:
        c = self._current()
        if not c:
            QMessageBox.information(self, "提示", "请先选择一个分类")
            return
        dlg = CategoryDialog(self.ctx, c, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                dlg.build_category()
            except ValueError as e:
                QMessageBox.warning(self, "提示", str(e))
                return
            self.ctx.save_all()

    def _on_delete(self) -> None:
        c = self._current()
        if not c:
            QMessageBox.information(self, "提示", "请先选择一个分类")
            return
        # 检查是否有交易使用
        used = sum(1 for t in self.ctx.transactions if t.category_id == c.id)
        if used > 0:
            QMessageBox.warning(
                self, "无法删除", f"该分类下还有 {used} 条交易，请先迁移或删除这些交易。"
            )
            return
        ok = QMessageBox.question(self, "确认删除", f"删除分类 [{c.name}] 吗？")
        if ok != QMessageBox.Yes:
            return
        self.ctx.categories = [x for x in self.ctx.categories if x.id != c.id]
        self.ctx.save_all()
