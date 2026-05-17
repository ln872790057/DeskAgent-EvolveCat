"""定时任务面板 — 可折叠，显示定时任务列表"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QScrollArea, QHBoxLayout,
    QCheckBox,
)


TYPE_ICONS = {"once": "[1]", "daily": "[D]", "weekly": "[W]", "cron": "[*]"}
TYPE_LABELS = {"once": "一次性", "daily": "每天", "weekly": "每周", "cron": "定时"}


class ScheduledTaskPanel(QWidget):
    """Compact collapsible scheduled task panel."""

    def __init__(self, scheduled_task_mgr=None, parent=None):
        super().__init__(parent)
        self._mgr = scheduled_task_mgr
        self._expanded = False
        self._rows: dict[str, QWidget] = {}

        self.setStyleSheet("ScheduledTaskPanel { background: #141418; border-top: 1px solid #27272A; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        # Collapsed header bar
        self._header = QWidget()
        self._header.setFixedHeight(28)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = lambda e: self.toggle()
        hl = QHBoxLayout(self._header); hl.setContentsMargins(14, 0, 10, 0)
        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        hl.addWidget(self._summary); hl.addStretch()
        self._expand_icon = QLabel("▸")
        self._expand_icon.setStyleSheet("color: #666; font-size: 10px; background: transparent;")
        hl.addWidget(self._expand_icon)
        layout.addWidget(self._header)

        # Expanded task list
        self._scroll = QScrollArea()
        self._scroll.setMaximumHeight(200)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(2)
        self._list_layout.setContentsMargins(8, 4, 8, 4)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_widget)
        self._scroll.hide()
        layout.addWidget(self._scroll)

        self.hide()

    def set_manager(self, mgr):
        self._mgr = mgr
        if mgr:
            mgr.tasks_changed.connect(self.refresh)

    def refresh(self):
        """Rebuild the task list from the manager."""
        # Clear existing rows
        for row in self._rows.values():
            row.deleteLater()
        self._rows.clear()

        # Remove all items from layout except the last stretch
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._mgr:
            self._refresh_summary()
            return

        tasks = self._mgr.get_all_tasks()
        for task in tasks:
            row = self._build_row(task)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._rows[task.task_id] = row

        self._refresh_summary()

    def _build_row(self, task) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(4, 2, 4, 2)
        rl.setSpacing(6)

        # Type icon + schedule
        icon = TYPE_ICONS.get(task.task_type, "[?]")
        schedule_text = task.schedule[:20]
        info_label = QLabel(f"{icon} {schedule_text}")
        info_label.setStyleSheet("color: #aaa; font-size: 11px; background: transparent;")
        info_label.setFixedWidth(120)
        rl.addWidget(info_label)

        # Content preview
        content_preview = task.content[:18] + ("..." if len(task.content) > 18 else "")
        content_label = QLabel(content_preview)
        content_label.setStyleSheet("color: #ddd; font-size: 11px; background: transparent;")
        rl.addWidget(content_label, 1)

        # Enable/disable toggle
        cb = QCheckBox()
        cb.setChecked(task.enabled)
        cb.setToolTip("启用/禁用")
        cb.setStyleSheet("QCheckBox { background: transparent; }")
        cb.toggled.connect(lambda checked, tid=task.task_id: self._toggle_enabled(tid, checked))
        rl.addWidget(cb)

        # Delete button
        del_btn = QPushButton("X")
        del_btn.setFixedSize(18, 18)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setToolTip("删除任务")
        del_btn.setStyleSheet(
            "QPushButton { color: #666; border: none; background: transparent; font-size: 10px; }"
            "QPushButton:hover { color: #F87171; }")
        del_btn.clicked.connect(lambda checked=False, tid=task.task_id: self._delete_task(tid))
        rl.addWidget(del_btn)

        return row

    def _toggle_enabled(self, task_id, enabled):
        if self._mgr:
            self._mgr.set_enabled(task_id, enabled)

    def _delete_task(self, task_id):
        if self._mgr:
            self._mgr.delete_task(task_id)

    def _refresh_summary(self):
        if not self._mgr:
            self.hide()
            return
        tasks = self._mgr.get_all_tasks()
        if not tasks:
            self.hide()
            return
        enabled_count = sum(1 for t in tasks if t.enabled)
        disabled_count = len(tasks) - enabled_count
        parts = [f"{len(tasks)} 个任务"]
        if enabled_count: parts.append(f"{enabled_count} 启用")
        if disabled_count: parts.append(f"{disabled_count} 禁用")
        self._summary.setText(f"定时任务 ({', '.join(parts)})")
        self.show()

    def toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._scroll.show()
            self._expand_icon.setText("▾")
        else:
            self._scroll.hide()
            self._expand_icon.setText("▸")
        self.refresh()
