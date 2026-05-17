from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, Property, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics
from PySide6.QtWidgets import QLabel


class BubbleWidget(QLabel):
    """Semi-transparent speech bubble above the pet."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("speech_bubble")
        self._opacity = 1.0
        self._full_text = ""
        self.setMinimumWidth(200)
        self.setMaximumWidth(220)
        self.setWordWrap(True)
        self.setFont(QFont("Microsoft YaHei", 10))
        self.setStyleSheet("color: white; padding: 10px 14px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._start_fade)
        self._fade_anim = None

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, value):
        self._opacity = value
        self.setWindowOpacity(value)
        self.update()

    opacity = Property(float, get_opacity, set_opacity)

    def show_bubble(self, text: str):
        self._full_text = text
        # Truncate for bubble display
        display_text = text[:60] + ("..." if len(text) > 60 else "")
        self.setText(display_text)
        self._opacity = 1.0
        self.setWindowOpacity(1.0)

        # Calculate size
        fm = QFontMetrics(self.font())
        # Estimate text rect
        max_width = 180
        text_rect = fm.boundingRect(0, 0, max_width, 500,
                                     Qt.TextFlag.TextWordWrap, display_text)
        w = min(text_rect.width() + 30, 210)
        h = text_rect.height() + 30

        # Position above the pet window
        parent_w = self.parent().width()
        x = (parent_w - w) // 2
        y = -h - 15  # above window, 15px gap

        self.setGeometry(x, y, w, h)
        self.show()
        self.raise_()

        self._fade_timer.start(5000)

    def _start_fade(self):
        self._fade_anim = QPropertyAnimation(self, b"opacity")
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setDuration(500)
        self._fade_anim.finished.connect(self.hide)
        self._fade_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        alpha = int(self._opacity * 180)
        painter.setBrush(QBrush(QColor(40, 40, 40, alpha)))
        painter.drawRoundedRect(self.rect(), 12, 12)

        # Small triangle at bottom center
        cx = self.width() // 2
        tri_h = 8
        tri_w = 6
        bl = self.rect().bottomLeft()
        painter.drawPolygon([
            QPoint(bl.x() + cx - tri_w, bl.y()),
            QPoint(bl.x() + cx + tri_w, bl.y()),
            QPoint(bl.x() + cx, bl.y() + tri_h),
        ])

        painter.end()
        super().paintEvent(event)

    def mousePressEvent(self, event):
        self.clicked.emit()
        self.hide()
