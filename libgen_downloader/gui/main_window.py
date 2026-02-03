import csv
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, QSettings, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .dialogs import CSVImportDialog
from .style import DARK_QSS
from .toast import ToastNotification
from .workers import SearchWorker, TaskWorker
from ..config import set_proxy


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Libgen GUI 下载器")
        self.settings = QSettings("Roo", "LibgenGUI")
        self.results = []
        self.download_queue = []
        self.active_downloads = []  # [(thread, worker, task)]
        self.row_progress = {}  # queue_row -> (downloaded, total)
        self.queue_tasks = []
        self.notify_mode = "toast_all"  # toast_all | toast_fail | silent

        self._build_ui()
        self._apply_style()
        self._load_settings()

    def _apply_style(self):
        app = QApplication.instance()
        if app:
            app.setStyleSheet(DARK_QSS)
        else:
            self.setStyleSheet(DARK_QSS)

    def _build_ui(self):
        central = QWidget()
        self.setAcceptDrops(True)
        layout = QVBoxLayout()
        layout.setSpacing(10)

        search_group = QGroupBox("搜索参数")
        search_grid = QGridLayout()
        search_grid.setSpacing(10)

        search_grid.addWidget(QLabel("关键词:"), 0, 0)
        self.query_edit = QLineEdit()
        search_grid.addWidget(self.query_edit, 0, 1, 1, 3)

        search_grid.addWidget(QLabel("作者:"), 0, 4)
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("作者名 / Author")
        search_grid.addWidget(self.author_edit, 0, 5, 1, 2)
        self.author_exact_cb = QCheckBox("精确")
        search_grid.addWidget(self.author_exact_cb, 0, 7)

        search_grid.addWidget(QLabel("语言:"), 1, 0)
        self.lang_edit = QLineEdit()
        self.lang_edit.setPlaceholderText("English / Chinese")
        search_grid.addWidget(self.lang_edit, 1, 1)

        search_grid.addWidget(QLabel("格式:"), 1, 2)
        self.ext_edit = QLineEdit()
        self.ext_edit.setPlaceholderText("pdf / epub")
        search_grid.addWidget(self.ext_edit, 1, 3)

        search_grid.addWidget(QLabel("年份范围:"), 1, 4)
        year_layout = QHBoxLayout()
        self.year_min_edit = QLineEdit()
        self.year_min_edit.setPlaceholderText("最小")
        self.year_max_edit = QLineEdit()
        self.year_max_edit.setPlaceholderText("最大")
        year_layout.addWidget(self.year_min_edit)
        year_layout.addWidget(QLabel("-"))
        year_layout.addWidget(self.year_max_edit)
        search_grid.addLayout(year_layout, 1, 5, 1, 2)

        search_grid.addWidget(QLabel("返回条数:"), 2, 0)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 200)
        self.limit_spin.setValue(25)
        search_grid.addWidget(self.limit_spin, 2, 1)

        self.search_btn = QPushButton("搜索")
        self.search_btn.setObjectName("search_btn")
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_btn.clicked.connect(self.start_search)
        search_grid.addWidget(self.search_btn, 2, 2, 1, 6)

        search_group.setLayout(search_grid)
        layout.addWidget(search_group)

        config_group = QGroupBox("下载设置")
        config_layout = QHBoxLayout()
        config_layout.setSpacing(10)

        config_layout.addWidget(QLabel("下载目录:"))
        self.dir_edit = QLineEdit()
        config_layout.addWidget(self.dir_edit, 1)

        config_layout.addWidget(QLabel("代理:"))
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:7890")
        self.proxy_edit.setFixedWidth(200)
        config_layout.addWidget(self.proxy_edit)

        choose_btn = QPushButton("选择目录")
        choose_btn.clicked.connect(self.choose_directory)
        config_layout.addWidget(choose_btn)

        open_dir_btn = QPushButton("打开目录")
        open_dir_btn.clicked.connect(self.open_download_directory)
        config_layout.addWidget(open_dir_btn)

        config_layout.addWidget(QLabel("并行:"))
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 50)
        self.concurrent_spin.setValue(2)
        self.concurrent_spin.setFixedWidth(60)
        config_layout.addWidget(self.concurrent_spin)

        config_layout.addWidget(QLabel("重试:"))
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(1, 10)
        self.retry_spin.setValue(3)
        self.retry_spin.setFixedWidth(60)
        config_layout.addWidget(self.retry_spin)

        config_layout.addWidget(QLabel("提醒:"))
        self.notify_combo = QComboBox()
        self.notify_combo.addItem("轻提示：成功/失败", userData="toast_all")
        self.notify_combo.addItem("轻提示：仅失败", userData="toast_fail")
        self.notify_combo.addItem("静默（不提醒）", userData="silent")
        self.notify_combo.setFixedWidth(150)
        config_layout.addWidget(self.notify_combo)

        self.csv_btn = QPushButton("导入书籍单")
        self.csv_btn.clicked.connect(self.import_csv)
        config_layout.addWidget(self.csv_btn)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.download_btn = QPushButton("下载所选")
        self.download_btn.clicked.connect(self.start_download_selected)
        self.download_btn.setEnabled(False)
        action_row.addWidget(self.download_btn)

        self.cancel_btn = QPushButton("取消当前下载")
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.cancel_btn.setEnabled(False)
        action_row.addWidget(self.cancel_btn)

        self.clear_queue_btn = QPushButton("清除已完成")
        self.clear_queue_btn.clicked.connect(self.clear_finished_tasks)
        action_row.addWidget(self.clear_queue_btn)

        self.export_results_btn = QPushButton("导出搜索结果")
        self.export_results_btn.clicked.connect(self.export_results_csv)
        action_row.addWidget(self.export_results_btn)

        self.export_queue_btn = QPushButton("导出下载队列")
        self.export_queue_btn.clicked.connect(self.export_queue_csv)
        action_row.addWidget(self.export_queue_btn)

        action_row.addStretch()
        layout.addLayout(action_row)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["标题", "作者", "出版社", "年份", "语言", "格式", "大小"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self.start_download_selected)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        splitter.addWidget(self.table)

        self.queue_table = QTableWidget(0, 8)
        self.queue_table.setHorizontalHeaderLabels(["关键词", "语言", "格式", "年≥", "年≤", "状态", "进度", "信息"])
        self.queue_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self.show_queue_context_menu)
        splitter.addWidget(self.queue_table)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        bottom_layout.addWidget(self.progress_bar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        bottom_layout.addWidget(self.log_view)

        bottom_widget.setLayout(bottom_layout)
        splitter.addWidget(bottom_widget)

        layout.addWidget(splitter)

        central.setLayout(layout)
        self.setCentralWidget(central)
        self.resize(1200, 800)

        self._setup_menu()

    def _setup_menu(self):
        menu = self.menuBar().addMenu("文件")
        exit_action = QAction(QIcon.fromTheme("application-exit"), "退出", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

    def append_log(self, message, level="info"):
        self.log_view.append(f"[{level.upper()}] {message}")
        self.log_view.ensureCursorVisible()

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    def open_download_directory(self):
        path = self.dir_edit.text().strip()
        if Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "提示", "目录不存在")

    def _load_settings(self):
        self.dir_edit.setText(self.settings.value("download_dir", str(Path.cwd() / "downloads")))
        self.lang_edit.setText(self.settings.value("last_lang", ""))
        self.ext_edit.setText(self.settings.value("last_ext", ""))
        self.author_edit.setText(self.settings.value("last_author", ""))
        self.author_exact_cb.setChecked(bool(int(self.settings.value("author_exact", 0))))
        self.proxy_edit.setText(self.settings.value("proxy_url", ""))
        self.notify_mode = self.settings.value("notify_mode", "toast_all")
        idx = self.notify_combo.findData(self.notify_mode)
        if idx >= 0:
            self.notify_combo.setCurrentIndex(idx)
        self.concurrent_spin.setValue(int(self.settings.value("concurrent_downloads", 2)))
        self.retry_spin.setValue(int(self.settings.value("download_retries", 3)))
        self._apply_proxy()

    def _save_settings(self):
        self.settings.setValue("download_dir", self.dir_edit.text())
        self.settings.setValue("last_lang", self.lang_edit.text())
        self.settings.setValue("last_ext", self.ext_edit.text())
        self.settings.setValue("last_author", self.author_edit.text())
        self.settings.setValue("author_exact", 1 if self.author_exact_cb.isChecked() else 0)
        self.settings.setValue("proxy_url", self.proxy_edit.text())
        self.settings.setValue("notify_mode", self.notify_combo.currentData())
        self.settings.setValue("concurrent_downloads", self.concurrent_spin.value())
        self.settings.setValue("download_retries", self.retry_spin.value())

    def _apply_proxy(self):
        set_proxy(self.proxy_edit.text().strip())

    def clear_finished_tasks(self):
        for i in range(self.queue_table.rowCount() - 1, -1, -1):
            status = self.queue_table.item(i, 5).text()
            if status in ["成功", "失败", "已取消"]:
                self.queue_table.removeRow(i)

    def show_table_context_menu(self, pos):
        menu = QMenu()
        download_act = menu.addAction("下载所选")
        copy_title_act = menu.addAction("复制标题")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == download_act:
            self.start_download_selected()
        elif action == copy_title_act:
            selected = self.table.selectedItems()
            if selected:
                row = selected[0].row()
                title = self.table.item(row, 0).text()
                QApplication.clipboard().setText(title)

    def show_queue_context_menu(self, pos):
        menu = QMenu()
        remove_act = menu.addAction("从队列移除")

        action = menu.exec(self.queue_table.viewport().mapToGlobal(pos))
        if action == remove_act:
            rows = {index.row() for index in self.queue_table.selectedIndexes()}
            for r in sorted(rows, reverse=True):
                self.queue_table.removeRow(r)

    def export_results_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "提示", "没有搜索结果可导出")
            return

        query = self.query_edit.text().strip() or "search_results"
        out_dir = Path(self.dir_edit.text().strip() or "downloads")
        out_dir.mkdir(parents=True, exist_ok=True)
        default_path = str(out_dir / f"{query}.csv")

        path, _ = QFileDialog.getSaveFileName(self, "导出搜索结果", default_path, "CSV Files (*.csv)")
        if path:
            try:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    headers = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
                    writer.writerow(headers)
                    for row in range(self.table.rowCount()):
                        row_data = [
                            self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(self.table.columnCount())
                        ]
                        writer.writerow(row_data)
                QMessageBox.information(self, "成功", f"搜索结果已导出到：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出出错：{e}")

    def export_queue_csv(self):
        if self.queue_table.rowCount() == 0:
            QMessageBox.information(self, "提示", "下载队列为空")
            return

        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(self.dir_edit.text().strip() or "downloads")
        out_dir.mkdir(parents=True, exist_ok=True)
        default_path = str(out_dir / f"queue_{now_str}.csv")

        path, _ = QFileDialog.getSaveFileName(self, "导出下载队列", default_path, "CSV Files (*.csv)")
        if path:
            try:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    headers = [self.queue_table.horizontalHeaderItem(i).text() for i in range(self.queue_table.columnCount())]
                    writer.writerow(headers)
                    for row in range(self.queue_table.rowCount()):
                        row_data = [
                            self.queue_table.item(row, col).text() if self.queue_table.item(row, col) else ""
                            for col in range(self.queue_table.columnCount())
                        ]
                        writer.writerow(row_data)
                QMessageBox.information(self, "成功", f"下载队列已导出到：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出出错：{e}")

    # --- 搜索 ---
    def start_search(self):
        query = self.query_edit.text().strip()
        if not query:
            QMessageBox.warning(self, "提示", "请输入搜索关键词")
            return

        self.search_btn.setEnabled(False)
        self.append_log(f"开始搜索：{query}")
        self._save_settings()
        self._apply_proxy()

        year_min = self._safe_int(self.year_min_edit.text())
        year_max = self._safe_int(self.year_max_edit.text())

        self.search_thread = QThread()
        self.search_worker = SearchWorker(
            query=query,
            limit=self.limit_spin.value(),
            language=self.lang_edit.text().strip() or None,
            ext=self.ext_edit.text().strip() or None,
            year_min=year_min,
            year_max=year_max,
            author=self.author_edit.text().strip() or None,
            author_exact=self.author_exact_cb.isChecked(),
        )
        self.search_worker.moveToThread(self.search_thread)
        self.search_thread.started.connect(self.search_worker.run)
        self.search_worker.finished.connect(self.on_search_finished)
        self.search_worker.error.connect(self.on_search_error)
        self.search_worker.log.connect(self.on_worker_log)
        self.search_worker.finished.connect(self.search_thread.quit)
        self.search_worker.finished.connect(self.search_worker.deleteLater)
        self.search_thread.finished.connect(self.search_thread.deleteLater)
        self.search_thread.start()

    def on_worker_log(self, level, message):
        self.append_log(message, level)

    def on_search_finished(self, results):
        self.search_btn.setEnabled(True)
        self.results = results
        self.download_btn.setEnabled(bool(results))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))
        for row, r in enumerate(results):
            title_item = QTableWidgetItem(r.get("title") or "")
            title_item.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, 0, title_item)
            self.table.setItem(row, 1, QTableWidgetItem(r.get("author") or ""))
            self.table.setItem(row, 2, QTableWidgetItem(r.get("publisher") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(r.get("year") or ""))
            self.table.setItem(row, 4, QTableWidgetItem(r.get("language") or ""))
            self.table.setItem(row, 5, QTableWidgetItem(r.get("extension") or ""))
            self.table.setItem(row, 6, QTableWidgetItem(r.get("size") or ""))
        self.table.setSortingEnabled(True)
        self.append_log(f"搜索完成，获得 {len(results)} 条结果")

    def on_search_error(self, message):
        self.search_btn.setEnabled(True)
        self.append_log(f"搜索失败：{message}", level="error")
        QMessageBox.critical(self, "搜索失败", message)

    # --- 下载 ---
    def start_download_selected(self):
        if not self.results:
            QMessageBox.information(self, "提示", "请先搜索并选择结果")
            return

        selected_indices = self.table.selectionModel().selectedRows()
        if not selected_indices:
            QMessageBox.information(self, "提示", "请选择至少一行进行下载")
            return

        tasks = []
        for index in selected_indices:
            row = index.row()
            original_idx = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if original_idx is not None and original_idx < len(self.results):
                result_data = self.results[original_idx]
                tasks.append({"type": "result", "result": result_data, "queue_row": self._add_queue_row_from_result(result_data)})
        self.download_queue.extend(tasks)
        self.queue_tasks.extend(tasks)
        self.append_log(f"准备下载 {len(tasks)} 个条目")
        self.progress_bar.setValue(0)
        self._start_next_download()

    def _start_next_download(self):
        while self.download_queue and len(self.active_downloads) < self.concurrent_spin.value():
            task = self.download_queue.pop(0)
            row = task.get("queue_row")
            self.append_log(f"开始下载：{task.get('query') or task.get('result', {}).get('title')}")
            self._apply_proxy()
            out_dir = self.dir_edit.text().strip() or str(Path.cwd() / "downloads")
            Path(out_dir).mkdir(parents=True, exist_ok=True)

            if row is not None and row < self.queue_table.rowCount():
                self.queue_table.setItem(row, 5, QTableWidgetItem("下载中"))
                self.queue_table.setItem(row, 6, QTableWidgetItem("0%"))
                self.queue_table.setItem(row, 7, QTableWidgetItem(""))

            thread = QThread()
            worker = TaskWorker(task, out_dir, limit=self.limit_spin.value(), max_retries=self.retry_spin.value())
            worker.moveToThread(thread)

            thread.started.connect(worker.run)
            worker.finished.connect(lambda path, r=row, w=worker, t=thread: self.on_download_finished(r, path))
            worker.error.connect(lambda msg, r=row, w=worker, t=thread: self.on_download_error(r, msg))
            worker.log.connect(self.on_worker_log)
            worker.progress.connect(lambda d, tot, r=row: self.on_download_progress_row(r, d, tot))
            worker.finished.connect(thread.quit)
            worker.error.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            worker.error.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.start()

            self.active_downloads.append((thread, worker, task))
            self.cancel_btn.setEnabled(True)

        if not self.active_downloads and not self.download_queue:
            self.append_log("下载队列完成")
            self.cancel_btn.setEnabled(False)

    def on_download_progress_row(self, row, downloaded, total):
        if row is None or row >= self.queue_table.rowCount():
            return
        self.row_progress[row] = (downloaded, total)
        if total and total > 0:
            percent = int(downloaded / total * 100)
            text = f"{percent}% ({downloaded / 1024 / 1024:.2f}MB / {total / 1024 / 1024:.2f}MB)"
        else:
            percent = 0
            text = f"{downloaded / 1024 / 1024:.2f}MB"
        self.queue_table.setItem(row, 6, QTableWidgetItem(f"{percent}%"))
        self.queue_table.setItem(row, 7, QTableWidgetItem(text))
        self._update_overall_progress()

    def on_download_finished(self, row, path):
        self.append_log(f"下载完成：{path}", level="success")
        self._update_queue_status(row, "成功", path)
        self.row_progress.pop(row, None)
        self._notify("success", "下载完成", f"已保存到：\n{path}")
        self._remove_active_by_row(row)
        self._start_next_download()

    def on_download_error(self, row, message):
        self.append_log(f"下载失败：{message}", level="error")
        self._update_queue_status(row, "失败", message)
        self.row_progress.pop(row, None)
        self._notify("error", "下载失败", message)
        self._remove_active_by_row(row)
        self._start_next_download()

    def cancel_download(self):
        if not self.active_downloads:
            return
        self.append_log("请求取消所有进行中的下载", level="warning")
        for _thread, worker, _task in list(self.active_downloads):
            try:
                worker.cancel()
            except Exception:
                pass
        self.cancel_btn.setEnabled(False)

    def _remove_active_by_row(self, row):
        self.active_downloads = [(t, w, task) for (t, w, task) in self.active_downloads if task.get("queue_row") != row]
        if not self.active_downloads:
            self.cancel_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")
        self._update_overall_progress()

    def _update_overall_progress(self):
        if not self.row_progress:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")
            return
        percents = []
        for downloaded, total in self.row_progress.values():
            if total and total > 0:
                percents.append(max(0, min(100, int(downloaded / total * 100))))
        if percents:
            avg = sum(percents) / len(percents)
            self.progress_bar.setValue(int(avg))
            self.progress_bar.setFormat(f"并行 {len(self.row_progress)} 个任务，平均 {avg:.0f}%")
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(f"并行 {len(self.row_progress)} 个任务")

    def _notify(self, level, title, text):
        mode = self.notify_combo.currentData()
        if mode == "silent":
            return
        if mode == "toast_fail" and level != "error":
            return
        toast = ToastNotification(self, title, text, level="success" if level == "success" else ("error" if level == "error" else "info"))
        toast.show_relative(self)

    @staticmethod
    def _safe_int(text):
        try:
            return int(text) if text else None
        except ValueError:
            return None

    # --- 队列 & 映射辅助 ---
    def _add_queue_row_from_result(self, result):
        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        title = result.get("title") or result.get("md5") or "未知标题"
        self.queue_table.setItem(row, 0, QTableWidgetItem(title))
        self.queue_table.setItem(row, 1, QTableWidgetItem(result.get("language") or ""))
        self.queue_table.setItem(row, 2, QTableWidgetItem(result.get("extension") or ""))
        self.queue_table.setItem(row, 3, QTableWidgetItem(""))
        self.queue_table.setItem(row, 4, QTableWidgetItem(""))
        self.queue_table.setItem(row, 5, QTableWidgetItem("排队中"))
        self.queue_table.setItem(row, 6, QTableWidgetItem(""))
        self.queue_table.setItem(row, 7, QTableWidgetItem(""))
        return row

    def _add_queue_row_from_query(self, task):
        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        self.queue_table.setItem(row, 0, QTableWidgetItem(task.get("query") or ""))
        self.queue_table.setItem(row, 1, QTableWidgetItem(task.get("language") or ""))
        self.queue_table.setItem(row, 2, QTableWidgetItem(task.get("ext") or ""))
        self.queue_table.setItem(row, 3, QTableWidgetItem(str(task.get("year_min") or "")))
        self.queue_table.setItem(row, 4, QTableWidgetItem(str(task.get("year_max") or "")))
        self.queue_table.setItem(row, 5, QTableWidgetItem("排队中"))
        self.queue_table.setItem(row, 6, QTableWidgetItem(""))
        self.queue_table.setItem(row, 7, QTableWidgetItem(""))
        return row

    def _update_queue_status(self, row, status, info):
        if row is None or row >= self.queue_table.rowCount():
            return
        self.queue_table.setItem(row, 5, QTableWidgetItem(status))
        self.queue_table.setItem(row, 7, QTableWidgetItem(info))

    # --- CSV 导入 ---
    def import_csv(self):
        dlg = CSVImportDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._enqueue_csv_tasks(dlg)

    def _enqueue_csv_tasks(self, dlg: CSVImportDialog):
        tasks = dlg.tasks
        if not tasks:
            QMessageBox.information(self, "提示", "没有可入队的任务")
            return
        for t in tasks:
            t["author_exact"] = self.author_exact_cb.isChecked()
            t["queue_row"] = self._add_queue_row_from_query(t)
        self.download_queue.extend(tasks)
        self.queue_tasks.extend(tasks)
        self.append_log(f"表格导入：入队 {len(tasks)} 条任务，跳过 {dlg.skipped} 条，年份错误 {dlg.year_errors} 条，解析错误 {dlg.parse_errors} 条")
        self._start_next_download()

    # 拖拽 CSV 支持
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                lower = url.toLocalFile().lower()
                if lower.endswith(".csv") or lower.endswith(".xlsx"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            lower = path.lower()
            if lower.endswith(".csv") or lower.endswith(".xlsx"):
                dlg = CSVImportDialog(self, preset_path=path)
                if dlg.exec() == dlg.DialogCode.Accepted:
                    self._enqueue_csv_tasks(dlg)
        event.acceptProposedAction()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
