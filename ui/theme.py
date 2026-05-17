"""双主题系统：Light/Dark QSS 动态注入"""
from PySide6.QtWidgets import QApplication

# ═══ 颜色令牌 ═══
TOKENS = {
    "dark": {
        "bg_primary":    "#121214",
        "bg_secondary":  "#1A1A1D",
        "bg_tertiary":   "#232328",
        "bg_hover":       "#2A2A30",
        "text_primary":  "#E4E4E7",
        "text_secondary":"#A1A1AA",
        "text_dim":       "#71717A",
        "accent":        "#3B82F6",
        "accent_hover":  "#2563EB",
        "accent_press":  "#1D4ED8",
        "border":        "#2A2A30",
        "border_light":  "rgba(255,255,255,0.06)",
        "success":       "#22C55E",
        "warning":       "#D97706",
        "danger":        "#DC2626",
        "danger_hover":  "#EF4444",
        "shadow":        "rgba(0,0,0,0.4)",
    },
    "light": {
        "bg_primary":    "#FFFFFF",
        "bg_secondary":  "#F4F4F5",
        "bg_tertiary":   "#E4E4E7",
        "text_primary":  "#18181B",
        "text_secondary":"#52525B",
        "text_dim":      "#A1A1AA",
        "accent":        "#3B82F6",
        "accent_hover":  "#2563EB",
        "accent_press":  "#1D4ED8",
        "border":        "#E4E4E7",
        "border_light":  "rgba(0,0,0,0.06)",
        "success":       "#16A34A",
        "danger":        "#EF4444",
        "danger_hover":  "#DC2626",
        "shadow":        "rgba(0,0,0,0.1)",
    },
}

_current_mode = "dark"


def get_token(key: str) -> str:
    return TOKENS.get(_current_mode, TOKENS["dark"]).get(key, "")


def get_mode() -> str:
    return _current_mode


def apply_theme(mode: str = "dark"):
    """注入全局 QSS，统一生效"""
    global _current_mode
    if mode not in TOKENS:
        mode = "dark"
    _current_mode = mode
    t = TOKENS[mode]

    qss = f"""
    /* ═══ 全局 ═══ */
    QWidget {{
        background-color: {t["bg_primary"]};
        color: {t["text_primary"]};
        font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
        font-size: 13px;
    }}

    /* ═══ QTabWidget 扁平化 ═══ */
    QTabWidget::pane {{
        border: none;
        background: {t["bg_primary"]};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {t["text_secondary"]};
        padding: 10px 20px;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: 13px;
    }}
    QTabBar::tab:selected {{
        color: {t["accent"]};
        font-weight: bold;
        border-bottom: 2px solid {t["accent"]};
    }}
    QTabBar::tab:hover {{
        color: {t["text_primary"]};
    }}

    /* ═══ QGroupBox 净化 ═══ */
    QGroupBox {{
        border: none;
        margin-top: 1ex;
        font-weight: bold;
        color: {t["text_primary"]};
        padding-top: 16px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 0px;
        padding: 0 2px;
        color: {t["text_primary"]};
        font-weight: 600;
    }}

    /* ═══ QLineEdit / QComboBox 统一 ═══ */
    QLineEdit, QComboBox {{
        min-height: 36px;
        max-height: 36px;
        border-radius: 6px;
        background-color: {t["bg_secondary"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border"]};
        padding-left: 10px;
        font-size: 13px;
    }}
    QLineEdit:focus {{
        border: 1px solid {t["accent"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 28px;
    }}

    /* ═══ QPushButton ═══ */
    QPushButton {{
        background-color: {t["bg_secondary"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border"]};
        border-radius: 8px;
        padding: 8px 20px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {t["bg_tertiary"]};
    }}
    QPushButton:pressed {{
        background-color: {t["border"]};
    }}

    /* 主按钮（强调色填充） */
    QPushButton[cssClass="primary"] {{
        background-color: {t["accent"]};
        color: #FFFFFF;
        border: none;
        font-weight: 600;
    }}
    QPushButton[cssClass="primary"]:hover {{
        background-color: {t["accent_hover"]};
    }}
    QPushButton[cssClass="primary"]:pressed {{
        background-color: {t["accent_press"]};
    }}

    /* 危险按钮 */
    QPushButton[cssClass="danger"] {{
        background-color: transparent;
        color: {t["danger"]};
        border: 1px solid {t["danger"]};
    }}
    QPushButton[cssClass="danger"]:hover {{
        background-color: {t["danger"]};
        color: #FFFFFF;
    }}

    /* ═══ QScrollBar ═══ */
    QScrollBar:vertical {{
        background: transparent; width: 6px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t["bg_tertiary"]}; border-radius: 3px; min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

    /* ═══ QSlider ═══ */
    QSlider::groove:horizontal {{
        height: 4px; background: {t["bg_secondary"]}; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px; height: 14px; margin: -5px 0;
        background: {t["accent"]}; border-radius: 7px;
    }}

    /* ═══ QCheckBox ═══ */
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border-radius: 4px;
        border: 2px solid {t["bg_tertiary"]}; background: transparent;
    }}
    QCheckBox::indicator:checked {{
        background: {t["accent"]}; border-color: {t["accent"]};
    }}

    /* ═══ QMenu ═══ */
    QMenu {{
        background-color: {t["bg_primary"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border"]};
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 28px;
        border-radius: 6px;
        color: {t["text_primary"]};
        background-color: transparent;
    }}
    QMenu::item:selected {{
        background-color: {t["accent"]};
        color: #FFFFFF;
    }}
    QMenu::separator {{
        height: 1px;
        background: {t["border"]};
        margin: 4px 8px;
    }}

    /* ═══ QToolTip ═══ */
    QToolTip {{
        background: {t["bg_secondary"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border"]};
        border-radius: 6px;
        padding: 6px 10px;
    }}
    """
    QApplication.instance().setStyleSheet(qss)
