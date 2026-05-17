"""工具状态卡片 — 紧凑可展开，与聊天气泡视觉区分"""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)

TOOL_ICONS = {
    "web_search": "🔍", "read_file": "📄", "write_file": "✏️",
    "clipboard_read": "📋", "clipboard_write": "📋",
    "screenshot": "📸", "notify": "🔔", "shell_exec": "⚡",
}
TOOL_NAMES = {
    "web_search": "搜索", "read_file": "读文件", "write_file": "写文件",
    "clipboard_read": "读剪贴板", "clipboard_write": "写剪贴板",
    "screenshot": "截屏分析", "notify": "通知", "shell_exec": "命令行",
}

# Status colors
COL_RUNNING = "#60A5FA"   # blue
COL_DONE = "#4ADE80"      # green
COL_FAILED = "#F87171"    # red


class ToolStatusBubble(QWidget):
    """工具状态卡片 — 左侧彩色边框 + 可展开详情 + 紧凑布局"""

    def __init__(self, tool_name: str, parent=None):
        super().__init__(parent)
        self._tool_name = tool_name
        self._result_text = ""
        self._status = "running"
        self._expanded = False

        self.setFixedWidth(340)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(2)

        # Header row: icon + tool label + status text + expand button
        header = QHBoxLayout()
        header.setSpacing(6)
        icon = TOOL_ICONS.get(tool_name, "🔧")
        name = TOOL_NAMES.get(tool_name, tool_name)

        # Tool type badge
        self._badge = QLabel(f" 工具 ")
        self._badge.setStyleSheet(
            "color: #888; font-size: 9px; font-weight: 700; "
            "background: rgba(255,255,255,0.06); border-radius: 4px; "
            "padding: 1px 6px;"
        )
        header.addWidget(self._badge)

        self._status_label = QLabel(f"{icon} {name} ···")
        self._status_label.setStyleSheet(
            "color: #aaa; font-size: 12px; background: transparent;")
        header.addWidget(self._status_label)
        header.addStretch()

        self._expand_btn = QPushButton("▸")
        self._expand_btn.setFixedSize(20, 20)
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._expand_btn.setStyleSheet(
            "QPushButton { color: #666; border: none; background: transparent; font-size: 10px; }"
            "QPushButton:hover { color: #aaa; }")
        self._expand_btn.clicked.connect(self._toggle)
        self._expand_btn.hide()
        header.addWidget(self._expand_btn)
        self._layout.addLayout(header)

        # Detail area (hidden by default)
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(
            "color: #999; font-size: 11px; background: rgba(255,255,255,0.02);"
            "border-radius: 6px; padding: 6px 8px; margin-top: 2px;")
        self._detail.hide()
        self._layout.addWidget(self._detail)

        self._set_border_color(COL_RUNNING)

    def _set_border_color(self, color: str):
        self.setStyleSheet(
            f"ToolStatusBubble {{"
            f"  background: rgba(255,255,255,0.02);"
            f"  border-radius: 6px;"
            f"  border-left: 3px solid {color};"
            f"  margin: 2px 0;"
            f"}}"
        )

    def set_running(self, text: str = ""):
        self._status = "running"
        icon = TOOL_ICONS.get(self._tool_name, "🔧")
        name = TOOL_NAMES.get(self._tool_name, self._tool_name)
        display = text or f"{name} ···"
        self._status_label.setText(f"{icon} {display}")
        self._status_label.setStyleSheet(
            f"color: {COL_RUNNING}; font-size: 12px; background: transparent;")
        self._set_border_color(COL_RUNNING)

    def set_done(self, result_summary: str):
        self._status = "done"
        icon = TOOL_ICONS.get(self._tool_name, "🔧")
        name = TOOL_NAMES.get(self._tool_name, self._tool_name)
        self._status_label.setText(f"{icon} {name} 完成")
        self._status_label.setStyleSheet(
            f"color: {COL_DONE}; font-size: 12px; background: transparent;")
        self._set_border_color(COL_DONE)
        if result_summary and result_summary.strip():
            self._result_text = result_summary[:300]
            self._detail.setText(result_summary[:300])
            self._expand_btn.show()

    def set_failed(self, error: str):
        self._status = "failed"
        name = TOOL_NAMES.get(self._tool_name, self._tool_name)
        self._status_label.setText(f"❌ {name} 失败")
        self._status_label.setStyleSheet(
            f"color: {COL_FAILED}; font-size: 12px; background: transparent;")
        self._set_border_color(COL_FAILED)
        if error:
            self._result_text = error[:300]
            self._detail.setText(error[:300])
            self._expand_btn.show()

    def _toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._detail.show()
            self._expand_btn.setText("▾")
        else:
            self._detail.hide()
            self._expand_btn.setText("▸")
