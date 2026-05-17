from PySide6.QtCore import (
    Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QRectF, QThread, QSize,
)
from PySide6.QtGui import QFont, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QSizePolicy,
    QListWidget, QListWidgetItem, QAbstractItemView,
)

from ui.theme import get_token, get_mode
from ui.task_panel import TaskPanel
from ui.scheduled_task_panel import ScheduledTaskPanel
from utils.logger import get_logger

logger = get_logger("ui.chat_window")


# ═══ LLMWorker: QThread 解耦网络请求 ═══
class LLMWorker(QThread):
    chunk_ready = Signal(str)       # 流式文本 chunk
    stream_done = Signal(str)       # 完成，带 emotion
    stream_error = Signal(str)      # 错误消息

    def __init__(self, agent, message: str, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.message = message

    def run(self):
        try:
            # Use sync chat() to get reply+emotion, then stream char by char
            response = self.agent.chat(self.message)
            reply = response.reply
            emotion = response.emotion
            for ch in reply:
                self.chunk_ready.emit(ch)
                self.msleep(12)  # typing speed
            self.stream_done.emit(emotion)
        except Exception as e:
            self.stream_error.emit(str(e))


class SendButton(QPushButton):
    """带 hover/press 动效的发送按钮"""

    def __init__(self, parent=None):
        super().__init__("发送", parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scale = 1.0
        self._anim = None
        self._refresh_style(False, False)
        self.setEnabled(False)

    def _refresh_style(self, hover: bool, press: bool):
        accent = get_token("accent")
        if not self.isEnabled():
            bg = get_token("bg_tertiary"); fg = get_token("text_dim")
        elif press:
            bg = get_token("accent_press"); fg = "#FFFFFF"
        elif hover:
            bg = get_token("accent_hover"); fg = "#FFFFFF"
        else:
            bg = accent; fg = "#FFFFFF"
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {fg}; border: none;
                border-radius: 18px; padding: 8px 20px;
                font-size: 13px; font-weight: 700; min-width: 56px; min-height: 34px;
            }}
        """)

    def enterEvent(self, ev):
        self._refresh_style(True, False)
        self._anim_press(1.04); super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._refresh_style(False, False)
        self._anim_press(1.0); super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        self._refresh_style(True, True)
        self._anim_press(0.95); super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._refresh_style(True, False)
        self._anim_press(1.0); super().mouseReleaseEvent(ev)

    def _anim_press(self, to_scale):
        if self._anim: self._anim.stop()
        g = self.geometry()
        c = g.center()
        nw, nh = int(g.width() * to_scale / self._scale), int(g.height() * to_scale / self._scale)
        self._scale = to_scale
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(100)
        self._anim.setStartValue(g)
        self._anim.setEndValue(QRectF(c.x() - nw/2, c.y() - nh/2, nw, nh))
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._anim.start()


class MessageBubble(QLabel):
    """自适应宽度聊天气泡 — NoFocus 防止自动滚动偏移"""

    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(parent)
        self._full = text
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(0)
        self.setMaximumWidth(620)
        f = QFont("Microsoft YaHei UI", 10)
        f.setStyleHint(QFont.StyleHint.SansSerif)
        self.setFont(f)

        mode = get_mode()
        if is_user:
            if mode == "light":
                bg = get_token("accent"); fg = "#FFFFFF"
            else:
                bg = get_token("bg_secondary"); fg = get_token("text_primary")
            self.setStyleSheet(f"""
                QLabel {{
                    background: {bg}; color: {fg};
                    border-radius: 14px 4px 14px 14px;
                    padding: 10px 15px; font-size: 13px;
                }}
            """)
        else:
            if mode == "light":
                bg = "#F4F4F5"; fg = "#18181B"; bl = "rgba(0,0,0,0.08)"
            else:
                bg = "transparent"; fg = get_token("text_primary"); bl = "rgba(255,255,255,0.08)"
            self.setStyleSheet(f"""
                QLabel {{
                    background: {bg}; color: {fg};
                    border-radius: 4px 14px 14px 14px;
                    padding: 10px 15px; font-size: 13px;
                    border-left: 2px solid {bl};
                }}
            """)

        self.setText(text)
        self.adjustSize()

    def append_text(self, text: str):
        self._full += text
        self.setText(self._full)
        self.adjustSize()


class ChatWindow(QWidget):
    emotion_changed = Signal(str)
    bubble_requested = Signal(str)

    def __init__(self, agent=None, task_manager=None, parent=None):
        super().__init__()
        self.agent = agent
        self.task_mgr = task_manager
        self._cb = None
        self._last_cat = None
        self._task_bubbles = {}
        self._task_types = {}
        self._tool_cards = {}
        self._hitl_cards = {}
        self._rendered_task_results = set()
        self._connected_task_mgr = None
        self._dr = False; self._dp = None
        self._init_ui()

    def set_agent(self, a): self.agent = a
    def set_task_manager(self, tm):
        self.task_mgr = tm
        self._ensure_task_connections()

    def _init_ui(self):
        self.setObjectName("chat_window")
        self._window_w = 760
        self._window_h = 680
        self.setFixedSize(self._window_w, self._window_h)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        QShortcut(Qt.Key.Key_Escape, self, self.hide)

        bg1 = get_token("bg_primary")
        border = get_token("border")
        text_c = get_token("text_primary")

        # ── Container ──
        container = QWidget(self)
        container.setObjectName("container")
        container.setGeometry(0, 0, self._window_w, self._window_h)
        container.setStyleSheet(f"""
            QWidget#container {{
                background: {bg1};
                border-radius: 18px;
                border: 1px solid {border};
            }}
        """)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        # ── Header: compact status bar matching the design mockup ──
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            background: #151518;
            border-top-left-radius: 18px; border-top-right-radius: 18px;
            border-bottom: 1px solid {border};
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 18, 0); hl.setSpacing(0)

        self._status_dot = QLabel()
        self._status_dot.setFixedSize(8, 8)
        self._status_dot.setStyleSheet(f"background: {get_token('success')}; border-radius: 4px;")
        hl.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addSpacing(12)

        brand = QWidget()
        brand.setFixedHeight(44)
        brand.setStyleSheet("background: transparent; border: none;")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(0, 3, 0, 3)
        brand_layout.setSpacing(2)
        title = QLabel("deskagent")
        title.setFixedHeight(20)
        title.setStyleSheet(f"color: {text_c}; font-size: 16px; font-weight: 700; background: transparent; border: none;")
        brand_layout.addWidget(title)

        self._status_text = QLabel("空闲中")
        self._status_text.setFixedHeight(15)
        self._status_text.setStyleSheet(f"color: {get_token('text_secondary')}; font-size: 12px; background: transparent; border: none;")
        brand_layout.addWidget(self._status_text)

        hl.addWidget(brand); hl.addStretch()

        icon_style = (
            "QPushButton { color: #D4D4D8; border: 1px solid #303036; "
            "border-radius: 8px; background: #1C1C21; font-size: 12px; "
            "font-weight: 650; padding: 0; outline: none; min-height: 30px; max-height: 30px; }"
            "QPushButton:hover { background: #26262C; border-color: #3F3F46; color: #FFFFFF; }"
            "QPushButton:pressed { background: #18181B; }"
            "QPushButton:focus { outline: none; border: 1px solid #303036; }"
        )
        self._task_btn = QPushButton("任务")
        self._task_btn.setToolTip("展开或收起后台任务")
        self._task_btn.setFixedSize(44, 30)
        self._task_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._task_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._task_btn.setStyleSheet(icon_style)
        self._task_btn.clicked.connect(self._toggle_task_panel)
        hl.addWidget(self._task_btn)
        hl.addSpacing(8)

        self._sched_btn = QPushButton("定时")
        self._sched_btn.setToolTip("查看定时任务")
        self._sched_btn.setFixedSize(44, 30)
        self._sched_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sched_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sched_btn.setStyleSheet(icon_style)
        self._sched_btn.clicked.connect(self._toggle_scheduled_panel)
        hl.addWidget(self._sched_btn)
        hl.addSpacing(8)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("close_btn")
        close_btn.setFixedSize(52, 30)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton#close_btn { color: #F4F4F5; border: 1px solid #34343A; "
            "border-radius: 8px; background: #27272C; font-size: 12px; "
            "font-weight: 750; padding: 0; outline: none; min-width: 52px; max-width: 52px; "
            "min-height: 30px; max-height: 30px; }"
            "QPushButton#close_btn:hover { background: #3F3F46; border-color: #52525B; color: #FFFFFF; }"
            "QPushButton#close_btn:pressed { background: #18181B; }"
            "QPushButton#close_btn:focus { outline: none; border: 1px solid #34343A; }")
        close_btn.clicked.connect(self.hide)
        hl.addWidget(close_btn)
        layout.addWidget(header)

        # Breathing dot animation
        self._breath_anim = QPropertyAnimation(self._status_dot, b"windowOpacity")
        self._breath_anim.setDuration(800)
        self._breath_anim.setStartValue(1.0)
        self._breath_anim.setEndValue(0.5)
        self._breath_anim.setLoopCount(-1)
        self._breath_anim.setEasingCurve(QEasingCurve.Type.InOutSine)

        self._task_meta = QWidget()
        self._task_meta.setFixedHeight(42)
        self._task_meta.setStyleSheet("background: #121214; border-bottom: 1px solid #242428;")
        ml = QHBoxLayout(self._task_meta)
        ml.setContentsMargins(22, 0, 22, 0); ml.setSpacing(8)
        self._task_meta_title = QLabel("当前任务：对话")
        self._task_meta_title.setStyleSheet(f"color: {text_c}; font-size: 14px; font-weight: 650; background: transparent;")
        self._task_meta_side = QLabel("")
        self._task_meta_side.setStyleSheet(f"color: {get_token('text_secondary')}; font-size: 12px; background: transparent;")
        ml.addWidget(self._task_meta_title)
        ml.addStretch()
        ml.addWidget(self._task_meta_side)
        layout.addWidget(self._task_meta)

        # ── Task stream area ──
        self.message_list = QListWidget()
        self.message_list.setObjectName("message_list")
        self.message_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.message_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.message_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.message_list.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; padding: 18px 22px; }}
            QListWidget::item {{ background: transparent; border: none; outline: 0; }}
            QListWidget::item:hover {{ background: transparent; border: none; outline: 0; }}
            QListWidget::item:selected {{ background: transparent; border: none; outline: 0; }}
            QListWidget::item:focus {{ background: transparent; border: none; outline: 0; }}
            QScrollBar:vertical {{ background: transparent; width: 5px; margin: 4px 2px; }}
            QScrollBar::handle:vertical {{ background: {get_token('bg_tertiary')}; border-radius: 3px; min-height: 20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self.message_list.setSpacing(4)


        # Task panel: collapsible bar above chat area
        self._task_panel = TaskPanel(self)
        self._task_panel.setFixedHeight(0)
        self._task_panel.hide()
        layout.addWidget(self._task_panel)

        # Scheduled task panel: below task panel
        self._scheduled_task_panel = ScheduledTaskPanel(None, self)
        self._scheduled_task_panel.setFixedHeight(0)
        self._scheduled_task_panel.hide()
        layout.addWidget(self._scheduled_task_panel)

        layout.addWidget(self.message_list)

        # ── Composer (72px, design-matching) ──
        input_w = QWidget()
        input_w.setObjectName("input_area")
        input_w.setFixedHeight(72)
        input_w.setStyleSheet(f"""
            QWidget#input_area {{
                background: #151518;
                border-top: 1px solid {border};
                border-bottom-left-radius: 16px;
                border-bottom-right-radius: 16px;
            }}
        """)
        il = QHBoxLayout(input_w)
        il.setContentsMargins(16, 10, 16, 14); il.setSpacing(12)

        self._input = QLineEdit()
        self._input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._input.setFixedHeight(44)
        self._input.setPlaceholderText("告诉 deskagent 下一步要做什么...")
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #232328; color: {text_c};
                border: 1px solid transparent; border-radius: 12px;
                padding: 0 16px; font-size: 14px;
                min-height: 44px; max-height: 44px;
            }}
            QLineEdit:focus {{ border-color: {get_token('border')}; }}
            QLineEdit::placeholder {{ color: {get_token('text_dim')}; }}
        """)
        self._input.returnPressed.connect(self._send)
        self._input.textChanged.connect(self._on_text_change)
        il.addWidget(self._input)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedSize(80, 44)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setEnabled(False)
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {get_token('accent')}; color: white;
                border: none; border-radius: 12px; font-size: 14px; font-weight: 700;
                padding: 0; min-height: 44px; max-height: 44px;
                min-width: 80px; max-width: 80px;
            }}
            QPushButton:hover {{ background: {get_token('accent_hover')}; }}
            QPushButton:disabled {{ background: {get_token('bg_tertiary')}; color: {get_token('text_dim')}; }}
        """)
        self._send_btn.clicked.connect(self._send)
        il.addWidget(self._send_btn)
        layout.addWidget(input_w)

    def _on_text_change(self):
        has = bool(self._input.text().strip())
        if self._send_btn.isEnabled() != has:
            self._send_btn.setEnabled(has)

    def _send(self):
        t = self._input.text().strip()
        if not t or not self.agent: return
        self._input.clear()

        # API Key 为空检查
        from agent.llm.router import get_llm_config
        if not get_llm_config().get("api_key"):
            self._add_msg(t, True)
            self._add_msg("请先在设置中配置 API Key", False)
            return

        # 屏幕相关关键词 → 立刻触发一次截屏分析
        screen_kw = ["屏幕","截屏","桌面","在看","干嘛","做什么","看到","看见","眼前"]
        if any(kw in t for kw in screen_kw):
            self._trigger_screen_capture()

        self._send_btn.setEnabled(False)
        self._set_status("working", "处理中...")
        if hasattr(self, "_task_meta_title"):
            self._task_meta_title.setText(f"当前任务：{t[:28]}{'...' if len(t) > 28 else ''}")

        # Step 1: 立即上屏用户气泡 + 思考占位
        self._add_msg(t, True)
        cat = self._add_msg("...", False)
        self._last_cat = cat
        self._cb = cat

        # Step 2: route via TaskManager or fallback LLMWorker
        if self.task_mgr:
            from agent.task_worker import classify_message
            from agent.task_manager import TaskType

            self._ensure_task_connections()
            mtype = classify_message(t)
            tt = TaskType.CHAT if mtype == "CHAT" else TaskType.TASK
            tid = self.task_mgr.create_task(t, tt, t)
            self._task_id = tid
            self._task_bubbles[tid] = cat
            self._task_types[tid] = tt.value
            logger.info(f"ChatWindow task created: tid={tid} type={tt.value} text={t[:40]}")
            # Task panel
            if tt.value == "task":
                self._task_panel.add_task(tid, t[:30])
                task = self.task_mgr.get_task(tid)
                if task:
                    self._task_panel.update_status(tid, task.status.value)
                # Background tasks should not lock the chat box while they run.
                self._send_btn.setEnabled(True)
        else:
            self._worker = LLMWorker(self.agent, t, self)
            self._worker.chunk_ready.connect(self._on_chunk)
            self._worker.stream_done.connect(self._on_done)
            self._worker.stream_error.connect(self._on_error)
            self._worker.finished.connect(self._worker.deleteLater)
            self._worker.start()

    def _ensure_task_connections(self):
        if not self.task_mgr or self._connected_task_mgr is self.task_mgr:
            return
        if self._connected_task_mgr:
            for sig, slot in [
                (self._connected_task_mgr.stream_chunk, self._on_tm_chunk),
                (self._connected_task_mgr.stream_done, self._on_tm_done),
                (self._connected_task_mgr.tool_status_update, self._on_tool_status),
                (self._connected_task_mgr.tool_result_update, self._on_tool_result),
                (self._connected_task_mgr.task_status_changed, self._on_task_status),
                (self._connected_task_mgr.task_completed, self._on_task_completed),
                (self._connected_task_mgr.task_failed, self._on_task_failed),
                (self._connected_task_mgr.hitl_confirmation_needed, self._on_hitl_needed),
            ]:
                try: sig.disconnect(slot)
                except Exception: pass
        self.task_mgr.stream_chunk.connect(self._on_tm_chunk)
        self.task_mgr.stream_done.connect(self._on_tm_done)
        self.task_mgr.tool_status_update.connect(self._on_tool_status)
        self.task_mgr.tool_result_update.connect(self._on_tool_result)
        self.task_mgr.task_status_changed.connect(self._on_task_status)
        self.task_mgr.task_completed.connect(self._on_task_completed)
        self.task_mgr.task_failed.connect(self._on_task_failed)
        self.task_mgr.hitl_confirmation_needed.connect(self._on_hitl_needed)
        self._connected_task_mgr = self.task_mgr

    def _on_tm_chunk(self, tid, chunk):
        bubble = self._task_bubbles.get(tid)
        if bubble:
            if bubble._full == "...":
                bubble._full = ""
                bubble.setText("")
                bubble.setMinimumHeight(0)
                bubble.setMaximumHeight(16777215)
                bubble.setFixedHeight(bubble.sizeHint().height())
            bubble.append_text(chunk)
            bubble.setMaximumHeight(16777215)
            bubble.setMinimumHeight(0)
            self._update_bubble_size(bubble)

    def _on_tm_done(self, tid, full):
        self.collapse_all_hitl()
        self._render_task_result(tid, full, source="stream_done")
        bubble = self._task_bubbles.get(tid)
        if tid == getattr(self, '_task_id', ''):
            self._cb = None
        self._send_btn.setEnabled(True)
        self._set_status("idle", "空闲中")
        logger.info(f"ChatWindow task reply shown: tid={tid} reply_len={len(full or '')}")
        self.emotion_changed.emit("talk")
        if full:
            self.bubble_requested.emit(full[:30])
        self._scroll_bottom()

        # Check for pending self-evolution special messages
        if self.agent and hasattr(self.agent, 'get_pending_special_msg'):
            special = self.agent.get_pending_special_msg()
            if special:
                bubble = self._add_msg(special, False)
                if bubble and hasattr(bubble, 'setStyleSheet'):
                    bubble.setStyleSheet(bubble.styleSheet().replace(
                        "border-left: 2px solid",
                        "border-left: 2px solid #fbbf24; border: 1px solid rgba(251,191,36,0.3);"
                    ))
                self._scroll_bottom()

        QTimer.singleShot(5000, lambda: self.emotion_changed.emit("idle"))

    def _on_tool_status(self, tid, tool_name, text):
        key = (tid, tool_name)
        icon_map = {
            "web_search": "🔍", "read_file": "📄", "write_file": "✏️",
            "clipboard_read": "📋", "clipboard_write": "📋",
            "screenshot": "📸", "notify": "🔔", "shell_exec": "⚡",
            "schedule_task": "⏰", "research_topic": "📊",
        }
        icon = icon_map.get(tool_name, "🔧")
        display = text.replace("等待确认:", "等待确认：").strip()
        if tool_name == "research_topic":
            phase = display
            for prefix in ("调研阶段：", "调研阶段:"):
                if phase.startswith(prefix):
                    phase = phase[len(prefix):].strip()
            if phase:
                self._task_panel.update_detail(tid, phase)
        if "等待确认" in display:
            self._set_status("waiting", display[:26])
        else:
            self._set_status("working", display[:26] if display else "执行中...")

        if key in self._tool_cards:
            row = self._tool_cards[key]
            name_label = row.findChild(QLabel, "step_name")
            status_label = row.findChild(QLabel, "step_status")
            if name_label:
                name_label.setText(f"… {icon} {display}")
                name_label.setStyleSheet(f"color: {get_token('accent')}; font-size: 12px; background: transparent;")
            if status_label:
                status_label.setText("等待确认" if "等待确认" in display else "执行中")
                status_label.setFixedHeight(22)
                status_c = get_token('warning') if '等待确认' in display else get_token('accent')
                status_label.setStyleSheet(f"""
                color: {status_c}; background: rgba(59,130,246,0.12);
                border: 1px solid rgba(255,255,255,0.05); border-radius: 8px;
                padding: 0 10px; font-size: 11px; font-weight: 650;
                """)
        else:
            row = QWidget()
            row.setObjectName("tool_step_row")
            row.setFixedHeight(34)
            row.setStyleSheet("""
                QWidget#tool_step_row {
                    background: rgba(59,130,246,0.08);
                    border: 1px solid rgba(59,130,246,0.14);
                    border-radius: 8px;
                }
            """)
            rl = QHBoxLayout(row); rl.setContentsMargins(11, 0, 10, 0); rl.setSpacing(8)
            name = QLabel(f"… {icon} {display}")
            name.setObjectName("step_name")
            name.setStyleSheet(f"color: {get_token('warning') if '等待确认' in display else get_token('accent')}; font-size: 12px; background: transparent;")
            name.setWordWrap(False)
            rl.addWidget(name); rl.addStretch()
            status = QLabel("等待确认" if "等待确认" in display else "执行中")
            status.setObjectName("step_status")
            status.setFixedHeight(22)
            status_c = get_token('warning') if '等待确认' in display else get_token('accent')
            status.setStyleSheet(f"""
                color: {status_c}; background: rgba(59,130,246,0.12);
                border: 1px solid rgba(255,255,255,0.05); border-radius: 8px;
                padding: 0 10px; font-size: 11px; font-weight: 650;
            """)
            rl.addWidget(status, 0, Qt.AlignmentFlag.AlignVCenter)
            self._tool_cards[key] = row
            self._append_chat_widget(row)
        self._scroll_bottom()

    def _on_tool_result(self, tid, tool_name, text):
        key = (tid, tool_name)
        row = self._tool_cards.get(key)
        if row:
            name_label = row.findChild(QLabel, "step_name")
            status_label = row.findChild(QLabel, "step_status")
            failed = "超时" in text or "失败" in text
            icon = "✗" if failed else "✓"
            if name_label:
                name_label.setText(f"{icon} {text[:80]}")
            if status_label:
                status_label.setText("失败" if failed else "已完成")
            c = get_token("danger") if failed else get_token("success")
            row.setStyleSheet("""
                QWidget#tool_step_row {
                    background: rgba(24,24,29,0.72);
                    border: 1px solid rgba(255,255,255,0.055);
                    border-radius: 8px;
                }
            """)
            if name_label:
                name_label.setStyleSheet(f"color: {get_token('text_secondary')}; font-size: 12px; background: transparent;")
            if status_label:
                status_label.setFixedHeight(22)
                bg = "rgba(248,113,113,0.12)" if failed else "rgba(34,197,94,0.12)"
                status_label.setStyleSheet(f"""
                    color: {c}; background: {bg};
                    border: 1px solid rgba(255,255,255,0.05); border-radius: 8px;
                    padding: 0 10px; font-size: 11px; font-weight: 650;
                """)
            if failed:
                self._set_status("error", "工具失败")
        if tool_name == "research_topic":
            self._task_panel.update_detail(tid, "调研失败" if ("超时" in text or "失败" in text) else "调研完成")
        self._scroll_bottom()

    def _on_task_status(self, tid, status):
        self._task_panel.update_status(tid, status)
        if status in ("running", "pending"):
            self._set_status("working", "执行中...")
        elif status == "completed":
            self._set_status("idle", "已完成")
        elif status in ("failed", "cancelled"):
            self._set_status("error", "任务失败" if status == "failed" else "已取消")

    def _on_task_completed(self, tid):
        task = self.task_mgr.get_task(tid) if self.task_mgr else None
        if not task:
            logger.warning(f"ChatWindow task completed without task object: tid={tid}")
            return
        logger.info(
            f"ChatWindow task_completed received: tid={tid} result_len={len(task.result or '')}"
        )
        self._render_task_result(tid, task.result or "", source="task_completed")
        self._set_status("idle", "已完成")

    def _on_task_failed(self, tid):
        bubble = self._task_bubbles.get(tid)
        task = self.task_mgr.get_task(tid) if self.task_mgr else None
        err = task.error if task and task.error else "任务失败"
        if bubble:
            bubble._full = f"出错了: {err[:80]}"
            bubble.setText(bubble._full)
            bubble.adjustSize()
            self._update_bubble_size(bubble)
        self._set_status("error", "任务失败")

    def _on_hitl_needed(self, tid, tool_name, params):
        from PySide6.QtWidgets import QTextEdit

        brd = get_token("border")
        bg2 = get_token("bg_secondary")
        t2 = get_token("text_secondary")
        t3 = get_token("text_dim")
        tp = get_token("text_primary")
        blue = get_token("accent")
        self._set_status("waiting", f"等待确认：{tool_name}")

        # Collapse previous pending cards
        for key in list(self._hitl_cards.keys()):
            if key[0] == tid:
                self._collapse_hitl_card(key, "auto_rejected")

        tool_labels = {
            "write_file": "写入文件", "read_file": "读取文件", "shell_exec": "执行命令",
            "web_search": "联网搜索", "clipboard_write": "写入剪贴板",
            "clipboard_read": "读取剪贴板", "notify": "发送通知",
        }
        action_label = tool_labels.get(tool_name, tool_name)
        path_str = str(params.get("path") or params.get("file_path") or params.get("command") or "—")
        content_len = len(str(params.get("content", "")))
        content_preview = str(params.get("content") or params.get("text") or params.get("command") or "")[:220]
        risk_level = "低" if tool_name in ("write_file", "read_file", "notify") else "中"
        if tool_name == "shell_exec":
            risk_level = "中"
        preview_payload = str(params.get("content", "")) if tool_name == "write_file" else str(params)

        card = QWidget()
        card.setObjectName(f"hitl_{tid}_{tool_name}")
        card._state = "pending"
        card.setMinimumHeight(0)
        card.setStyleSheet(f"""
            QWidget#hitl_{tid}_{tool_name} {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(217,119,6,13), stop:0.36 {bg2});
                border: 1px solid rgba(217,119,6,200); border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14); layout.setSpacing(0)

        # Title row: ⚠ 需要确认 + risk badge
        title_row = QHBoxLayout()
        title = QLabel(f"⚠ 需要确认：{action_label}")
        card._card_title = title
        title.setStyleSheet(f"color: #f5d0a0; font-size: 14px; font-weight: 700; background: transparent;")
        title_row.addWidget(title); title_row.addStretch()
        risk_badge = QLabel(f"风险：{risk_level}")
        risk_badge.setStyleSheet(f"""
            color: #f5c37c; font-size: 12px; font-weight: 500; background: rgba(217,119,6,36);
            padding: 2px 8px; border-radius: 12px;
        """)
        title_row.addWidget(risk_badge)
        layout.addLayout(title_row)

        # Description
        desc_text = "确认后会在本地创建或修改文件。默认只显示摘要，完整内容可展开查看。"
        if tool_name == "shell_exec":
            desc_text = "确认后会执行本地命令。请确认命令内容和影响范围。"
        desc = QLabel(desc_text)
        desc.setStyleSheet(f"color: {t2}; font-size: 13px; background: transparent; margin: 4px 0 12px 0;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Facts table
        facts = QWidget()
        facts.setObjectName("hitl_facts")
        facts.setStyleSheet(f"""
            QWidget#hitl_facts {{
                background: rgba(18,18,20,190);
                border: 1px solid {brd};
                border-radius: 7px;
            }}
        """)
        fl = QVBoxLayout(facts); fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(0)
        for label, value in [
            ("操作类型", action_label),
            ("目标位置", path_str),
            ("内容摘要", content_preview or "（无内容）"),
            ("预计大小", f"约 {content_len} 字符" if content_len else "—"),
        ]:
            row = QWidget()
            row.setObjectName("hitl_fact_row")
            row.setStyleSheet("QWidget#hitl_fact_row { background: transparent; border-bottom: 1px solid #242428; min-height: 34px; }")
            rl = QHBoxLayout(row); rl.setContentsMargins(10, 7, 10, 7); rl.setSpacing(10)
            label_widget = QLabel(label)
            label_widget.setFixedWidth(92)
            label_widget.setStyleSheet(f"color: {t3}; font-size: 13px; background: transparent;")
            rl.addWidget(label_widget)
            rv = QLabel(value)
            rv.setStyleSheet(f"color: {tp}; font-size: 13px; background: transparent;")
            rv.setWordWrap(True)
            rl.addWidget(rv, 1)
            fl.addWidget(row)
        layout.addWidget(facts)

        # Preview toggle
        preview_toggle = QPushButton("展开预览 ▼")
        preview_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        preview_toggle.setStyleSheet(f"""
            QPushButton {{ color: {t3}; border: none; background: transparent; font-size: 13px; text-align: left; margin-top: 12px; }}
            QPushButton:hover {{ color: {t2}; }}
        """)
        layout.addWidget(preview_toggle)

        preview_text = QTextEdit()
        preview_text.setReadOnly(True)
        preview_text.setPlainText(preview_payload[:2000])
        preview_text.setMaximumHeight(86)
        preview_text.hide()
        preview_text.setStyleSheet(f"""
            QTextEdit {{ color: #cbd5e1; font-size: 12px; font-family: Consolas,monospace;
            background: #101012; border: 1px solid {brd}; border-radius: 7px; padding: 10px; }}
        """)
        layout.addWidget(preview_text)

        item = QListWidgetItem()

        def update_card_height():
            card.adjustSize()
            h = max(210, min(card.sizeHint().height() + 8, 360))
            item.setSizeHint(QSize(self.message_list.viewport().width() - 4, h))

        def toggle_preview():
            if preview_text.isVisible():
                preview_text.hide()
                preview_toggle.setText("展开预览 ▼")
            else:
                preview_text.show()
                preview_toggle.setText("收起预览 ▲")
            update_card_height()
        preview_toggle.clicked.connect(toggle_preview)

        # Buttons: 拒绝 · 修改要求 · 批准执行
        buttons = QWidget()
        buttons.setStyleSheet("background: transparent;")
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 12, 0, 0); btn_row.setSpacing(12)
        btn_row.addStretch()

        deny = QPushButton("拒绝")
        deny.setMinimumSize(86, 34)
        deny.setCursor(Qt.CursorShape.PointingHandCursor)
        deny.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {t3}; border: 1px solid {brd};
            border-radius: 8px; font-size: 13px; font-weight: 600; padding: 0 14px; }}
            QPushButton:hover {{ color: {tp}; border-color: {t3}; }}
        """)
        btn_row.addWidget(deny)

        modify = QPushButton("修改要求")
        modify.setMinimumSize(86, 34)
        modify.setCursor(Qt.CursorShape.PointingHandCursor)
        modify.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {t3}; border: 1px solid {brd};
            border-radius: 8px; font-size: 13px; font-weight: 600; padding: 0 14px; }}
            QPushButton:hover {{ color: {tp}; border-color: {t3}; }}
        """)
        btn_row.addWidget(modify)

        approve = QPushButton("批准执行")
        approve.setMinimumSize(86, 34)
        approve.setCursor(Qt.CursorShape.PointingHandCursor)
        approve.setStyleSheet(f"""
            QPushButton {{ background: {blue}; color: white; border: 1px solid rgba(59,130,246,180);
            border-radius: 8px; font-size: 13px; font-weight: 600; padding: 0 14px; }}
            QPushButton:hover {{ background: {get_token('accent_hover')}; }}
            QPushButton:pressed {{ background: {get_token('accent_press')}; }}
        """)
        btn_row.addWidget(approve)
        buttons.setLayout(btn_row)
        layout.addWidget(buttons)
        card._card_detail = preview_text
        card._card_buttons = buttons
        card._collapsible_widgets = [desc, facts, preview_toggle, preview_text, buttons]

        key = (tid, tool_name)
        self._hitl_cards[key] = {"card": card, "item": None}

        def on_approve():
            logger.info(f"HITL approve clicked: tid={tid} tool={tool_name}")
            self._resolve_hitl_card(tid, tool_name, True, card)
        def on_deny():
            logger.info(f"HITL deny clicked: tid={tid} tool={tool_name}")
            self._resolve_hitl_card(tid, tool_name, False, card)
        approve.clicked.connect(on_approve)
        deny.clicked.connect(on_deny)
        modify.clicked.connect(on_deny)  # same as deny for now

        QTimer.singleShot(300000, lambda: self._auto_reject_hitl(key))

        update_card_height()
        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, card)
        self._hitl_cards[key]["item"] = item
        self.message_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtBottom)

    def _toggle_hitl_preview(self):
        if self._preview_text.isVisible():
            self._preview_text.hide()
            self._preview_toggle.setText("展开预览 ▸")
        else:
            self._preview_text.show()
            self._preview_toggle.setText("收起预览 ▾")

    def _collapse_hitl_card(self, key, reason: str):
        """Collapse HITL card to one-line summary."""
        data = self._hitl_cards.get(key)
        if not data:
            return
        card = data["card"]
        if getattr(card, "_state", "") == "collapsed":
            return

        card._state = "collapsed"
        tid, tool_name = key

        # Hide detail sections and leave a quiet one-line receipt.
        for widget in getattr(card, "_collapsible_widgets", []):
            widget.hide()
        if hasattr(card, '_card_detail'):
            card._card_detail.hide()
        if hasattr(card, '_card_buttons'):
            card._card_buttons.hide()

        # Show collapsed summary
        icons = {"confirmed": "OK", "rejected": "X", "auto_rejected": "timeout"}
        icon = icons.get(reason, "?")
        tool_labels = {"web_search": "search", "read_file": "read file", "write_file": "write file",
                       "shell_exec": "shell", "clipboard_read": "clipboard", "clipboard_write": "clipboard",
                       "screenshot": "screenshot", "notify": "notify"}
        label = tool_labels.get(tool_name, tool_name)
        if hasattr(card, '_card_title'):
            card._card_title.setText(f"{icon} {label} ({reason})")
            card._card_title.setStyleSheet("color: #888; font-size: 11px; font-weight: 400; background: transparent;")

        card.setMinimumHeight(24)
        card.setMaximumHeight(28)
        card.setStyleSheet(
            "QWidget { background: rgba(20,20,24,0.6); border-radius: 4px;"
            "border: 1px solid rgba(255,255,255,0.04); }")

        # Update item size
        item = data["item"]
        if item:
            item.setSizeHint(QSize(self.message_list.viewport().width() - 4, 30))

    def _auto_reject_hitl(self, key):
        """Auto-reject card that timed out, if still pending."""
        data = self._hitl_cards.get(key)
        if not data:
            return
        card = data["card"]
        if getattr(card, "_state", "") != "pending":
            return
        tid, tool_name = key
        logger.info(f"HITL auto-rejected (timeout): tid={tid} tool={tool_name}")
        if self.task_mgr:
            self.task_mgr.resolve_hitl(tid, tool_name, False)
        self._set_status("idle", "确认超时，已跳过")
        self._collapse_hitl_card(key, "auto_rejected")

    def _resolve_hitl_card(self, tid, tool_name, approved, card):
        if self.task_mgr:
            self.task_mgr.resolve_hitl(tid, tool_name, approved)
        self._set_status("working" if approved else "idle", "继续执行..." if approved else "已拒绝执行")
        key = (tid, tool_name)
        self._collapse_hitl_card(key, "confirmed" if approved else "rejected")

    def collapse_all_hitl(self):
        """Collapse all HITL cards (called on task completion)."""
        for key in list(self._hitl_cards.keys()):
            data = self._hitl_cards.get(key)
            if data and getattr(data["card"], "_state", "") == "pending":
                self._collapse_hitl_card(key, "auto_rejected")

    def _set_status(self, state: str, text: str = ""):
        """Update status bar dot color and text."""
        colors = {
            "idle": get_token("success"), "working": get_token("accent"),
            "waiting": get_token("warning"), "error": get_token("danger"),
        }
        c = colors.get(state, get_token("success"))
        self._status_dot.setStyleSheet(f"background: {c}; border-radius: 4px;")
        if state == "working":
            self._breath_anim.start()
        else:
            self._breath_anim.stop()
            self._status_dot.setWindowOpacity(1.0)
        if text:
            self._status_text.setText(text)

    def _toggle_task_panel(self):
        if self._task_panel.isHidden() and self._task_panel._cards:
            self._task_panel.show()
        self._task_panel.toggle()

    def set_scheduled_task_manager(self, mgr):
        self._scheduled_task_panel.set_manager(mgr)

    def _toggle_scheduled_panel(self):
        p = self._scheduled_task_panel
        if p.isHidden() and p._mgr and p._mgr.get_all_tasks():
            p.show()
        p.toggle()

    def _on_chunk(self, chunk: str):
        if self._cb:
            if self._cb._full == "...": self._cb._full = ""
            self._cb.append_text(chunk)
            self._update_bubble_size(self._cb)

    def _on_done(self, em: str):
        self._cb = None
        self._send_btn.setEnabled(True)
        self._set_status("idle", "空闲中")
        self.emotion_changed.emit(em)
        if hasattr(self, '_last_cat') and self._last_cat:
            txt = self._last_cat._full
            if txt: self.bubble_requested.emit(txt[:30])
        QTimer.singleShot(5000, lambda: self.emotion_changed.emit("idle"))

    def _on_error(self, err: str):
        self._cb = None
        self._send_btn.setEnabled(True)
        self._set_status("error", "出错了")
        if hasattr(self, '_last_cat') and self._last_cat:
            self._last_cat.setText(f"出错了: {err[:60]}")
            self._last_cat.adjustSize()

    def _trigger_screen_capture(self):
        """立刻触发一次截屏分析，结果注入 agent 上下文"""
        import threading, base64, io
        from agent.llm.router import get_llm_config

        llm = get_llm_config()
        if not llm.get("api_key"):
            return

        def _capture():
            try:
                import pyautogui
                screenshot = pyautogui.screenshot()
                if screenshot.width > 1280:
                    ratio = 1280 / screenshot.width
                    screenshot = screenshot.resize((1280, int(screenshot.height * ratio)))
                buf = io.BytesIO()
                screenshot.save(buf, format="PNG", optimize=True)
                img_b64 = base64.b64encode(buf.getvalue()).decode()
                vision_msg = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "描述这张截图：1)用户正在使用什么应用 2)应用名称/窗口标题 3)用户在做什么具体操作。用中文回答，30字以内。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    ],
                }
                from openai import OpenAI
                cl = OpenAI(api_key=llm["api_key"], base_url=llm["base_url"], timeout=30)
                resp = cl.chat.completions.create(
                    model=llm["model"],
                    messages=[vision_msg],
                    max_tokens=200,
                )
                result = resp.choices[0].message.content or ""
                if result:
                    self.agent.handle_perception("screen", result)
            except Exception:
                logger.debug("screen capture failed (non-critical)", exc_info=True)

        threading.Thread(target=_capture, daemon=True).start()

    def _add_msg(self, text, is_user):
        bubble = MessageBubble(text, is_user)
        if not is_user: self._last_cat = bubble

        from datetime import datetime
        now = datetime.now().strftime("%H:%M")
        bg2 = get_token("bg_secondary")
        brd = get_token("border")
        t2 = get_token("text_secondary")

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 10)
        row_layout.setSpacing(7)

        # Event head: speaker name + time
        head = QHBoxLayout(); head.setSpacing(8)
        speaker = QLabel("用户" if is_user else "deskagent")
        speaker.setStyleSheet(f"color: {get_token('text_primary')}; font-size: 12px; font-weight: 650; background: transparent;")
        head.addWidget(speaker)
        time_label = QLabel(now)
        time_label.setStyleSheet(f"color: {t2}; font-size: 12px; background: transparent;")
        head.addWidget(time_label)
        head.addStretch()
        row_layout.addLayout(head)

        max_msg_width = self._message_max_width()
        bubble.setMaximumWidth(max_msg_width)
        if is_user:
            # User message in a bordered card
            bubble.setStyleSheet(bubble.styleSheet() + f"""
                QLabel {{ background: {bg2}; border: 1px solid {brd}; border-radius: 8px;
                padding: 12px 14px; font-size: 14px; line-height: 165%; color: {get_token('text_primary')}; }}
            """)
            bubble.setWordWrap(True)
            bubble.setMinimumWidth(200)
            row_layout.addWidget(bubble)
        else:
            # Cat message: a softer card than the user's input, for readability.
            bubble.setStyleSheet(f"""
                QLabel {{ color: {get_token('text_primary')}; font-size: 14px;
                background: rgba(24,24,29,0.72); border: 1px solid rgba(255,255,255,0.055);
                border-radius: 10px; padding: 13px 15px; line-height: 175%; }}
            """)
            bubble.setWordWrap(True)
            bubble.setMinimumWidth(260)
            bubble.setMaximumWidth(max_msg_width)
            row_layout.addWidget(bubble)

        # Dashed separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: transparent; border-bottom: 1px solid rgba(255,255,255,0.035);")
        row_layout.addWidget(sep)

        bubble.adjustSize()
        row.adjustSize()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        item = QListWidgetItem()
        list_w = self.message_list.viewport().width() - 4
        h = row.sizeHint().height() + 4
        item.setSizeHint(QSize(max(list_w, 180), max(h, 60)))
        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, row)
        self._task_bubbles.setdefault("__item__", {})[id(bubble)] = item
        self._task_bubbles.setdefault("__row__", {})[id(bubble)] = row
        self._task_bubbles.setdefault("__layout__", {})[id(bubble)] = row_layout
        self.message_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtBottom)
        return bubble

    def _append_chat_widget(self, widget):
        """Append standalone status widget inside the transcript column."""
        target = self._cb or self._last_cat
        if target:
            layouts = self._task_bubbles.get("__layout__", {})
            rows = self._task_bubbles.get("__row__", {})
            items = self._task_bubbles.get("__item__", {})
            layout = layouts.get(id(target))
            row = rows.get(id(target))
            item = items.get(id(target))
            if layout and row and item:
                if getattr(target, "_full", "") == "...":
                    target.setText("")
                    target.setFixedHeight(0)
                    target.setMinimumHeight(0)
                    target.setMaximumHeight(0)
                widget.setMinimumWidth(0)
                widget.setMaximumWidth(self._message_max_width() - 48)
                holder = QWidget()
                holder.setStyleSheet("background: transparent;")
                holder.setMinimumHeight(widget.sizeHint().height() + 12)
                holder_layout = QHBoxLayout(holder)
                holder_layout.setContentsMargins(24, 6, 24, 8)
                holder_layout.setSpacing(0)
                holder_layout.addWidget(widget)
                holder_layout.addStretch()
                insert_at = max(0, layout.count() - 1)
                layout.insertWidget(insert_at, holder)
                holder.adjustSize()
                row.adjustSize()
                item.setSizeHint(QSize(self.message_list.viewport().width() - 4, max(row.sizeHint().height() + 18, 96)))
                self.message_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtBottom)
                return

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(16, 6, 16, 8)
        step_width = min(self._message_max_width(), max(520, self.message_list.viewport().width() - 120))
        widget.setMinimumWidth(step_width)
        widget.setMaximumWidth(step_width)
        rl.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        rl.addStretch()

        widget.adjustSize()
        row.adjustSize()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        item = QListWidgetItem()
        h = max(row.sizeHint().height() + 8, widget.sizeHint().height() + 18)
        item.setSizeHint(QSize(self.message_list.viewport().width() - 4, max(h, 36)))
        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, row)
        self.message_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtBottom)

    def _render_task_result(self, tid: str, full: str, source: str):
        if not full:
            logger.warning(f"ChatWindow render skipped empty result: tid={tid} source={source}")
            return

        bubble = self._task_bubbles.get(tid)
        if bubble:
            # Update bubble if: TASK (no streaming), or bubble still has placeholder text
            is_task = self._task_types.get(tid) == "task"
            is_placeholder = bubble._full == "..." or not bubble._full
            if is_task or is_placeholder:
                bubble._full = full
                bubble.setMinimumHeight(0)
                bubble.setMaximumHeight(16777215)
                bubble.setText(full)
                bubble.adjustSize()
                self._rendered_task_results.add(tid)
                self._update_bubble_size(bubble)
                logger.info(
                    f"ChatWindow render updated existing bubble: tid={tid} source={source} "
                    f"reply_len={len(full)}"
                )
                return
            else:
                # CHAT type: streaming already filled the bubble, just mark rendered
                self._rendered_task_results.add(tid)
                logger.info(
                    f"ChatWindow render skipped: tid={tid} source={source} "
                    f"(CHAT streaming already filled bubble)"
                )
                return

        if tid in self._rendered_task_results:
            logger.info(f"ChatWindow render skipped duplicate: tid={tid} source={source}")
            return

        summary = full if len(full) <= 300 else full[:297] + "..."
        bubble = self._add_msg(summary, False)
        self._task_bubbles[tid] = bubble
        self._task_types.setdefault(tid, "task")
        self._rendered_task_results.add(tid)
        logger.info(
            f"ChatWindow render created fallback bubble: tid={tid} source={source} "
            f"reply_len={len(full)} shown_len={len(summary)}"
        )

    def _update_bubble_size(self, bubble):
        """Update QListWidgetItem sizeHint after bubble text changes (streaming etc)."""
        items = self._task_bubbles.get("__item__", {})
        item = items.get(id(bubble))
        if item:
            row = self._task_bubbles.get("__row__", {}).get(id(bubble))
            if row:
                max_width = self._message_max_width()
                bubble.setMaximumWidth(max_width)
                if bubble is self._last_cat:
                    bubble.setMinimumWidth(max_width)
                bubble.adjustSize()
                row.adjustSize()
                h = max(row.sizeHint().height() + 4, 60)
                item.setSizeHint(QSize(self.message_list.viewport().width() - 4, h))
            else:
                item.setSizeHint(bubble.sizeHint())
            self.message_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtBottom)

    def _message_max_width(self):
        """Keep messages readable while using most of the chat column."""
        viewport_w = self.message_list.viewport().width()
        if viewport_w <= 0:
            viewport_w = self._window_w - 44
        return max(360, min(660, viewport_w - 40))

    def _scroll_bottom(self, reason: str = ""):
        """Scroll to last item — QListWidget native, no manual scrollbar manipulation."""
        count = self.message_list.count()
        if count > 0:
            last = self.message_list.item(count - 1)
            self.message_list.scrollToItem(last, QAbstractItemView.ScrollHint.PositionAtBottom)

    # ═══ Drag ═══
    def mousePressEvent(self, ev):
        if ev.position().y() < 56:
            self._dr = True; self._dp = ev.globalPosition().toPoint()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._dr and self._dp:
            d = ev.globalPosition().toPoint() - self._dp
            self.move(self.pos() + d); self._dp = ev.globalPosition().toPoint()

    def mouseReleaseEvent(self, ev):
        self._dr = False; self._dp = None

    # ═══ Onboarding stubs ═══
    def _add_onboarding_message(self, t, u): self._add_msg(t, u)
    def _show_onboarding_input(self, ph, cb):
        self._ocb = cb; self._input.setPlaceholderText(ph); self._input.setFocus()
        self._input.returnPressed.disconnect(); self._input.returnPressed.connect(lambda: self._oi_submit(cb))
    def _oi_submit(self, cb):
        t = self._input.text().strip()
        if not t: return
        self._add_msg(t, True); self._input.clear(); cb(t)
    def _show_onboarding_api_key(self, cb):
        self._ocb = cb; self._input.setPlaceholderText("输入 DeepSeek API Key...")
        self._input.setEchoMode(QLineEdit.EchoMode.Password); self._input.setFocus()
        self._input.returnPressed.disconnect(); self._input.returnPressed.connect(lambda: self._oak_submit(cb))
    def _oak_submit(self, cb):
        t = self._input.text().strip()
        if not t: return
        self._add_msg("API Key 已设置", True); self._input.clear()
        self._input.setEchoMode(QLineEdit.EchoMode.Normal); cb(t)
    def _hide_onboarding_input(self):
        self._input.setPlaceholderText("跟 deskagent 说点什么...")
        self._input.setEchoMode(QLineEdit.EchoMode.Normal)
        try: self._input.returnPressed.disconnect()
        except: pass
        self._input.returnPressed.connect(self._send)
