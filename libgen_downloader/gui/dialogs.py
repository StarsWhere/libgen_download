import csv
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class CSVImportDialog(QDialog):
    def __init__(self, parent=None, preset_path=None):
        super().__init__(parent)
        self.setWindowTitle("导入 CSV/XLSX 并映射列")
        self.resize(900, 600)
        self.file_path = preset_path
        self.tasks = []
        self.skipped = 0
        self.year_errors = 0
        self.parse_errors = 0
        self.headers = []
        self.encoding_auto = True  # 首次自动检测编码

        self._build_ui()
        if preset_path:
            self.path_edit.setText(preset_path)
            self.load_file()

    def _build_ui(self):
        layout = QVBoxLayout()

        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        file_row.addWidget(QLabel("CSV/XLSX 文件"))
        file_row.addWidget(self.path_edit, 1)
        choose_btn = QPushButton("选择")
        choose_btn.clicked.connect(self.browse_file)
        file_row.addWidget(choose_btn)

        file_row.addWidget(QLabel("编码"))
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["utf-8", "utf-8-sig", "gbk", "big5", "iso-8859-1"])
        self.encoding_combo.currentIndexChanged.connect(self._on_encoding_manual_change)
        file_row.addWidget(self.encoding_combo)

        reload_btn = QPushButton("重新加载")
        reload_btn.clicked.connect(self.load_file)
        file_row.addWidget(reload_btn)
        layout.addLayout(file_row)

        map_grid = QGridLayout()
        self.combo_query = QComboBox()
        self.combo_lang = QComboBox()
        self.combo_ext = QComboBox()
        self.combo_year_min = QComboBox()
        self.combo_year_max = QComboBox()
        for i, (label, combo) in enumerate(
            [
                ("搜索关键词*", self.combo_query),
                ("语言列", self.combo_lang),
                ("格式列", self.combo_ext),
                ("年份≥", self.combo_year_min),
                ("年份≤", self.combo_year_max),
            ]
        ):
            map_grid.addWidget(QLabel(label), i, 0)
            map_grid.addWidget(combo, i, 1)
        layout.addLayout(map_grid)

        opts_row = QHBoxLayout()
        self.cb_skip_empty = QCheckBox("跳过空关键词行")
        self.cb_skip_empty.setChecked(True)
        opts_row.addWidget(self.cb_skip_empty)
        self.cb_ignore_year = QCheckBox("年份解析失败时跳过该行")
        self.cb_ignore_year.setChecked(True)
        opts_row.addWidget(self.cb_ignore_year)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        self.preview = QTableWidget(0, 0)
        self.preview.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self.preview, 1)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

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
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            "",
            "表格文件 (*.csv *.xlsx);;CSV Files (*.csv);;Excel Files (*.xlsx);;All Files (*)",
        )
        if path:
            self.path_edit.setText(path)
            self.load_file()

    def load_file(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请先选择 CSV/XLSX 文件")
            return
        self._set_encoding_enabled(not path.lower().endswith(".xlsx"))
        if path.lower().endswith(".csv") and self.encoding_auto:
            detected = self._auto_detect_csv_encoding(path)
            if detected:
                self._set_encoding_value(detected)
        try:
            headers, rows, parse_errors = self._read_tabular(path, preview_limit=100)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "读取失败", f"读取文件出错：{e}")
            return

        self.headers = headers
        self.parse_errors = parse_errors
        self._fill_combo_options()
        self._guess_mapping()
        self._fill_preview(rows)
        encoding_note = ""
        if path.lower().endswith(".csv"):
            encoding_note = f"，编码 {self.encoding_combo.currentText()}"
        self.status_label.setText(f"预览 {len(rows)} 行，表头 {len(self.headers)} 个，解析错误 {parse_errors} 行{encoding_note}")

    def _set_encoding_enabled(self, enabled):
        self.encoding_combo.setEnabled(enabled)
        self.encoding_combo.setToolTip("" if enabled else "XLSX 文件不需要选择编码")
        if not enabled:
            self.encoding_auto = True

    def _set_encoding_value(self, enc):
        block = self.encoding_combo.blockSignals(True)
        idx = self.encoding_combo.findText(enc)
        if idx < 0:
            self.encoding_combo.insertItem(0, enc)
            idx = 0
        self.encoding_combo.setCurrentIndex(idx)
        self.encoding_combo.blockSignals(block)
        self.encoding_auto = True

    def _on_encoding_manual_change(self, _index):
        if self.encoding_combo.isEnabled():
            self.encoding_auto = False

    def _read_tabular(self, path, preview_limit=None):
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            return self._read_csv(path, preview_limit)
        if suffix == ".xlsx":
            return self._read_xlsx(path, preview_limit)
        raise ValueError("仅支持 CSV 或 XLSX 文件")

    def _read_csv(self, path, preview_limit=None):
        enc = self.encoding_combo.currentText()
        rows = []
        headers = []
        with open(path, "r", encoding=enc, newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                rows.append(row)
                if preview_limit is not None and len(rows) >= preview_limit:
                    break
        return headers, rows, 0

    def _auto_detect_csv_encoding(self, path):
        candidates = ["utf-8-sig", "utf-8", "gbk", "big5", "iso-8859-1"]
        for enc in candidates:
            try:
                with open(path, "r", encoding=enc) as f:
                    f.read(4096)
                return enc
            except UnicodeDecodeError:
                continue
            except Exception:
                break
        return None

    def _read_xlsx(self, path, preview_limit=None):
        try:
            import openpyxl  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("需要安装 openpyxl 才能读取 XLSX 文件") from e

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active

        headers = []
        rows = []
        parse_errors = 0
        header_found = False

        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v).strip() for v in row]
            if not header_found:
                if any(cells):
                    headers = [c if c else f"列{idx + 1}" for idx, c in enumerate(cells)]
                    header_found = True
                continue

            if not header_found:
                continue

            if not any(cells):
                continue

            try:
                mapped = {h: cells[i] if i < len(cells) else "" for i, h in enumerate(headers)}
                rows.append(mapped)
                if preview_limit is not None and len(rows) >= preview_limit:
                    break
            except Exception:
                parse_errors += 1
                continue

        if not header_found:
            raise ValueError("未在 XLSX 中找到表头行（首个非空行）")

        wb.close()

        return headers, rows, parse_errors

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
            QMessageBox.warning(self, "提示", "请先选择 CSV/XLSX 文件")
            return
        if self.combo_query.currentIndex() <= 0:
            QMessageBox.warning(self, "提示", "必须选择“搜索关键词”列")
            return

        col_query = self.combo_query.currentText()
        col_lang = self.combo_lang.currentText() if self.combo_lang.currentIndex() > 0 else None
        col_ext = self.combo_ext.currentText() if self.combo_ext.currentIndex() > 0 else None
        col_ymin = self.combo_year_min.currentText() if self.combo_year_min.currentIndex() > 0 else None
        col_ymax = self.combo_year_max.currentText() if self.combo_year_max.currentIndex() > 0 else None

        tasks = []
        skipped = 0
        year_errors = 0
        try:
            _, rows, parse_errors = self._read_tabular(path, preview_limit=None)
            for row in rows:
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
                tasks.append(
                    {
                        "type": "query",
                        "query": query,
                        "language": lang or None,
                        "ext": ext or None,
                        "year_min": y_min,
                        "year_max": y_max,
                    }
                )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "读取失败", f"读取文件出错：{e}")
            return

        self.tasks = tasks
        self.skipped = skipped
        self.year_errors = year_errors
        self.parse_errors = parse_errors
        self.accept()

    @staticmethod
    def _safe_int(val):
        if val is None:
            return None
        try:
            return int(str(val).strip()) if str(val).strip() else None
        except ValueError:
            return None
