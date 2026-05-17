import os
import struct
import wave
import math

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect, QMediaPlayer, QAudioOutput

SOUNDS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "resources", "sounds")

SOUND_SPECS = {
    "meow":           {"freq": 600, "dur": 0.3,  "kind": "meow"},
    "meow_short":     {"freq": 700, "dur": 0.2,  "kind": "meow"},
    "meow_annoyed":   {"freq": 450, "dur": 0.5,  "kind": "meow"},
    "drag":           {"freq": 200, "dur": 0.4,  "kind": "growl"},
    "yawn":           {"freq": 350, "dur": 0.7,  "kind": "yawn"},
    "purr":           {"freq": 100, "dur": 0.8,  "kind": "purr"},
    "hiss":           {"freq": 800, "dur": 0.35, "kind": "hiss"},
    "cute_meow":      {"freq": 900, "dur": 0.25, "kind": "meow"},
    "notification":   {"freq": 880, "dur": 0.3,  "kind": "meow"},
    "walk_light":     {"freq": 300, "dur": 0.15, "kind": "growl"},
}


def _generate_wav(filepath: str, freq: float, dur: float, kind: str):
    sample_rate = 22050
    n_samples = int(sample_rate * dur)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        if kind == "meow":
            env = 1.0 - (t / dur)
            f = freq + 200 * math.sin(t * 15) * env
            val = env * math.sin(2 * math.pi * f * t)
            val += 0.3 * env * math.sin(2 * math.pi * f * 1.5 * t)
        elif kind == "growl":
            env = max(0, 1.0 - t / dur)
            val = env * 0.6 * math.sin(2 * math.pi * freq * t)
            val += env * 0.4 * (2.0 * (i % 200) / 200.0 - 1.0)
        elif kind == "yawn":
            env = math.sin(math.pi * t / dur)
            f = freq + 100 * math.sin(t * 3)
            val = env * math.sin(2 * math.pi * f * t)
        elif kind == "purr":
            pulse = 0.5 + 0.5 * math.sin(2 * math.pi * 25 * t)
            val = pulse * 0.3 * math.sin(2 * math.pi * freq * t)
        elif kind == "hiss":
            env = max(0, 1.0 - t / dur) * math.sin(math.pi * t / dur)
            import random
            val = env * (random.random() * 2 - 1)
        else:
            val = math.sin(2 * math.pi * freq * t)
        val = max(-1.0, min(1.0, val))
        samples.append(int(val * 32767 * 0.6))
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with wave.open(filepath, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def ensure_sounds():
    for name, spec in SOUND_SPECS.items():
        path = os.path.join(SOUNDS_DIR, f"{name}.wav")
        if not os.path.exists(path):
            _generate_wav(path, spec["freq"], spec["dur"], spec["kind"])


class SoundManager:
    """Cat sound effect manager using QMediaPlayer for broad format support."""

    def __init__(self, enabled: bool = True, volume: float = 0.5):
        self.enabled = enabled
        self.volume = volume
        self._sounds = {}
        sound_files = {
            "meow": "meow.wav", "meow_short": "meow_short.wav",
            "meow_annoyed": "meow_annoyed.wav", "drag": "drag.wav",
            "yawn": "yawn.wav", "purr": "purr.wav",
            "hiss": "hiss.wav", "cute_meow": "cute_meow.wav",
            "notification": "notification.wav", "walk_light": "walk_light.wav",
        }
        for name, fname in sound_files.items():
            path = os.path.join(SOUNDS_DIR, fname)
            self._sounds[name] = path if os.path.exists(path) else None

        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._audio.setVolume(volume)
        self._player.setAudioOutput(self._audio)

    def set_enabled(self, enabled: bool):
        self.enabled = enabled

    def set_volume(self, volume: float):
        self.volume = volume
        self._audio.setVolume(volume)

    def play(self, sound_name: str):
        if not self.enabled:
            return
        path = self._sounds.get(sound_name)
        if path and os.path.exists(path):
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()


class TTSManager:
    """Edge-TTS text-to-speech manager."""

    def __init__(self, enabled: bool = False, voice: str = "zh-CN-YunxiNeural"):
        self.enabled = enabled
        self.voice = voice
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)

    def set_enabled(self, enabled: bool):
        self.enabled = enabled

    def set_voice(self, voice: str):
        self.voice = voice

    def speak(self, text: str):
        if not self.enabled:
            return
        try:
            import asyncio
            import edge_tts
            import tempfile
            import threading

            async def _gen():
                try:
                    communicate = edge_tts.Communicate(text, self.voice, rate="+20%")
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    tmp_path = tmp.name
                    tmp.close()
                    await communicate.save(tmp_path)
                    self.player.setSource(QUrl.fromLocalFile(tmp_path))
                    self.player.play()
                except Exception:
                    pass

            def _run():
                try:
                    asyncio.run(_gen())
                except Exception:
                    pass

            threading.Thread(target=_run, daemon=True).start()
        except Exception:
            pass
