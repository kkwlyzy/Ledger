"""记账桌面软件主入口。

负责：初始化 QApplication、装配数据上下文、构建主窗口与左侧导航。
运行：python main.py
"""
from __future__ import annotations

import sys
import os
import shutil
import calendar
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from PySide6.QtCore import QObject, Qt, Signal, QFileSystemWatcher, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import storage
from models import Budget, Category, Transaction, TYPE_EXPENSE, TYPE_INCOME


APP_TITLE = "记账本"
APP_VERSION = "1.2.0"


class AppContext(QObject):
    """全局数据上下文。

    持有内存中的所有业务数据，并在数据变化时发出 data_changed 信号，
    各页面订阅该信号以刷新自己的视图。
    """

    data_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.categories: List[Category] = []
        self.transactions: List[Transaction] = []
        self.budgets: List[Budget] = []
        self.settings: Dict = {}

    # ---- 数据加载/保存 ----
    def reload(self) -> None:
        """从磁盘重新加载并广播刷新。"""
        self.settings = storage.load_settings()
        self.categories = storage.load_categories()
        self.transactions = storage.load_transactions()
        self.budgets = storage.load_budgets()
        self.data_changed.emit()

    def save_all(self) -> None:
        storage.save_categories(self.categories)
        storage.save_transactions(self.transactions)
        storage.save_budgets(self.budgets)
        storage.save_settings(self.settings)
        self.data_changed.emit()

    # ---- 设置 ----
    @property
    def payday(self) -> int:
        return int(self.settings.get("payday", 8))

    def set_payday(self, day: int) -> None:
        if not (1 <= day <= 28):
            raise ValueError("发薪日必须在 1~28 之间")
        self.settings["payday"] = int(day)
        self.save_all()

    # ---- 发薪周期 ----
    def cycle_range(self, cycle_start: str) -> Tuple[date, date]:
        """根据周期起始日字符串(YYYY-MM-DD)返回 [start, end) 区间。

        end = 下一个发薪日(下个月同 payday 号)，区间不含 end。
        若 payday 在下个月不存在(如 31 号)，取该月最后一天；
        payday 已限定在 1~28，月份一定存在该日。
        """
        y, m, _d = map(int, cycle_start.split("-"))
        start = date(y, m, self.payday)
        # 下个月
        nm = m + 1
        ny = y
        if nm > 12:
            nm = 1
            ny += 1
        last_day = calendar.monthrange(ny, nm)[1]
        end_day = min(self.payday, last_day)
        end = date(ny, nm, end_day)
        return start, end

    def cycle_label(self, cycle_start: str) -> str:
        """生成显示用文本：2026-09-08 ~ 2026-10-08。"""
        s, e = self.cycle_range(cycle_start)
        e_prev = e - timedelta(days=1)
        return f"{s.isoformat()} ~ {e_prev.isoformat()}"

    def cycle_for_date(self, d: date) -> str:
        """找到包含日期 d 的发薪周期的起始日字符串。

        例：payday=8，d=2026-09-15 → 落在 2026-09-08 起始的周期内。
        """
        payday = self.payday
        # 若 d.day >= payday，则周期起始日为本月 payday；否则为上月 payday
        if d.day >= payday:
            y, m = d.year, d.month
        else:
            y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
        last_day = calendar.monthrange(y, m)[1]
        start_day = min(payday, last_day)
        return date(y, m, start_day).isoformat()

    def current_cycle_start(self) -> str:
        return self.cycle_for_date(date.today())

    def recent_cycles(self, n: int = 6) -> List[str]:
        """返回最近 n 个发薪周期的起始日(由远及近)，末项为当前周期。"""
        cur = self.current_cycle_start()
        out = [cur]
        for _ in range(n - 1):
            s, _e = self.cycle_range(out[-1])
            prev = s - timedelta(days=1)  # 上一天
            out.append(self.cycle_for_date(prev))
        return list(reversed(out))

    # ---- 分类辅助 ----
    def category_by_id(self, cid: str) -> Category | None:
        for c in self.categories:
            if c.id == cid:
                return c
        return None

    def categories_of_type(self, type_: str) -> List[Category]:
        return [c for c in self.categories if c.type == type_]

    # ---- 统计辅助 ----
    def cycle_summary(self, cycle_start: str):
        """返回 (income, expense) 该发薪周期总额。"""
        s, e = self.cycle_range(cycle_start)
        income = 0.0
        expense = 0.0
        for t in self.transactions:
            try:
                td = date.fromisoformat(t.date)
            except ValueError:
                continue
            if not (s <= td < e):
                continue
            if t.type == TYPE_INCOME:
                income += t.amount
            else:
                expense += t.amount
        return income, expense

    def cycle_category_total(self, cycle_start: str, category_id: str) -> float:
        s, e = self.cycle_range(cycle_start)
        total = 0.0
        for t in self.transactions:
            try:
                td = date.fromisoformat(t.date)
            except ValueError:
                continue
            if s <= td < e and t.category_id == category_id:
                total += t.amount
        return total

    def cycle_days(self, cycle_start: str) -> int:
        """周期天数(含起始日，不含结束日)。"""
        s, e = self.cycle_range(cycle_start)
        return (e - s).days

    def day_expense(self, d: date) -> Tuple[float, int]:
        """返回指定日期的 (支出总额, 支出笔数)。"""
        total = 0.0
        count = 0
        ds = d.isoformat()
        for t in self.transactions:
            if t.date == ds and t.type == TYPE_EXPENSE:
                total += t.amount
                count += 1
        return total, count


