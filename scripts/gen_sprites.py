"""Generate placeholder cat PNG sprites for all 8 states × 3 layers + shadows."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import (
    QPainter, QPixmap, QColor, QPen, QBrush, QFont, QPainterPath, QImage,
)
from PySide6.QtCore import Qt, QPoint

CAT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "resources", "cat")

BODY_COLOR = QColor(255, 180, 100)
BODY_DARK = QColor(230, 150, 70)
OUTLINE = QColor(80, 50, 20)
INNER_EAR = QColor(255, 160, 140)
NOSE_COLOR = QColor(255, 140, 140)
EYE_WHITE = QColor(255, 255, 255)
PUPIL = QColor(30, 20, 10)


def make_pixmap(w, h):
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def draw_body(painter, state, w=200, h=200):
    """Draw cat body (head + torso + ears + paws + tail)."""
    cx, cy = w // 2, h // 2 - 15

    if state == "sleeping":
        cy += 20
    if state == "happy":
        cy -= 5

    painter.setPen(QPen(OUTLINE, 2))
    painter.setBrush(QBrush(BODY_COLOR))

    # Torso
    if state == "sleeping":
        painter.drawEllipse(int(cx - 35), int(cy + 15), 70, 35)
    else:
        painter.drawEllipse(int(cx - 28), int(cy + 20), 56, 48)

    # Head
    head_r = 36
    if state == "curious":
        cx += 5
    painter.drawEllipse(int(cx - head_r), int(cy - head_r), head_r * 2, head_r * 2)

    # Ears
    draw_ear(painter, cx - 24, cy - 24, cx - 38, cy - 48, cx - 10, cy - 30)
    draw_ear(painter, cx + 24, cy - 24, cx + 38, cy - 48, cx + 10, cy - 30)

    # Paws
    if state != "sleeping":
        painter.setPen(QPen(OUTLINE, 1.5))
        painter.setBrush(QBrush(BODY_COLOR))
        painter.drawEllipse(int(cx - 16), int(cy + 55), 18, 12)
        painter.drawEllipse(int(cx + 2), int(cy + 55), 18, 12)

    # Tail
    tail_path = QPainterPath()
    tx, ty = cx - 25, cy + 40
    tail_path.moveTo(tx, ty)
    if state == "happy":
        tail_path.cubicTo(tx - 20, ty - 30, tx - 40, ty - 50, tx - 35, ty - 55)
    elif state == "annoyed":
        tail_path.cubicTo(tx, ty - 35, tx + 20, ty - 55, tx + 5, ty - 60)
    else:
        tail_path.cubicTo(tx - 30, ty, tx - 50, ty - 20, tx - 40, ty - 35)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(OUTLINE, 3))
    painter.drawPath(tail_path)

    # Walking: tilted body
    if state == "walking":
        pass  # tilt handled by animation

    # Nose
    painter.setPen(QPen(OUTLINE, 1.5))
    painter.setBrush(QBrush(NOSE_COLOR))
    ny = cy + 8
    painter.drawPolygon([QPoint(int(cx), int(ny + 4)), QPoint(int(cx - 4), int(ny - 2)), QPoint(int(cx + 4), int(ny - 2))])

    # Mouth
    painter.setPen(QPen(OUTLINE, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    my = ny + 6
    if state == "talking":
        painter.setBrush(QBrush(QColor(60, 30, 30)))
        painter.drawEllipse(int(cx - 5), int(my), 10, 8)
    elif state == "happy":
        painter.drawArc(int(cx - 10), int(my - 5), 20, 14, 0, 180 * 16)
    elif state == "annoyed":
        painter.drawArc(int(cx - 8), int(my + 4), 16, 12, 180 * 16, 180 * 16)
    elif state == "sleeping":
        painter.drawEllipse(int(cx - 3), int(my), 6, 4)
    else:
        painter.drawArc(int(cx - 6), int(my - 2), 12, 8, 0, 180 * 16)

    # Whiskers
    painter.setPen(QPen(OUTLINE, 1))
    wy = cy + 5
    painter.drawLine(int(cx - 55), int(wy - 4), int(cx - 30), int(wy))
    painter.drawLine(int(cx - 55), int(wy + 3), int(cx - 30), int(wy + 3))
    painter.drawLine(int(cx + 55), int(wy - 4), int(cx + 30), int(wy))
    painter.drawLine(int(cx + 55), int(wy + 3), int(cx + 30), int(wy + 3))


def draw_ear(painter, x1, y1, x2, y2, x3, y3):
    path = QPainterPath()
    path.moveTo(x1, y1)
    path.lineTo(x2, y2)
    path.lineTo(x3, y3)
    path.closeSubpath()
    painter.setPen(QPen(OUTLINE, 2))
    painter.setBrush(QBrush(BODY_COLOR))
    painter.drawPath(path)
    # Inner
    mx, my = (x1 + x2 + x3) / 3, (y1 + y2 + y3) / 3
    inner = QPainterPath()
    inner.moveTo(x1 + (x2 - x1) * 0.3, y1 + (y2 - y1) * 0.3)
    inner.lineTo(x2 + (x1 - x2) * 0.2, y2 + (y1 - y2) * 0.2)
    inner.lineTo(x3 + (x1 - x3) * 0.1, y3 + (y1 - y3) * 0.1)
    inner.closeSubpath()
    painter.setBrush(QBrush(INNER_EAR))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(inner)


def draw_eyes(painter, state, w=80, h=40):
    """Draw eyes layer. cx relative to body which is at ~100,~85 center."""
    painter.setPen(Qt.PenStyle.NoPen)
    le_x, re_x = 38, 58  # left/right eye positions within 80px
    ey = 15

    if state == "sleeping":
        painter.setPen(QPen(OUTLINE, 2))
        painter.drawArc(le_x - 8, ey - 2, 16, 10, 0, 180 * 16)
        painter.drawArc(re_x - 8, ey - 2, 16, 10, 0, 180 * 16)
    elif state == "happy":
        painter.setPen(QPen(OUTLINE, 2))
        painter.drawArc(le_x - 8, ey - 6, 16, 12, 180 * 16, 180 * 16)
        painter.drawArc(re_x - 8, ey - 6, 16, 12, 180 * 16, 180 * 16)
    elif state == "annoyed":
        painter.setPen(QPen(OUTLINE, 2))
        painter.setBrush(QBrush(EYE_WHITE))
        painter.drawEllipse(le_x - 8, ey - 6, 16, 14)
        painter.drawEllipse(re_x - 8, ey - 6, 16, 14)
        painter.setBrush(QBrush(PUPIL))
        painter.drawEllipse(le_x - 2, ey - 2, 6, 6)
        painter.drawEllipse(re_x - 2, ey - 2, 6, 6)
        # Angry brows
        painter.setPen(QPen(OUTLINE, 2.5))
        painter.drawLine(le_x - 9, ey - 10, le_x + 5, ey - 5)
        painter.drawLine(re_x + 9, ey - 10, re_x - 5, ey - 5)
    elif state == "sick":
        painter.setPen(QPen(QColor(140, 200, 140), 2))
        painter.drawLine(le_x - 5, ey - 3, le_x + 5, ey + 3)
        painter.drawLine(le_x + 5, ey - 3, le_x - 5, ey + 3)
        painter.drawLine(re_x - 5, ey - 3, re_x + 5, ey + 3)
        painter.drawLine(re_x + 5, ey - 3, re_x - 5, ey + 3)
    elif state == "curious":
        painter.setBrush(QBrush(EYE_WHITE))
        painter.drawEllipse(le_x - 9, ey - 8, 18, 18)
        painter.drawEllipse(re_x - 9, ey - 8, 18, 18)
        painter.setBrush(QBrush(PUPIL))
        painter.drawEllipse(le_x - 1, ey - 1, 8, 8)
        painter.drawEllipse(re_x - 1, ey - 1, 8, 8)
    else:
        # idle / talking / walking: normal eyes
        painter.setPen(QPen(OUTLINE, 1.5))
        painter.setBrush(QBrush(EYE_WHITE))
        painter.drawEllipse(le_x - 8, ey - 6, 16, 14)
        painter.drawEllipse(re_x - 8, ey - 6, 16, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(PUPIL))
        painter.drawEllipse(le_x - 1, ey - 1, 7, 7)
        painter.drawEllipse(re_x - 1, ey - 1, 7, 7)


def draw_effects(painter, state, w=200, h=200):
    """Draw effects layer (ZZZ, hearts, steam, etc.)."""
    cx, cy = w // 2, h // 2 - 15

    if state == "sleeping":
        font = QFont("Arial", 10, QFont.Weight.Bold)
        painter.setFont(font)
        for i, char in enumerate(["z", "z", "Z"]):
            alpha = 255 - i * 50
            painter.setPen(QPen(QColor(100, 100, 200, alpha)))
            painter.drawText(int(cx + 30 + i * 8), int(cy - 55 + i * 8), char)

    elif state == "happy":
        painter.setPen(QPen(QColor(255, 100, 130, 180), 2))
        for i in range(3):
            hx = int(cx + 20 + i * 12 - 12)
            hy = int(cy - 50 - i * 5)
            painter.drawText(hx, hy, "♥")

    elif state == "annoyed":
        painter.setPen(QPen(QColor(200, 100, 100), 2))
        for i in range(3):
            painter.drawText(int(cx + 20), int(cy - 50 + i * 10), "#")

    elif state == "talking":
        painter.setPen(QPen(QColor(255, 255, 255, 60), 1.5))
        for i in range(3):
            r = 15 + i * 10
            painter.drawEllipse(int(cx - r), int(cy - 42 - r), r * 2, r * 2)

    elif state == "sick":
        painter.setPen(QPen(QColor(140, 200, 140, 160), 2))
        for i in range(5):
            a = i * 1.2
            r = 5 + i * 3
            px = int(cx + r * math.cos(a))
            py = int(cy - 55 + r * math.sin(a))
            painter.drawEllipse(px - 1, py - 1, 2, 2)

    elif state == "curious":
        font = QFont("Arial", 12, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QPen(QColor(255, 200, 100)))
        painter.drawText(int(cx + 30), int(cy - 45), "?")

    elif state == "walking":
        painter.setPen(QPen(QColor(180, 160, 140, 80), 1))
        for i in range(3):
            painter.drawEllipse(int(cx - 15 + i * 8), int(cy + 50), 3, 2)


def draw_shadow(painter, variant, w=160, h=40):
    """Draw shadow ellipse."""
    painter.setPen(Qt.PenStyle.NoPen)
    if variant == "normal":
        painter.setBrush(QBrush(QColor(0, 0, 0, 40)))
        painter.drawEllipse(10, 5, 140, 20)
    elif variant == "jump":
        painter.setBrush(QBrush(QColor(0, 0, 0, 15)))
        painter.drawEllipse(20, 10, 80, 10)
    elif variant == "land":
        painter.setBrush(QBrush(QColor(0, 0, 0, 60)))
        painter.drawEllipse(5, 2, 170, 30)


def gen_all():
    os.makedirs(CAT_DIR, exist_ok=True)
    states = ["idle", "talking", "sleeping", "walking", "annoyed", "sick", "happy", "curious"]

    # Shadow variants
    shadow_specs = {"shadow_normal": (160, 40, "normal"), "shadow_jump": (120, 30, "jump"), "shadow_land": (180, 50, "land")}
    for name, (sw, sh, variant) in shadow_specs.items():
        pm = make_pixmap(sw, sh)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_shadow(p, variant, sw, sh)
        p.end()
        pm.save(os.path.join(CAT_DIR, f"{name}.png"), "PNG")
        print(f"  {name}.png ({sw}x{sh})")

    # State layers
    for state in states:
        # Body (200x200)
        pm = make_pixmap(200, 200)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_body(p, state)
        p.end()
        pm.save(os.path.join(CAT_DIR, f"{state}_body.png"), "PNG")

        # Eyes (80x40)
        pm = make_pixmap(80, 40)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_eyes(p, state)
        p.end()
        pm.save(os.path.join(CAT_DIR, f"{state}_eyes.png"), "PNG")

        # Effects (200x200)
        pm = make_pixmap(200, 200)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_effects(p, state)
        p.end()
        pm.save(os.path.join(CAT_DIR, f"{state}_effects.png"), "PNG")

        print(f"  {state}: body + eyes + effects")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gen_all()
    print("All 27 PNG sprites generated!")
    app.quit()
