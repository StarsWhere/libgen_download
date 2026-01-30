import sys
import csv
from pathlib import Path
from threading import Event

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QProgressBar,
    QDialog,
    QComboBox,
    QCheckBox,
    QGridLayout,
    QSplitter,
)

from libgen_download import smart_search, download_for_result, DownloadError


class SearchWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    log = pyqtSignal(str, str)  # level, message

    def __init__(self, query, limit, language, ext, year_min, year_max):
        super().__init__()
        self.query = query
        self.limit = limit
        self.language = language or None
        self.ext = ext or None
        self.year_min = year_min
        self.year_max = year_max

    def run(self):
        def logger(level, message):
            self.log.emit(level, message)

        try:
            results = smart_search(
                self.query,
                limit=self.limit,
                language=self.language,
                ext=self.ext,
                year_min=self.year_min,
                year_max=self.year_max,
                logger=logger,
            )
            self.finished.emit(results)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class DownloadWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # downloaded, total (-1 when unknown)
    log = pyqtSignal(str, str)

    def __init__(self, result, out_dir, max_entry_urls=5, max_retries=3):
        super().__init__()
        self.result = result
        self.out_dir = out_dir
        self.max_entry_urls = max_entry_urls
        self.max_retries = max_retries
        self.cancel_event = Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        def logger(level, message):
            self.log.emit(level, message)

        def progress_cb(downloaded, total):
            self.progress.emit(downloaded, total if total is not None else -1)

        try:
            path = download_for_result(
                self.result,
                out_dir=self.out_dir,
                max_entry_urls=self.max_entry_urls,
                max_get_retries=self.max_retries,
                logger=logger,
                progress_cb=progress_cb,
                cancel_event=self.cancel_event,
            )
            if self.cancel_event.is_set():
                raise DownloadError("下载已被取消")
            self.finished.emit(path)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class TaskWorker(QObject):
    """统一处理两类任务：已有搜索结果 or 仅有查询参数"""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str, str)

    def __init__(self, task, out_dir, limit=25, max_entry_urls=5, max_retries=3):
        super().__init__()
        self.task = task
        self.out_dir = out_dir
        self.limit = limit
        self.max_entry_urls = max_entry_urls
        self.max_retries = max_retries
        self.cancel_event = Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        def logger(level, message):
            self.log.emit(level, message)

        def progress_cb(downloaded, total):
            self.progress.emit(downloaded, total if total is not None else -1)

        try:
            if self.task.get("type") == "result":
                result = self.task["result"]
            else:
                result = self._search_first_match(logger)
                if not result:
                    raise DownloadError("未找到匹配结果")

            path = download_for_result(
                result,
                out_dir=self.out_dir,
                max_entry_urls=self.max_entry_urls,
                max_get_retries=self.max_retries,
                logger=logger,
                progress_cb=progress_cb,
                cancel_event=self.cancel_event,
            )
            if self.cancel_event.is_set():
                raise DownloadError("下载已被取消")
            self.finished.emit(path)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))

    def _search_first_match(self, logger):
        res = smart_search(
            self.task["query"],
            limit=self.limit,
            language=self.task.get("language"),
            ext=self.task.get("ext"),
            year_min=self.task.get("year_min"),
            year_max=self.task.get("year_max"),
            logger=logger,
        )
        return res[0] if res else None