class MainWindow(QMainWindow):
    """主窗口：左侧导航 + 右侧页面堆栈 + 顶部状态栏。"""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{APP_TITLE} v{APP_VERSION}")
        self.resize(1100, 720)

        self._build_ui()
        self._build_menu()
        self.ctx.data_changed.connect(self._refresh_status)
        self.ctx.reload()
        self._refresh_status()
        self._setup_auto_refresh()

    # ---- UI 构建 ----
    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左侧导航
        self.nav = QListWidget(self)
        self.nav.setObjectName("navList")
        self.nav.setFixedWidth(180)
        self.nav.setIconSize(self.nav.iconSize().expandedTo(self.nav.iconSize()))
        for label in ("记账", "分类管理", "预算管理", "统计报表"):
            item = QListWidgetItem(label)
            item.setTextAlignment(Qt.AlignVCenter)
            self.nav.addItem(item)
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._on_nav_changed)

        # 右侧页面堆栈(延迟实例化避免循环依赖)
        self.stack = QStackedWidget(self)
        # 此处导入放方法内，避免模块加载阶段循环依赖
        from widgets.transactions import TransactionsPage
        from widgets.categories import CategoriesPage
        from widgets.budgets import BudgetsPage
        from widgets.reports import ReportsPage

        self.page_tx = TransactionsPage(self.ctx)
        self.page_cat = CategoriesPage(self.ctx)
        self.page_budget = BudgetsPage(self.ctx)
        self.page_report = ReportsPage(self.ctx)

        self.stack.addWidget(self.page_tx)
        self.stack.addWidget(self.page_cat)
        self.stack.addWidget(self.page_budget)
        self.stack.addWidget(self.page_report)

        layout.addWidget(self._wrap_frame(self.nav))
        layout.addWidget(self.stack, 1)
        central.setLayout(layout)
        self.setCentralWidget(central)

        # 状态栏(本月收支)
        self.status_income = QLabel("本月收入：--")
        self.status_expense = QLabel("本月支出：--")
        self.status_balance = QLabel("结余：--")
        for w in (self.status_income, self.status_expense, self.status_balance):
            self.statusBar().addPermanentWidget(w)

    def _wrap_frame(self, widget: QWidget) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("navFrame")
        v = QVBoxLayout(frame)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        title = QLabel(APP_TITLE, frame)
        title.setObjectName("navTitle")
        title.setFixedHeight(56)
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)
        v.addWidget(widget, 1)
        return frame

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        m_file = menubar.addMenu("文件(&F)")
        act_save = QAction("保存(&S)", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self._on_save)
        m_file.addAction(act_save)
        m_file.addSeparator()
        act_quit = QAction("退出(&Q)", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_set = menubar.addMenu("设置(&E)")
        act_payday = QAction("发薪日(&P)...", self)
        act_payday.triggered.connect(self._on_set_payday)
        m_set.addAction(act_payday)
        act_restore = QAction("从备份恢复(&R)...", self)
        act_restore.triggered.connect(self._on_restore_backup)
        m_set.addAction(act_restore)

        m_help = menubar.addMenu("帮助(&H)")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._on_about)
        m_help.addAction(act_about)

    def _on_restore_backup(self) -> None:
        """从 data/backup/ 选一份历史备份覆盖当前数据。"""
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        backup_dir = os.path.join(storage.DATA_DIR, "backup")
        if not os.path.isdir(backup_dir):
            QMessageBox.information(self, "提示", "暂无备份文件。")
            return
        # 列出所有备份(按时间倒序)
        files = sorted(
            (f for f in os.listdir(backup_dir) if f.endswith(".bak")),
            reverse=True,
        )
        if not files:
            QMessageBox.information(self, "提示", "暂无备份文件。")
            return
        target_kind, ok = QInputDialog.getItem(
            self,
            "选择恢复目标",
            "选择要恢复的数据类型：",
            ["transactions.json (交易)", "budgets.json (预算)", "categories.json (分类)"],
            0,
            False,
        )
        if not ok:
            return
        base = target_kind.split(" ")[0]
        matching = [f for f in files if f.startswith(base + ".")]
        if not matching:
            QMessageBox.information(self, "提示", f"未找到 {base} 的备份。")
            return
        choice, ok = QInputDialog.getItem(
            self, "选择备份", f"选择要恢复的 {base} 备份(按时间倒序)：",
            matching, 0, False,
        )
        if not ok:
            return
        src = os.path.join(backup_dir, choice)
        # 确认
        confirm = QMessageBox.question(
            self, "确认恢复",
            f"将用备份文件覆盖当前 {base}：\n{choice}\n\n当前数据会被覆盖(覆盖前会再备份一次)。",
        )
        if confirm != QMessageBox.Yes:
            return
        # 直接拷贝覆盖(走 storage 的备份逻辑会先备份当前)
        target = os.path.join(storage.DATA_DIR, base)
        # 先走一次 storage 写入触发当前数据备份
        shutil.copy2(src, target)
        self.ctx.reload()
        QMessageBox.information(self, "已恢复", f"已从 {choice} 恢复 {base}")

    def _on_set_payday(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        cur = self.ctx.payday
        val, ok = QInputDialog.getInt(
            self,
            "设置发薪日",
            "请输入发薪日(1~28，默认 8)：\n预算周期将按「发薪日 → 下个发薪日」计算。",
            value=cur,
            minValue=1,
            maxValue=28,
        )
        if not ok:
            return
        try:
            self.ctx.set_payday(val)
        except ValueError as e:
            QMessageBox.warning(self, "提示", str(e))
            return
        QMessageBox.information(
            self, "已更新", f"发薪日已设为每月 {val} 号\n当前周期：{self.ctx.cycle_label(self.ctx.current_cycle_start())}"
        )

    # ---- 槽函数 ----
    def _on_nav_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        page = self.stack.widget(row)
        if hasattr(page, "on_show"):
            page.on_show()

    def _on_save(self) -> None:
        self.ctx.save_all()
        self.statusBar().showMessage("已保存", 2000)

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            f"<b>{APP_TITLE}</b> v{APP_VERSION}<br><br>"
            f"基于 PySide6 的本地记账软件。<br>"
            f"数据存储：JSON 文件（位于 data/ 目录）",
        )

    def _refresh_status(self) -> None:
        cycle = self.ctx.current_cycle_start()
        income, expense = self.ctx.cycle_summary(cycle)
        self.status_income.setText(f"本周期收入：¥{income:,.2f}")
        self.status_expense.setText(f"本周期支出：¥{expense:,.2f}")
        self.status_balance.setText(f"结余：¥{income - expense:,.2f}")

    # ---- 自动刷新：监视外部数据文件变化 ----
    def _setup_auto_refresh(self) -> None:
        """监视 data 目录，外部(如 AI/CLI)写入后自动重载并刷新界面。

        用 QFileSystemWatcher 监听 4 个 JSON 文件，变化后用 QTimer
        防抖 300ms 再 reload，避免连续写入触发多次刷新。
        """
        import os as _os

        data_dir = getattr(storage, "DATA_DIR", None)
        if not data_dir or not _os.path.isdir(data_dir):
            return

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_data_changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._do_reload)
        # 监视目录（目录内容变化比单文件更可靠，覆盖新增/替换/删除）
        self._watcher.addPath(data_dir)

    def _on_data_changed(self, path: str) -> None:
        # 目录里任何变化都触发防抖重载
        self._debounce.start()

    def _do_reload(self) -> None:
        # 重新读盘并广播刷新；异常时静默，避免打断界面
        try:
            self.ctx.reload()
        except Exception:
            pass

    # ---- 关闭事件 ----
    def closeEvent(self, event) -> None:
        # 关闭前自动保存，避免数据丢失
        self.ctx.save_all()
        # 同步一份到异地备份目录(D盘)
        storage.backup_to_remote()
        super().closeEvent(event)


