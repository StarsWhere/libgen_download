from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout


class ToastNotification(QFrame):
    """轻量 Toast 提示，自动消失，不阻塞主流程。"""

    def __init__(self, parent, title, text, level="info", duration_ms=3000, width=360):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            """
            QFrame {
                background: rgba(40, 40, 40, 0.92);
                color: #f0f0f0;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.08);
            }
            QLabel#title { font-weight: bold; color: %s; }
            QLabel#body { color: #e0e0e0; }
            """
            % ("#28a745" if level == "success" else ("#ff6b6b" if level == "error" else "#66b1ff"))
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("title")
        body_lbl = QLabel(text)
        body_lbl.setObjectName("body")
        body_lbl.setWordWrap(True)

        lay.addWidget(title_lbl)
        lay.addWidget(body_lbl)

        self.resize(width, self.sizeHint().height())

        QTimer.singleShot(duration_ms, self.close)

    def show_relative(self, parent_widget, margin=16):
        if parent_widget is None:
            self.show()
            return
        bottom_right = parent_widget.mapToGlobal(QPoint(parent_widget.width(), parent_widget.height()))
        x = bottom_right.x() - self.width() - margin
        y = bottom_right.y() - self.height() - margin
        self.move(QPoint(x, y))
        self.show()
