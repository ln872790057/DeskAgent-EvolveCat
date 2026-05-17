import os, math, time, random
from PySide6.QtCore import (
    Qt, Signal, QTimer, QSize, QPoint, QPropertyAnimation, QEasingCurve, QRectF,
)
from PySide6.QtGui import (
    QPixmap, QCursor, QMouseEvent, QGuiApplication, QPainter, QColor, QFont, QPen,
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QApplication, QGraphicsOpacityEffect, QMenu,
)
from utils.platform_compat import IS_MACOS

RES = os.path.join(os.path.dirname(__file__), "resources", "cat")

STATE_F = {
    "idle":"idle.png","talking":"talking.png","sleeping":"sleeping.png",
    "annoyed":"annoyed.png","sick":"sick.png","happy":"happy.png","curious":"curious.png",
}
MAP = {"idle":"idle","sleep":"sleeping","talk":"talking","happy":"happy",
       "angry":"annoyed","working":"curious","sleeping":"sleeping","walk":"idle",
       "sick_dizzy":"sick","sick_sleepy":"sleeping","sick_frustrated":"annoyed","sick_blind":"sick"}
def _m(e): return MAP.get(e,"idle")

# ── Emoji bubble types ──
class EmojiBubble(QLabel):
    """Floating emoji bubble that fades out."""
    def __init__(self, emoji, parent):
        super().__init__(emoji, parent)
        font = QFont("Segoe UI Emoji", 22)
        self.setFont(font); self.setStyleSheet("background:transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.adjustSize(); self.hide()

    def show_at(self, x, y):
        self.move(x, y); self.show(); self.raise_()
        eff = QGraphicsOpacityEffect(self); self.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", self); a.setDuration(1500)
        a.setStartValue(1.0); a.setEndValue(0); a.setEasingCurve(QEasingCurve.Type.OutQuad)
        a.finished.connect(self.hide); a.start()

    def show_with_duration(self, x, y, ms):
        self.move(x, y); self.show(); self.raise_()
        eff = QGraphicsOpacityEffect(self); self.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", self); a.setDuration(ms)
        a.setStartValue(1.0); a.setEndValue(0) if ms > 400 else a.setEndValue(0.6)
        a.setEasingCurve(QEasingCurve.Type.OutQuad)
        a.finished.connect(self.hide); a.start()


class PetWindow(QWidget):
    clicked = Signal(); double_clicked = Signal()
    drag_started = Signal(); drag_ended = Signal()
    request_emotion = Signal(str)
    file_dropped = Signal(str, str)  # file_path, content

    def __init__(self, monitor_index=0):
        super().__init__()
        self.setObjectName("pet_window")
        self._dp = None; self._pt = 0.0; self._lc = None; self._dr = False
        self._st = "idle"; self._prev_st = "idle"
        self._fp = None; self._li = time.time()
        self.agent = None; self.chat_window = None; self.sound_manager = None
        self._sp = {}; self._mouse_near = False; self._hover = False
        self._sleep_clicked = False; self._curious_active = False
        self.setAcceptDrops(True)

        self._init_win(monitor_index)
        self._init_sprites()
        self._init_bubble()
        self._init_timers()
        self.setMouseTracking(True)

    # ═══ Window ═══
    def _init_win(self, mi):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if IS_MACOS: self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")
        self.setFixedSize(150, 150); self.setWindowTitle("deskagent")
        s = QApplication.primaryScreen()
        if s:
            ss = QApplication.screens(); s = ss[mi] if mi < len(ss) else s
            g = s.availableGeometry(); self.move(g.right()-170, g.bottom()-190)

    # ═══ Sprites ═══
    def _init_sprites(self):
        for state, fn in STATE_F.items():
            path = os.path.join(RES, fn)
            pm = QPixmap(path) if os.path.exists(path) else QPixmap()
            if not pm.isNull():
                self._sp[state] = pm.scaled(QSize(126,126), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)

        # Main label
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._label.setStyleSheet("background: transparent;")
        self._label.setGeometry(12, 12, 126, 126)

        # Fade effect
        self._eff = QGraphicsOpacityEffect(self._label); self._eff.setOpacity(1.0)
        self._label.setGraphicsEffect(self._eff)

        # Emoji bubbles
        self._heart = EmojiBubble("❤", self)
        self._anger = EmojiBubble("💢", self)
        self._zzz   = EmojiBubble("💤", self)

        self._set_sprite("idle")

    def _set_sprite(self, state, animate=True):
        if state == self._st: return
        self._prev_st = self._st; self._st = state
        pm = self._sp.get(state, self._sp.get("idle"))
        if not pm or pm.isNull(): return

        if animate and self._prev_st != state:
            # 15+16: elastic scale + cross-fade
            self._animate_switch(pm)
        else:
            self._label.setPixmap(pm)
            self._eff.setOpacity(1.0)

    def _animate_switch(self, new_pm):
        # Fade out old
        a1 = QPropertyAnimation(self._eff, b"opacity", self); a1.setDuration(100)
        a1.setStartValue(1.0); a1.setEndValue(0.3)
        a1.finished.connect(lambda: self._do_fade_in(new_pm))
        a1.start()

    def _do_fade_in(self, new_pm):
        self._label.setPixmap(new_pm)
        geo = self._label.geometry()
        self._label.resize(int(126*0.95), int(126*0.95))
        self._label.move(12 + int(126*0.025), 12 + int(126*0.025))
        a2 = QPropertyAnimation(self._eff, b"opacity", self); a2.setDuration(150)
        a2.setStartValue(0.3); a2.setEndValue(1.0)
        a2.start()
        QTimer.singleShot(100, lambda: self._label.setGeometry(geo))

    # ═══ Timers ═══
    def _init_timers(self):
        # Proximity check every 200ms
        self._prox_t = QTimer(self); self._prox_t.timeout.connect(self._check_proximity)
        self._prox_t.start(200)
        # Random blink (3-8s)
        self._blink_t = QTimer(self); self._blink_t.timeout.connect(self._do_blink)
        self._schedule_blink()
        # Curious peek (15-30s)
        self._peek_t = QTimer(self); self._peek_t.timeout.connect(self._do_peek)
        self._schedule_peek()
        # Sleep Zzz
        self._zzz_t = QTimer(self); self._zzz_t.timeout.connect(self._do_zzz)
        self._schedule_zzz()
        # Sleep auto-check
        self._sleep_t = QTimer(self); self._sleep_t.timeout.connect(self._check_sleep)
        self._sleep_t.start(10000)
        # Talking auto-restore
        self._talk_restore = QTimer(self); self._talk_restore.setSingleShot(True)
        self._talk_restore.timeout.connect(lambda: self._restore_from_talk())

    def _schedule_blink(self):
        self._blink_t.setInterval(random.randint(3000, 8000)); self._blink_t.start()

    def _schedule_peek(self):
        self._peek_t.setInterval(random.randint(15000, 30000)); self._peek_t.start()

    def _schedule_zzz(self):
        self._zzz_t.setInterval(random.randint(10000, 20000)); self._zzz_t.start()

    # ═══ 6. Random blink ═══
    def _do_blink(self):
        if self._st != "idle" or self._hover: self._schedule_blink(); return
        a = QPropertyAnimation(self._label, b"geometry", self)
        geo = self._label.geometry()
        y = geo.y() + int(126*0.075)
        h = int(126*0.85)
        a.setDuration(75); a.setStartValue(geo)
        a.setEndValue(QRectF(geo.x(), y, 126, h))
        a.setEasingCurve(QEasingCurve.Type.OutQuad)
        a2 = QPropertyAnimation(self._label, b"geometry", self)
        a2.setDuration(75); a2.setStartValue(QRectF(geo.x(), y, 126, h))
        a2.setEndValue(QRectF(geo.x(), geo.y(), 126, 126))
        a2.setEasingCurve(QEasingCurve.Type.InQuad)
        a.finished.connect(a2.start)
        a.start()
        self._schedule_blink()

    # ═══ 7. Sleep check ═══
    def _check_sleep(self):
        if self._st == "idle" and time.time() - self._li > 300:
            self.set_state("sleeping")

    def _do_zzz(self):
        if self._st != "sleeping": self._schedule_zzz(); return
        x = self._label.x() + 70; y = self._label.y() - 10
        self._zzz.show_with_duration(x, y, 2000)
        self._schedule_zzz()

    # ═══ 10. Curious peek ═══
    def _do_peek(self):
        if self._st != "idle" or self._hover or self._mouse_near:
            self._schedule_peek(); return
        self._curious_active = True
        self._set_sprite("curious")
        QTimer.singleShot(2000, self._end_peek)
        self._schedule_peek()

    def _end_peek(self):
        if self._curious_active and self._st == "curious":
            self._curious_active = False
            self._set_sprite("idle")

    # ═══ Proximity ═══
    def _check_proximity(self):
        if self._st == "sleeping": return
        pos = QCursor.pos(); c = self.geometry().center()
        dist = ((pos.x()-c.x())**2 + (pos.y()-c.y())**2) ** 0.5
        was_near = self._mouse_near
        self._mouse_near = dist < 80  # ~50px from edge
        if self._mouse_near and not was_near and self._st in ("idle",):
            self._set_sprite("curious")
        elif not self._mouse_near and was_near and self._st == "curious" and not self._hover and not self._curious_active:
            self._set_sprite("idle")

    # ═══ Mouse events ═══
    def enterEvent(self, ev):
        self._hover = True
        if self._st in ("idle", "curious") and not self._sleep_clicked:
            self._set_sprite("happy")
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        if self._st == "happy" and not self._sleep_clicked:
            self._set_sprite("idle")
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            self._show_menu(ev.globalPosition().toPoint())
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            self._dp = ev.globalPosition().toPoint(); self._pt = time.time(); self._dr = False
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton and self._dp:
            d = ev.globalPosition().toPoint() - self._dp
            if not self._dr and (abs(d.x())>3 or abs(d.y())>3):
                self._dr = True; self._ps("drag"); self.drag_started.emit()
            if self._dr:
                np = self.pos() + d; self._dp = ev.globalPosition().toPoint()
                s = QApplication.screenAt(self.pos())
                if s:
                    g = s.availableGeometry()
                    self.move(max(g.left(), min(g.right()-self.width(), np.x())),
                              max(g.top(), min(g.bottom()-self.height(), np.y())))
                else: self.move(np)
                self._li = time.time()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton: return
        if self._dr: self._dr = False; self.drag_ended.emit(); self._li = time.time(); return
        if time.time() - self._pt < 0.3:
            self._li = time.time(); n = time.time()
            if self._lc and (n-self._lc) < 0.5:
                # 3: Double click → happy + heart
                self._ps("meow_annoyed"); self.double_clicked.emit()
                self._set_sprite("happy")
                x = self._label.x() + 50; y = self._label.y() - 20
                self._heart.show_at(x, y)
                QTimer.singleShot(2000, lambda: self._restore_state())
                self._lc = None
            else:
                self._lc = n
                if self._st == "sleeping":
                    # 8: Sleep click → annoyed + anger
                    self._sleep_clicked = True
                    self._set_sprite("annoyed")
                    x = self._label.x() + 50; y = self._label.y() - 20
                    self._anger.show_at(x, y)
                    QTimer.singleShot(1000, lambda: self._wake_from_sleep())
                else:
                    QTimer.singleShot(500, self._es)

    def _es(self):
        if self._lc and (time.time()-self._lc) >= 0.4:
            self._ps("meow"); self.clicked.emit()

    def _show_menu(self, pos):
        m = QMenu()  # no parent — inherit global QSS
        m.setObjectName("pet_menu")
        m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)  # opaque for QSS
        a1 = m.addAction("⚙  设置")
        a1.triggered.connect(lambda: self._open_settings())
        a2 = m.addAction("—  最小化")
        a2.triggered.connect(self.hide)
        m.addSeparator()
        a3 = m.addAction("✕  退出")
        a3.triggered.connect(lambda: QApplication.quit())
        m.exec(pos)

    # ═══ Restore helpers ═══
    def _restore_state(self):
        if self._st not in ("sleeping",): self._set_sprite("idle")

    def _wake_from_sleep(self):
        self._sleep_clicked = False
        self._set_sprite("idle")

    def _restore_from_talk(self):
        if self._st == "talking": self._set_sprite("idle")

    # ═══ Public API ═══
    def set_state(self, s: str):
        m = _m(s)
        self._set_sprite(m)
        if m == "talking":
            self._talk_restore.start(2000)  # 9
        if m != "sleeping":
            self._li = time.time()

    def set_emotion(self, e): self.set_state(e)

    def set_agent(self, a): self.agent = a
    def set_sound_manager(self, sm): self.sound_manager = sm
    def _ps(self, n):
        if self.sound_manager: self.sound_manager.play(n)
    def show_bubble(self, t): self.bubble.show_bubble(t)
    def get_idle_duration(self): return time.time() - self._li
    def mark_interaction(self): self._li = time.time()

    def _open_settings(self):
        from ui.settings_window import SettingsWindow
        dlg = SettingsWindow(agent=self.agent, sound_manager=self.sound_manager)
        dlg.exec()

    def _open_chat_window(self):
        if self.chat_window is None:
            from ui.chat_window import ChatWindow
            self.chat_window = ChatWindow(agent=self.agent, task_manager=getattr(self, 'task_mgr', None))
            self.chat_window.emotion_changed.connect(self._oce)
            self.chat_window.bubble_requested.connect(self.show_bubble)
            sched_mgr = getattr(self, '_scheduled_task_mgr', None)
            if sched_mgr:
                self.chat_window.set_scheduled_task_manager(sched_mgr)
        if self.chat_window.isVisible():
            self.chat_window.raise_(); self.chat_window.activateWindow()
        else:
            cw = self.chat_window
            cw_w, cw_h = 760, 680
            pet_geo = self.geometry()
            screen = QGuiApplication.primaryScreen()
            sg = screen.availableGeometry() if screen else None
            if sg:
                # Try right side first, then left, then clamp
                x = pet_geo.right() + 6
                y = pet_geo.top()
                if x + cw_w > sg.right():
                    x = pet_geo.left() - cw_w - 6
                if x < sg.left():
                    x = sg.left() + 10
                if y + cw_h > sg.bottom():
                    y = sg.bottom() - cw_h - 10
                if y < sg.top():
                    y = sg.top() + 10
                cw.move(x, y)
            cw.show()
        self.mark_interaction()

    def _oce(self, em):
        self.request_emotion.emit(em)
        if em == "happy": self._ps("cute_meow")
        elif em == "angry": self._ps("hiss")

    def enter_focus_mode(self):
        self._fp = self.pos()
        s = QApplication.screenAt(self.pos())
        if s:
            g = s.availableGeometry(); self.move(g.right()-self.width()-10, g.bottom()-self.height()-10)
    def exit_focus_mode(self):
        if self._fp: self.move(self._fp); self._fp = None

    def _init_bubble(self):
        from ui.bubble import BubbleWidget
        self.bubble = BubbleWidget(self); self.bubble.hide()

    # ═══ Drag-drop file support ═══
    _TEXT_EXTENSIONS = {
        ".txt", ".md", ".py", ".json", ".csv", ".log",
        ".xml", ".yaml", ".yml", ".html", ".css", ".js",
        ".ts", ".tsx", ".jsx", ".vue", ".toml", ".ini", ".cfg",
    }

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                ext = os.path.splitext(path)[1].lower()
                if ext in self._TEXT_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            ext = os.path.splitext(path)[1].lower()
            if ext not in self._TEXT_EXTENSIONS:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(10000)
                self.file_dropped.emit(path, content)
                self.show_bubble(f"已读取: {os.path.basename(path)}")
                self.mark_interaction()
            except Exception:
                self.show_bubble("这个文件读不了...")
            break  # only process first valid file