def _apply_style(app: QApplication) -> None:
    """应用全局 QSS 样式。"""
    app.setStyleSheet("""
        QMainWindow { background: #f5f6f8; }
        QFrame#navFrame { background: #2c3e50; }
        QLabel#navTitle { color: #ecf0f1; font-size: 18px; font-weight: 600; }
        QListWidget#navList {
            background: #2c3e50;
            color: #bdc3c7;
            border: none;
            font-size: 14px;
            outline: none;
        }
        QListWidget#navList::item {
            padding: 16px 20px;
            border-left: 3px solid transparent;
        }
        QListWidget#navList::item:selected {
            background: #243342;
            color: #ffffff;
            border-left: 3px solid #3498db;
        }
        QListWidget#navList::item:hover { background: #34495e; }
        QWidget { font-family: "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 13px; }
        QPushButton {
            background: #3498db;
            color: white;
            border: none;
            padding: 6px 14px;
            border-radius: 4px;
        }
        QPushButton:hover { background: #2980b9; }
        QPushButton:disabled { background: #95a5a6; }
        QPushButton[role="danger"] { background: #e74c3c; }
        QPushButton[role="danger"]:hover { background: #c0392b; }
        QPushButton[role="secondary"] { background: #7f8c8d; }
        QPushButton[role="secondary"]:hover { background: #6c7a7d; }
        QLineEdit, QComboBox, QDoubleSpinBox, QDateEdit {
            padding: 5px 8px;
            border: 1px solid #bdc3c7;
            border-radius: 4px;
            background: white;
        }
        QLineEdit:focus, QComboBox:focus { border-color: #3498db; }
        QTableWidget {
            gridline-color: #ecf0f1;
            background: white;
            selection-background-color: #3498db;
        }
        QHeaderView::section {
            background: #34495e;
            color: white;
            padding: 6px;
            border: none;
        }
        QStatusBar { background: #2c3e50; color: #ecf0f1; }
        QStatusBar QLabel { color: #ecf0f1; padding: 0 10px; }
        QLabel#sectionTitle { font-size: 18px; font-weight: 600; color: #2c3e50; }
        QProgressBar {
            border: 1px solid #bdc3c7;
            border-radius: 4px;
            text-align: center;
            background: #ecf0f1;
        }
        QProgressBar::chunk { background: #3498db; }
    """)


def main() -> int:
    app = QApplication(sys.argv)
    _apply_style(app)
    ctx = AppContext()
    win = MainWindow(ctx)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
