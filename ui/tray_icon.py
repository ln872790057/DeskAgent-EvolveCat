from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication


def _create_tray_icon_pixmap() -> QPixmap:
    """Draw a small cat icon for the system tray."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx, cy = 32, 28

    # Body
    painter.setPen(QPen(QColor(80, 50, 20), 2))
    painter.setBrush(QBrush(QColor(255, 180, 100)))
    painter.drawEllipse(int(cx - 22), int(cy + 10), 44, 36)

    # Head
    painter.drawEllipse(int(cx - 24), int(cy - 24), 48, 48)

    # Ears
    painter.setPen(QPen(QColor(80, 50, 20), 2))
    painter.setBrush(QBrush(QColor(255, 180, 100)))
    painter.drawPolygon([QPoint(cx - 18, cy - 20), QPoint(cx - 30, cy - 40), QPoint(cx - 8, cy - 24)])
    painter.drawPolygon([QPoint(cx + 18, cy - 20), QPoint(cx + 30, cy - 40), QPoint(cx + 8, cy - 24)])

    # Eyes
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.drawEllipse(int(cx - 16), int(cy - 10), 14, 12)
    painter.drawEllipse(int(cx + 4), int(cy - 10), 14, 12)
    painter.setBrush(QBrush(QColor(30, 20, 10)))
    painter.drawEllipse(int(cx - 12), int(cy - 7), 6, 6)
    painter.drawEllipse(int(cx + 8), int(cy - 7), 6, 6)

    # Nose
    painter.setBrush(QBrush(QColor(255, 140, 140)))
    painter.drawPolygon([QPoint(cx, cy + 4), QPoint(cx - 3, cy - 1), QPoint(cx + 3, cy - 1)])

    painter.end()
    return pixmap


class TrayManager:
    """Manages system tray icon and menu."""

    def __init__(self, pet_window):
        self.pet = pet_window
        self.tray = QSystemTrayIcon()
        icon = QIcon(_create_tray_icon_pixmap())
        self.tray.setIcon(icon)
        self.tray.setToolTip("deskagent")

        self._settings_callback = None

        menu = QMenu()
        menu.setObjectName("tray_menu")
        show_action = menu.addAction("&显示宠物")
        show_action.triggered.connect(self.show_pet)
        menu.addSeparator()
        self.settings_action = menu.addAction("&设置")
        self.settings_action.triggered.connect(self._open_settings)
        menu.addSeparator()
        quit_action = menu.addAction("&退出")
        quit_action.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def set_settings_callback(self, callback):
        self._settings_callback = callback

    def _open_settings(self):
        if self._settings_callback:
            self._settings_callback()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_pet()

    def show_pet(self):
        self.pet.show()
        self.pet.raise_()
        self.pet.activateWindow()

    def quit_app(self):
        self.tray.hide()
        QApplication.quit()
