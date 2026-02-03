DARK_QSS = """
    QWidget { background-color: #2b2b2b; color: #efefef; }
    QMainWindow { background-color: #2b2b2b; color: #efefef; }
    QDialog { background-color: #2b2b2b; color: #efefef; }
    QGroupBox { font-weight: bold; border: 1px solid #555; border-radius: 6px; margin-top: 15px; padding-top: 15px; color: #aaa; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
    QLabel { color: #efefef; }
    QPushButton { padding: 6px 15px; border-radius: 4px; background-color: #444; border: 1px solid #666; color: #efefef; min-height: 20px; }
    QPushButton:hover { background-color: #555; border-color: #888; }
    QPushButton:pressed { background-color: #333; }
    QPushButton#search_btn { background-color: #0078d4; color: white; border: none; font-weight: bold; }
    QPushButton#search_btn:hover { background-color: #0086f0; }
    QPushButton#search_btn:disabled { background-color: #555; color: #888; }
    QLineEdit, QSpinBox, QComboBox { padding: 5px; border: 1px solid #555; border-radius: 4px; background-color: #3c3f41; color: #efefef; selection-background-color: #0078d4; }
    QComboBox:disabled, QLineEdit:disabled { color: #aaaaaa; }
    QComboBox QAbstractItemView { background-color: #2b2b2b; color: #efefef; selection-background-color: #004a8d; }
    QLineEdit:focus { border-color: #0078d4; }
    QCheckBox { spacing: 6px; }
    QCheckBox::indicator { width: 16px; height: 16px; }
    QCheckBox::indicator:unchecked { border: 1px solid #777; background: #3c3f41; }
    QCheckBox::indicator:checked { border: 1px solid #777; background: #0078d4; }
    QTableWidget { background-color: #2b2b2b; border: 1px solid #555; gridline-color: #444; color: #efefef; selection-background-color: #004a8d; selection-color: #ffffff; }
    QHeaderView::section { background-color: #3c3f41; padding: 6px; border: 1px solid #555; color: #aaa; }
    QProgressBar { border: 1px solid #555; border-radius: 4px; text-align: center; background-color: #3c3f41; color: white; }
    QProgressBar::chunk { background-color: #28a745; width: 10px; }
    QTextEdit { background-color: #1e1e1e; color: #d4d4d4; font-family: 'Consolas', 'Monaco', monospace; border: 1px solid #555; }
    QScrollBar:vertical { border: none; background: #2b2b2b; width: 10px; margin: 0px; }
    QScrollBar::handle:vertical { background: #555; min-height: 20px; border-radius: 5px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""