class CSVImportDialog(QDialog):
    def __init__(self, parent=None, preset_path=None):
        super().__init__(parent)
        self.setWindowTitle("导入 CSV 并映射列")
        self.resize(900, 600)
        self.file_path = preset_path
        self.tasks = []
        self.skipped = 0
        self.year_errors = 0
        self.headers = []

        self._build_ui()
        if preset_path:
            self.path_edit.setText(preset_path)
            self.load_file()

    def _build_ui(self):
        layout = QVBoxLayout()

        # 文件选择行
        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        file_row.addWidget(QLabel("CSV 文件"))
        file_row.addWidget(self.path_edit, 1)
        choose_btn = QPushButton("选择")
        choose_btn.clicked.connect(self.browse_file)
        file_row.addWidget(choose_btn)

        file_row.addWidget(QLabel("编码"))
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["utf-8", "utf-8-sig", "gbk", "big5", "iso-8859-1"])
        file_row.addWidget(self.encoding_combo)

        reload_btn = QPushButton("重新加载")
        reload_btn.clicked.connect(self.load_file)
        file_row.addWidget(reload_btn)
        layout.addLayout(file_row)

        # 映射区域
        map_grid = QGridLayout()
        self.combo_query = QComboBox()
        self.combo_lang = QComboBox()
        self.combo_ext = QComboBox()
        self.combo_year_min = QComboBox()
        self.combo_year_max = QComboBox()
        for i, (label, combo) in enumerate([
            ("搜索关键词*", self.combo_query),
            ("语言列", self.combo_lang),
            ("格式列", self.combo_ext),
            ("年份≥", self.combo_year_min),
            ("年份≤", self.combo_year_max),
        ]):
            map_grid.addWidget(QLabel(label), i, 0)
            map_grid.addWidget(combo, i, 1)
        layout.addLayout(map_grid)

        # 选项
        opts_row = QHBoxLayout()
        self.cb_skip_empty = QCheckBox("跳过空关键词行")
        self.cb_skip_empty.setChecked(True)
        opts_row.addWidget(self.cb_skip_empty)
        self.cb_ignore_year = QCheckBox("年份解析失败时跳过该行")
        self.cb_ignore_year.setChecked(True)
        opts_row.addWidget(self.cb_ignore_year)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        # 预览表
        self.preview = QTableWidget(0, 0)
        self.preview.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self.preview, 1)

        # 状态行
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("确定入队")
        ok_btn.clicked.connect(self.accept_dialog)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 CSV 文件", "", "CSV Files (*.csv);;All Files (*)")
        if path:
            self.path_edit.setText(path)
            self.load_file()

    def load_file(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请先选择 CSV 文件")
            return
        enc = self.encoding_combo.currentText()
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                self.headers = reader.fieldnames or []
                rows = []
                for i, row in enumerate(reader):
                    if i >= 100:
                        break
                    rows.append(row)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "读取失败", f"读取文件出错：{e}")
            return

        self._fill_combo_options()
        self._guess_mapping()
        self._fill_preview(rows)
        self.status_label.setText(f"预览 {len(rows)} 行，表头 {len(self.headers)} 个")

    def _fill_combo_options(self):
        combos = [self.combo_query, self.combo_lang, self.combo_ext, self.combo_year_min, self.combo_year_max]
        for c in combos:
            c.clear()
            c.addItem("<未选择>")
            for h in self.headers:
                c.addItem(h)

    def _guess_mapping(self):
        def pick(combo, candidates):
            lowered = [h.lower() for h in self.headers]
            for cand in candidates:
                if cand in lowered:
                    combo.setCurrentIndex(lowered.index(cand) + 1)
                    return

        pick(self.combo_query, ["书名", "标题", "title", "name", "query"])
        pick(self.combo_lang, ["语言", "language", "lang"])
        pick(self.combo_ext, ["类型", "格式", "ext", "format"])
        pick(self.combo_year_min, ["年份", "year", "year_min", "year from"])
        pick(self.combo_year_max, ["年份上限", "year_max", "year to", "yearend"])

    def _fill_preview(self, rows):
        self.preview.clear()
        self.preview.setRowCount(len(rows))
        self.preview.setColumnCount(len(self.headers))
        self.preview.setHorizontalHeaderLabels(self.headers)
        for r_idx, row in enumerate(rows):
            for c_idx, h in enumerate(self.headers):
                self.preview.setItem(r_idx, c_idx, QTableWidgetItem(row.get(h, "")))

    def accept_dialog(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请先选择 CSV 文件")
            return
        if self.combo_query.currentIndex() <= 0:
            QMessageBox.warning(self, "提示", "必须选择“搜索关键词”列")
            return

        enc = self.encoding_combo.currentText()
        col_query = self.combo_query.currentText()
        col_lang = self.combo_lang.currentText() if self.combo_lang.currentIndex() > 0 else None
        col_ext = self.combo_ext.currentText() if self.combo_ext.currentIndex() > 0 else None
        col_ymin = self.combo_year_min.currentText() if self.combo_year_min.currentIndex() > 0 else None
        col_ymax = self.combo_year_max.currentText() if self.combo_year_max.currentIndex() > 0 else None

        tasks = []
        skipped = 0
        year_errors = 0
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    query = (row.get(col_query) or "").strip()
                    if not query:
                        skipped += 1
                        continue
                    lang = (row.get(col_lang) or "").strip() if col_lang else None
                    ext = (row.get(col_ext) or "").strip() if col_ext else None
                    raw_ymin = row.get(col_ymin) if col_ymin else None
                    raw_ymax = row.get(col_ymax) if col_ymax else None
                    y_min = self._safe_int(raw_ymin) if raw_ymin else None
                    y_max = self._safe_int(raw_ymax) if raw_ymax else None
                    parse_error = (raw_ymin and y_min is None) or (raw_ymax and y_max is None)
                    if parse_error:
                        year_errors += 1
                        if self.cb_ignore_year.isChecked():
                            y_min = None
                            y_max = None
                        else:
                            continue
                    tasks.append({
                        "type": "query",
                        "query": query,
                        "language": lang or None,
                        "ext": ext or None,
                        "year_min": y_min,
                        "year_max": y_max,
                    })
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "读取失败", f"读取文件出错：{e}")
            return

        self.tasks = tasks
        self.skipped = skipped
        self.year_errors = year_errors
        self.accept()

    @staticmethod
    def _safe_int(val):
        if val is None:
            return None
        try:
            return int(str(val).strip()) if str(val).strip() else None
        except ValueError:
            return None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Libgen GUI 下载器")
        self.results = []
        self.download_queue = []
        self.current_download_thread = None
        self.current_download_worker = None
        self.queue_tasks = []

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setAcceptDrops(True)
        layout = QVBoxLayout()

        # 搜索行
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("关键词"))
        self.query_edit = QLineEdit()
        search_row.addWidget(self.query_edit)

        search_row.addWidget(QLabel("语言"))
        self.lang_edit = QLineEdit()
        self.lang_edit.setPlaceholderText("如 English / Chinese")
        search_row.addWidget(self.lang_edit)

        search_row.addWidget(QLabel("格式"))
        self.ext_edit = QLineEdit()
        self.ext_edit.setPlaceholderText("pdf / epub")
        search_row.addWidget(self.ext_edit)

        search_row.addWidget(QLabel("年份≥"))
        self.year_min_edit = QLineEdit()
        self.year_min_edit.setFixedWidth(60)
        search_row.addWidget(self.year_min_edit)

        search_row.addWidget(QLabel("年份≤"))
        self.year_max_edit = QLineEdit()
        self.year_max_edit.setFixedWidth(60)
        search_row.addWidget(self.year_max_edit)

        search_row.addWidget(QLabel("返回条数"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 200)
        self.limit_spin.setValue(25)
        search_row.addWidget(self.limit_spin)

        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.start_search)
        search_row.addWidget(self.search_btn)

        layout.addLayout(search_row)

        # 下载目录 + 按钮区
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("下载目录"))
        self.dir_edit = QLineEdit(str(Path.cwd() / "downloads"))
        path_row.addWidget(self.dir_edit)
        choose_btn = QPushButton("选择目录")
        choose_btn.clicked.connect(self.choose_directory)
        path_row.addWidget(choose_btn)

        self.download_btn = QPushButton("下载所选")
        self.download_btn.clicked.connect(self.start_download_selected)
        self.download_btn.setEnabled(False)
        path_row.addWidget(self.download_btn)

        self.cancel_btn = QPushButton("取消当前下载")
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.cancel_btn.setEnabled(False)
        path_row.addWidget(self.cancel_btn)

        # CSV 导入按钮
        self.csv_btn = QPushButton("导入 CSV")
        self.csv_btn.clicked.connect(self.import_csv)
        path_row.addWidget(self.csv_btn)

        layout.addLayout(path_row)

        # 分隔器：上方搜索结果，下方队列/日志
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 结果表
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["标题", "作者", "出版社", "年份", "语言", "格式", "大小"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        splitter.addWidget(self.table)

        # 下载队列表
        self.queue_table = QTableWidget(0, 7)
        self.queue_table.setHorizontalHeaderLabels(["关键词", "语言", "格式", "年≥", "年≤", "状态", "信息"])
        self.queue_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        splitter.addWidget(self.queue_table)

        # 进度 + 日志区域
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

    def append_log(self, message, level="info"):
        self.log_view.append(f"[{level.upper()}] {message}")
        self.log_view.ensureCursorVisible()

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    # --- 搜索 ---
    def start_search(self):
        query = self.query_edit.text().strip()
        if not query:
            QMessageBox.warning(self, "提示", "请输入搜索关键词")
            return

        self.search_btn.setEnabled(False)
        self.append_log(f"开始搜索：{query}")

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
        self.table.setRowCount(len(results))
        for row, r in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(r.get("title") or ""))
            self.table.setItem(row, 1, QTableWidgetItem(r.get("author") or ""))
            self.table.setItem(row, 2, QTableWidgetItem(r.get("publisher") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(r.get("year") or ""))
            self.table.setItem(row, 4, QTableWidgetItem(r.get("language") or ""))
            self.table.setItem(row, 5, QTableWidgetItem(r.get("extension") or ""))
            self.table.setItem(row, 6, QTableWidgetItem(r.get("size") or ""))
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

        selected_rows = {index.row() for index in self.table.selectedIndexes()}
        if not selected_rows:
            QMessageBox.information(self, "提示", "请选择至少一行进行下载")
            return

        tasks = []
        for i in sorted(selected_rows):
            tasks.append({
                "type": "result",
                "result": self.results[i],
                "queue_row": self._add_queue_row_from_result(self.results[i]),
            })
        self.download_queue.extend(tasks)
        self.queue_tasks.extend(tasks)
        self.append_log(f"准备下载 {len(tasks)} 个条目")
        self.progress_bar.setValue(0)
        self._start_next_download()

    def _start_next_download(self):
        if self.current_download_thread:
            return  # 正在下载

        if not self.download_queue:
            self.append_log("下载队列完成")
            self.cancel_btn.setEnabled(False)
            return

        task = self.download_queue.pop(0)
        self.append_log(f"开始下载：{task.get('query') or task.get('result', {}).get('title')}")
        out_dir = self.dir_edit.text().strip() or str(Path.cwd() / "downloads")
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        # 标记队列状态为进行中
        row = task.get("queue_row")
        if row is not None and row < self.queue_table.rowCount():
            self.queue_table.setItem(row, 5, QTableWidgetItem("下载中"))
            self.queue_table.setItem(row, 6, QTableWidgetItem(""))

        self.current_download_thread = QThread()
        self.current_download_worker = TaskWorker(
            task,
            out_dir,
            limit=self.limit_spin.value(),
        )
        self.current_download_worker.moveToThread(self.current_download_thread)

        self.current_download_thread.started.connect(self.current_download_worker.run)
        self.current_download_worker.finished.connect(self.on_download_finished)
        self.current_download_worker.error.connect(self.on_download_error)
        self.current_download_worker.log.connect(self.on_worker_log)
        self.current_download_worker.progress.connect(self.on_download_progress)
        self.current_download_worker.finished.connect(self.current_download_thread.quit)
        self.current_download_worker.finished.connect(self.current_download_worker.deleteLater)
        self.current_download_worker.error.connect(self.current_download_thread.quit)
        self.current_download_worker.error.connect(self.current_download_worker.deleteLater)
        self.current_download_thread.finished.connect(self._clear_download_thread)
        self.current_download_thread.finished.connect(self.current_download_thread.deleteLater)
        self.current_download_thread.start()

        self.cancel_btn.setEnabled(True)

    def on_download_progress(self, downloaded, total):
        if total and total > 0:
            percent = int(downloaded / total * 100)
            self.progress_bar.setValue(max(0, min(percent, 100)))
            self.progress_bar.setFormat(
                f"{percent}% ({downloaded / 1024 / 1024:.2f}MB / {total / 1024 / 1024:.2f}MB)"
            )
        else:
            # 未知总长，只显示已下载
            self.progress_bar.setFormat(f"{downloaded / 1024 / 1024:.2f}MB")

    def on_download_finished(self, path):
        self.append_log(f"下载完成：{path}", level="success")
        self._update_queue_status("成功", path)
        QMessageBox.information(self, "下载完成", f"已保存到：\n{path}")
        self._finish_current_download()
        self._start_next_download()

    def on_download_error(self, message):
        self.append_log(f"下载失败：{message}", level="error")
        self._update_queue_status("失败", message)
        QMessageBox.critical(self, "下载失败", message)
        self._finish_current_download()
        self._start_next_download()

    def _finish_current_download(self):
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        if self.current_download_thread:
            self.current_download_thread.quit()

    def _clear_download_thread(self):
        self.current_download_thread = None
        self.current_download_worker = None

    def cancel_download(self):
        if self.current_download_worker:
            self.append_log("请求取消当前下载", level="warning")
            self.current_download_worker.cancel()
            self.cancel_btn.setEnabled(False)

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
        self.queue_table.setItem(row, 0, QTableWidgetItem(result.get("title") or result.get("md5") or ""))
        self.queue_table.setItem(row, 1, QTableWidgetItem(result.get("language") or ""))
        self.queue_table.setItem(row, 2, QTableWidgetItem(result.get("extension") or ""))
        self.queue_table.setItem(row, 3, QTableWidgetItem(""))
        self.queue_table.setItem(row, 4, QTableWidgetItem(""))
        self.queue_table.setItem(row, 5, QTableWidgetItem("排队中"))
        self.queue_table.setItem(row, 6, QTableWidgetItem(""))
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
        return row

    def _update_queue_status(self, status, info):
        worker = self.current_download_worker
        if not worker:
            return
        task = getattr(worker, "task", None)
        if not task:
            return
        row = task.get("queue_row")
        if row is None or row >= self.queue_table.rowCount():
            return
        self.queue_table.setItem(row, 5, QTableWidgetItem(status))
        self.queue_table.setItem(row, 6, QTableWidgetItem(info))

    # --- CSV 导入 ---
    def import_csv(self):
        dlg = CSVImportDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._enqueue_csv_tasks(dlg)

    def _enqueue_csv_tasks(self, dlg: CSVImportDialog):
        tasks = dlg.tasks
        if not tasks:
            QMessageBox.information(self, "提示", "没有可入队的任务")
            return
        for t in tasks:
            t["queue_row"] = self._add_queue_row_from_query(t)
        self.download_queue.extend(tasks)
        self.queue_tasks.extend(tasks)
        self.append_log(f"CSV 导入：入队 {len(tasks)} 条任务，跳过 {dlg.skipped} 条，年份错误 {dlg.year_errors} 条")
        self._start_next_download()

    # 拖拽 CSV 支持
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".csv"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".csv"):
                dlg = CSVImportDialog(self, preset_path=path)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self._enqueue_csv_tasks(dlg)
        event.acceptProposedAction()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
