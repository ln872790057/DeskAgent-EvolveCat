import time
from datetime import datetime
from PySide6.QtCore import QObject, QTimer, Signal


class PetAnimator(QObject):
    """Lightweight state coordinator — most animation logic is now in PetWindow."""

    emotion_changed = Signal(str)

    def __init__(self, pet_window):
        super().__init__()
        self.pet = pet_window
        self._emotion = "idle"
        self._li = time.time()

        self._idle_t = QTimer(self)
        self._idle_t.timeout.connect(self._tick)
        self._idle_t.start(1000)

        self._restore_t = QTimer(self)
        self._restore_t.setSingleShot(True)
        self._restore_t.timeout.connect(lambda: self.set_emotion("idle"))

    @property
    def emotion(self): return self._emotion

    def set_emotion(self, emotion: str):
        self._emotion = emotion
        self._restore_t.stop()
        self.pet.set_state(emotion)
        if emotion == "talk":
            self._restore_t.start(10000)
        self.emotion_changed.emit(emotion)

    def mark_interaction(self):
        self._li = time.time()
        if self._emotion not in ("idle","sleep"):
            self._restore_t.start(10000)

    def _tick(self):
        pass  # sleep timing now handled by PetWindow._check_sleep

    def get_idle_duration(self): return time.time() - self._li
