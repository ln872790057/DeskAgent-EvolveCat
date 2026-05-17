from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QSlider, QWidget, QFormLayout,
    QGroupBox, QMessageBox, QScrollArea,
)
from utils.config import get_config, save_config, reload_config
from utils.logger import get_logger
from ui.theme import get_token, get_mode

logger = get_logger()


class SettingsWindow(QDialog):
    config_saved = Signal()

    def __init__(self, agent=None, sound_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("settings_window")
        self.agent = agent
        self.sound_manager = sound_manager
        self.config = get_config()
        self._init_ui()
        self.setWindowTitle("deskagent - 设置")
        self.setMinimumSize(540, 460)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        tabs = QTabWidget()
        tabs.setObjectName("settings_tabs")

        for title, widget in [
            ("模型配置", self._tab_model()),
            ("感知与行为", self._tab_perception()),
            ("外观与语音", self._tab_appearance()),
            ("数据与隐私", self._tab_data()),
            ("关于", self._tab_about()),
        ]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            tabs.addTab(scroll, title)

        layout.addWidget(tabs)

        # Bottom: cancel + save (no extra bg panel)
        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject); btn_row.addWidget(cancel)
        save = QPushButton("保存")
        save.setObjectName("save_btn")
        save.setProperty("cssClass", "primary")
        save.clicked.connect(self._on_save); btn_row.addWidget(save)
        layout.addLayout(btn_row)

    # ═══ Tab: 模型配置 (V2 单模型) ═══
    def _tab_model(self):
        from agent.llm.router import get_llm_config, save_llm_config
        llm = get_llm_config()

        w = QWidget(); layout = QVBoxLayout(w)

        grp = QGroupBox("模型配置"); f = QFormLayout(grp); f.setSpacing(10)
        self._llm_key = QLineEdit(llm["api_key"]); self._llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_key.setPlaceholderText("输入 API Key...")
        self._llm_url = QLineEdit(llm["base_url"]); self._llm_url.setPlaceholderText("https://ark.cn-beijing.volces.com/api/v3")
        self._llm_model = QLineEdit(llm["model"]); self._llm_model.setPlaceholderText("doubao-seed-2.0-thinking-pro")

        test_btn = QPushButton("测试连接"); test_btn.clicked.connect(lambda: self._test_conn())
        f.addRow("API Key:", self._llm_key)
        f.addRow("Base URL:", self._llm_url)
        f.addRow("Model:", self._llm_model)
        f.addRow("", test_btn)
        layout.addWidget(grp)

        # Proxy
        grp3 = QGroupBox("代理设置"); proxy_row = QHBoxLayout(grp3)
        self.proxy_enabled = QCheckBox("启用代理")
        self.proxy_enabled.setChecked(self.config.get("proxy", {}).get("enabled", False))
        self.proxy_url = QLineEdit(self.config.get("proxy", {}).get("http", "http://127.0.0.1:7897"))
        proxy_row.addWidget(self.proxy_enabled); proxy_row.addWidget(self.proxy_url)
        layout.addWidget(grp3)
        layout.addStretch()
        return w

    def _test_conn(self):
        key, url, model = self._llm_key.text(), self._llm_url.text(), self._llm_model.text()
        if not key or not url:
            QMessageBox.warning(self, "提示", "请填写 API Key 和 Base URL"); return
        try:
            from openai import OpenAI
            base = url.rstrip("/")
            cl = OpenAI(api_key=key, base_url=base, timeout=15)
            cl.chat.completions.create(model=model, messages=[{"role":"user","content":"hi"}], max_tokens=5)
            QMessageBox.information(self, "成功", "连接正常！")
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e)[:120])

    # ═══ Tab: 感知与行为 ═══
    def _tab_perception(self):
        w = QWidget(); layout = QVBoxLayout(w)
        grp = QGroupBox("感知设置")
        fl = QFormLayout(grp); fl.setSpacing(10)
        cfg = self.config.get("perception", {})

        self.screen_enabled = QCheckBox(); self.screen_enabled.setChecked(True)
        fl.addRow("截屏感知:", self.screen_enabled)

        self.screen_interval = QSlider(Qt.Orientation.Horizontal)
        self.screen_interval.setRange(60, 600)
        self.screen_interval.setValue(cfg.get("screen_capture_interval", 300))
        self._sl = QLabel(f"截屏间隔: {self.screen_interval.value()}秒")
        self.screen_interval.valueChanged.connect(lambda v: self._sl.setText(f"截屏间隔: {v}秒"))
        fl.addRow(self._sl, self.screen_interval)

        self.clipboard_enabled = QCheckBox(); self.clipboard_enabled.setChecked(True)
        fl.addRow("剪贴板监听:", self.clipboard_enabled)
        self.window_enabled = QCheckBox(); self.window_enabled.setChecked(True)
        fl.addRow("窗口监控:", self.window_enabled)
        self.proactive_enabled = QCheckBox(); self.proactive_enabled.setChecked(True)
        fl.addRow("主动搭话:", self.proactive_enabled)

        layout.addWidget(grp)

        grp2 = QGroupBox("行为"); fl2 = QFormLayout(grp2); fl2.setSpacing(10)
        fl2.addRow("毒舌程度 (1-5):", QLabel(""))
        self.sass = QSlider(Qt.Orientation.Horizontal); self.sass.setRange(1, 5)
        self.sass.setValue(self.config.get("personality", {}).get("sass_level", 3))
        fl2.addRow(self.sass)
        layout.addWidget(grp2)
        layout.addStretch()
        return w

    # ═══ Tab: 外观与语音 ═══
    def _tab_appearance(self):
        w = QWidget(); layout = QVBoxLayout(w)
        grp = QGroupBox("主题"); fl = QFormLayout(grp); fl.setSpacing(10)
        self.theme_sel = QComboBox()
        self.theme_sel.addItems(["dark", "light"])
        self.theme_sel.setCurrentText(get_mode())
        t = get_token("text_secondary")
        hint = QLabel(f"切换后立即生效"); hint.setStyleSheet(f"color: {t}; font-size: 12px;")
        fl.addRow("色彩模式:", self.theme_sel)
        fl.addRow("", hint)
        layout.addWidget(grp)

        grp2 = QGroupBox("音效与语音"); fl2 = QFormLayout(grp2); fl2.setSpacing(10)
        self.sound_enabled = QCheckBox(); self.sound_enabled.setChecked(self.config.get("sound", {}).get("enabled", True))
        fl2.addRow("启用音效:", self.sound_enabled)
        self.sound_vol = QSlider(Qt.Orientation.Horizontal); self.sound_vol.setRange(0, 100)
        self.sound_vol.setValue(int(self.config.get("sound", {}).get("volume", 0.5) * 100))
        fl2.addRow("音量:", self.sound_vol)

        self.tts_enabled = QCheckBox(); self.tts_enabled.setChecked(self.config.get("voice", {}).get("enabled", False))
        fl2.addRow("TTS 语音:", self.tts_enabled)
        self.tts_voice = QComboBox()
        self.tts_voice.addItems(["zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural"])
        self.tts_voice.setCurrentText(self.config.get("voice", {}).get("voice", "zh-CN-YunxiNeural"))
        fl2.addRow("音色:", self.tts_voice)

        self.pet_name = QLineEdit(self.config.get("personality", {}).get("name", "deskagent"))
        fl2.addRow("宠物名:", self.pet_name)
        layout.addWidget(grp2)
        layout.addStretch()
        return w

    # ═══ Tab: 数据 ═══
    def _tab_data(self):
        w = QWidget(); layout = QVBoxLayout(w)
        export = QPushButton("导出所有数据"); export.clicked.connect(self._export)
        layout.addWidget(export)
        clear = QPushButton("清除所有数据")
        clear.setProperty("cssClass", "danger"); clear.clicked.connect(self._confirm_clear)
        layout.addWidget(clear)
        layout.addSpacing(10)
        priv = QLabel("你的所有数据只存储在本地。对话记录、记忆、配置均不上传任何服务器。\nAPI Key 仅用于直接调用对应服务，不经过任何中间层。")
        priv.setWordWrap(True)
        t = get_token("text_secondary")
        priv.setStyleSheet(f"color: {t}; font-size: 12px; padding: 8px 0;")
        layout.addWidget(priv)
        layout.addStretch()
        return w

    # ═══ Tab: 关于 ═══
    def _tab_about(self):
        w = QWidget(); layout = QVBoxLayout(w)
        layout.addWidget(QLabel("deskagent — 桌面 Agent"))
        layout.addWidget(QLabel("v1.0"))
        layout.addWidget(QLabel("PySide6 + DeepSeek / Gemini"))
        layout.addStretch()
        return w

    # ═══ Save ═══
    def _on_save(self):
        # Save LLM to QSettings
        from agent.llm.router import save_llm_config
        save_llm_config(self._llm_key.text(), self._llm_url.text(), self._llm_model.text())

        cfg = dict(self.config)
        cfg["proxy"]["enabled"] = self.proxy_enabled.isChecked()
        cfg["proxy"]["http"] = self.proxy_url.text()
        cfg["proxy"]["https"] = self.proxy_url.text()
        cfg["perception"]["screen_capture_interval"] = self.screen_interval.value()
        cfg["personality"]["sass_level"] = self.sass.value()
        cfg["personality"]["name"] = self.pet_name.text()
        cfg["sound"]["enabled"] = self.sound_enabled.isChecked()
        cfg["sound"]["volume"] = self.sound_vol.value() / 100.0
        cfg["voice"]["enabled"] = self.tts_enabled.isChecked()
        cfg["voice"]["voice"] = self.tts_voice.currentText()
        cfg["display"]["theme"] = self.theme_sel.currentText()

        save_config(cfg)
        if self.agent: self.agent.router.reload()
        if self.sound_manager:
            self.sound_manager.set_enabled(cfg["sound"]["enabled"])
            self.sound_manager.set_volume(cfg["sound"]["volume"])

        # Apply theme
        mode = self.theme_sel.currentText()
        from ui.theme import apply_theme
        apply_theme(mode)

        self.config_saved.emit(); self.accept()

    # ═══ Actions ═══
    def _export(self):
        from utils.config import export_data
        try:
            p = export_data(); QMessageBox.information(self, "成功", f"已导出到:\n{p}")
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def _confirm_clear(self):
        r = QMessageBox.question(self, "确认", "确定清除所有记忆和数据？\n此操作不可撤销。",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            from utils.config import clear_all_data
            clear_all_data(); QMessageBox.information(self, "完成", "所有数据已清除")
