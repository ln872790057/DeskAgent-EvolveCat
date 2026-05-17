"""后台任务面板 — 可折叠任务抽屉，在聊天区上方"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QScrollArea, QHBoxLayout,
)


STATUS_META = {
    "pending": ("排队中", "#A1A1AA", "#27272C"),
    "running": ("执行中", "#60A5FA", "rgba(59,130,246,0.14)"),
    "completed": ("已完成", "#22C55E", "rgba(34,197,94,0.12)"),
    "failed": ("失败", "#F87171", "rgba(248,113,113,0.12)"),
    "cancelled": ("已取消", "#A1A1AA", "#27272C"),
}


class TaskPanel(QWidget):
    """Compact collapsible task drawer above the chat transcript."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("task_panel")
        self.setStyleSheet("""
            QWidget#task_panel {
                background: #101014;
                border-top: 1px solid #25252B;
                border-bottom: 1px solid #2E2E36;
            }
        """)
        self._cards: dict[str, QWidget] = {}
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 8, 22, 8); layout.setSpacing(8)

        # Collapsed header bar
        self._header = QWidget()
        self._header.setObjectName("task_panel_header")
        self._header.setFixedHeight(34)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setStyleSheet("""
            QWidget#task_panel_header {
                background: transparent;
                border: none;
            }
        """)
        self._header.mousePressEvent = lambda e: self.toggle()
        hl = QHBoxLayout(self._header); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(10)

        title = QLabel("后台任务")
        title.setStyleSheet("color: #E4E4E7; font-size: 12px; font-weight: 700; background: transparent;")
        hl.addWidget(title)

        self._summary = QLabel("")
        self._summary.setStyleSheet("""
            color: #A1A1AA;
            font-size: 11px;
            background: #1A1A1F;
            border: 1px solid #2A2A30;
            border-radius: 10px;
            padding: 2px 9px;
        """)
        hl.addWidget(self._summary)
        hl.addStretch()

        self._hint = QLabel("点击展开")
        self._hint.setStyleSheet("color: #71717A; font-size: 11px; background: transparent;")
        hl.addWidget(self._hint)

        self._expand_icon = QLabel("▸")
        self._expand_icon.setFixedWidth(16)
        self._expand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._expand_icon.setStyleSheet("color: #A1A1AA; font-size: 13px; font-weight: 700; background: transparent;")
        hl.addWidget(self._expand_icon)
        layout.addWidget(self._header)

        # Expanded task list
        self._scroll = QScrollArea()
        self._scroll.setMaximumHeight(150)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
                margin: 2px 0;
            }
            QScrollBar::handle:vertical {
                background: #34343A;
                border-radius: 2px;
                min-height: 18px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(6)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_widget)
        self._scroll.hide()
        layout.addWidget(self._scroll)

        self._bottom_rule = QWidget()
        self._bottom_rule.setFixedHeight(2)
        self._bottom_rule.setStyleSheet("background: #3B82F6; border-radius: 1px;")
        self._bottom_rule.hide()
        layout.addWidget(self._bottom_rule)

        self.hide()

    def _apply_panel_style(self):
        if self._expanded:
            bg = "#18181E"
            bottom = "#3B82F6"
            self._bottom_rule.show()
        else:
            bg = "#101014"
            bottom = "#2E2E36"
            self._bottom_rule.hide()
        self.setStyleSheet(f"""
            QWidget#task_panel {{
                background: {bg};
                border-top: 1px solid #33333A;
                border-bottom: 2px solid {bottom};
            }}
        """)

    def _refresh_summary(self):
        self._apply_panel_style()
        running = sum(1 for c in self._cards.values() if getattr(c, '_status', '') == 'running')
        pending = sum(1 for c in self._cards.values() if getattr(c, '_status', '') == 'pending')
        done = sum(1 for c in self._cards.values() if getattr(c, '_status', '') == 'completed')
        failed = sum(1 for c in self._cards.values() if getattr(c, '_status', '') == 'failed')
        parts = []
        if running: parts.append(f"{running} 执行中")
        if pending: parts.append(f"{pending} 排队中")
        if done: parts.append(f"{done} 已完成")
        if failed: parts.append(f"{failed} 失败")
        if parts:
            self._summary.setText(" / ".join(parts))
            self.show()
            self.setFixedHeight(self._panel_height())
        else:
            self.hide()

    def _panel_height(self) -> int:
        if not self._expanded:
            return 50
        return 64 + min(150, max(42, len(self._cards) * 42))

    def add_task(self, task_id: str, name: str):
        if task_id in self._cards:
            return
        row = QWidget()
        row._name_base = name[:42]
        row._detail = ""
        row.setObjectName(f"task_row_{task_id}")
        row.setMinimumHeight(36)
        row.setStyleSheet(f"""
            QWidget#task_row_{task_id} {{
                background: #101014;
                border: 1px solid #34343C;
                border-radius: 8px;
            }}
        """)
        rl = QHBoxLayout(row); rl.setContentsMargins(12, 6, 10, 6); rl.setSpacing(10)

        dot = QLabel()
        dot.setObjectName(f"dot_{task_id}")
        dot.setFixedSize(7, 7)
        dot.setStyleSheet("background: #A1A1AA; border-radius: 3px;")
        rl.addWidget(dot)

        name_lbl = QLabel(row._name_base)
        name_lbl.setObjectName(f"name_{task_id}")
        name_lbl.setStyleSheet("color: #D4D4D8; font-size: 12px; background: transparent;")
        rl.addWidget(name_lbl, 1)

        status_lbl = QLabel("")
        status_lbl.setObjectName(f"status_{task_id}")
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_lbl.setMinimumWidth(54)
        rl.addWidget(status_lbl)
        row._status = 'pending'
        self._apply_row_status(row, task_id, 'pending')

        count = self._list_layout.count()
        if count > 0:
            last = self._list_layout.itemAt(count - 1)
            if last and last.spacerItem():
                self._list_layout.removeItem(last)
        self._list_layout.addWidget(row)
        self._list_layout.addStretch()
        self._cards[task_id] = row
        self._refresh_summary()

    def update_detail(self, task_id: str, detail: str):
        if task_id not in self._cards:
            return
        row = self._cards[task_id]
        row._detail = (detail or "").strip()
        label = row.findChild(QLabel, f"name_{task_id}")
        if not label:
            return
        base = getattr(row, "_name_base", "")
        if row._detail:
            label.setText(f"{base} · {row._detail}"[:76])
            label.setStyleSheet("color: #E4E4E7; font-size: 12px; background: transparent;")
        else:
            label.setText(base)
            label.setStyleSheet("color: #D4D4D8; font-size: 12px; background: transparent;")

    def update_status(self, task_id: str, status: str):
        if task_id not in self._cards:
            return
        row = self._cards[task_id]
        row._status = status
        self._apply_row_status(row, task_id, status)
        self._refresh_summary()

    def _apply_row_status(self, row: QWidget, task_id: str, status: str):
        text, color, bg = STATUS_META.get(status, STATUS_META["pending"])
        dot = row.findChild(QLabel, f"dot_{task_id}")
        label = row.findChild(QLabel, f"status_{task_id}")
        if dot:
            dot.setStyleSheet(f"background: {color}; border-radius: 3px;")
        if label:
            label.setText(text)
            label.setStyleSheet(f"""
                color: {color};
                background: {bg};
                border: 1px solid rgba(255,255,255,0.05);
                border-radius: 9px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 650;
            """)

    def remove_task(self, task_id: str):
        if task_id in self._cards:
            self._cards.pop(task_id).deleteLater()
        if not self._cards:
            self.hide()
        else:
            self._refresh_summary()

    def toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._scroll.show()
            self._scroll.setMaximumHeight(min(150, max(42, len(self._cards) * 42)))
            self._expand_icon.setText("▾")
            self._hint.setText("点击收起")
        else:
            self._scroll.hide()
            self._expand_icon.setText("▸")
            self._hint.setText("点击展开")
        self._refresh_summary()
