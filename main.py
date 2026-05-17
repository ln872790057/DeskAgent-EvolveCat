import sys
import signal

from PySide6.QtCore import Qt, QTimer as QtTimer
from PySide6.QtWidgets import QApplication

from utils.config import get_config, is_first_run
from utils.logger import get_logger
from agent.pet_agent import PetAgent
from ui.pet_window import PetWindow
from ui.pet_animator import PetAnimator
from ui.tray_icon import TrayManager
from action.voice import SoundManager, TTSManager, ensure_sounds
from perception.scheduler import ProactiveScheduler
from perception.screen import ScreenPerceiver
from perception.clipboard import ClipboardMonitor
from perception.window_monitor import WindowMonitor


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName("deskagent")
    app.setQuitOnLastWindowClosed(False)

    config = get_config()
    logger = get_logger()

    # Apply dual theme system (Light/Dark)
    from ui.theme import apply_theme
    theme_mode = config.get("display", {}).get("theme", "dark")
    apply_theme(theme_mode)
    logger.info("deskagent starting...")

    # ── Create Agent + TaskManager ──
    agent = PetAgent(config)
    from agent.task_manager import TaskManager
    task_mgr = TaskManager(agent)

    # ── DreamWorker (memory maintenance, runs in background) ──
    from agent.memory import file_store as memory_files
    from agent.memory.dream import DreamWorker
    dream_worker = DreamWorker(
        memory_store=agent.memory,
        file_store=memory_files,
        llm_client=agent.router.get_client(),
        agent=agent,
    )
    agent.set_dream_worker(dream_worker)

    # ── Scheduled Task Manager ──
    from agent.scheduled_task_manager import ScheduledTaskManager, set_scheduled_task_manager_instance
    scheduled_task_mgr = None  # created after pet is available

    # ── Sound Manager ──
    sound_enabled = config.get("sound", {}).get("enabled", True)
    sound_volume = config.get("sound", {}).get("volume", 0.5)
    sound_manager = SoundManager(enabled=sound_enabled, volume=sound_volume)

    # ── TTS Manager ──
    tts_enabled = config.get("voice", {}).get("enabled", False)
    tts_voice = config.get("voice", {}).get("voice", "zh-CN-YunxiNeural")
    tts_manager = TTSManager(enabled=tts_enabled, voice=tts_voice)

    # ── Create Pet Window ──
    monitor_index = config.get("display", {}).get("monitor", 0)
    pet = PetWindow(monitor_index=monitor_index)
    pet.set_agent(agent)
    pet.set_sound_manager(sound_manager)
    pet.task_mgr = task_mgr

    # ── Scheduled Task Manager (needs pet for bubble notifications) ──
    scheduled_task_mgr = ScheduledTaskManager(task_mgr, pet)
    set_scheduled_task_manager_instance(scheduled_task_mgr)
    pet._scheduled_task_mgr = scheduled_task_mgr

    def on_scheduled_task_fired(task_id, content):
        pet.show_bubble(f"定时任务：{content[:30]}")
    scheduled_task_mgr.task_fired.connect(on_scheduled_task_fired)

    # ── DreamWorker signals ──
    dream_worker.dream_started.connect(lambda: animator.set_emotion("sleep"))
    dream_worker.dream_finished.connect(lambda: animator.set_emotion("idle"))

    # ── File drop → start chat about file content ──
    def on_file_dropped(path, content):
        pet.show_bubble(f"读取: {path.split('/')[-1][:20]}")
        # Trigger agent to process file content
        agent.handle_perception("clipboard", content)
    pet.file_dropped.connect(on_file_dropped)

    # ── Create Animator ──
    animator = PetAnimator(pet)

    # ── Connect signals ──
    pet.drag_started.connect(animator.mark_interaction)
    pet.drag_ended.connect(animator.mark_interaction)

    # Single click → open chat (skip if sleeping — PetWindow handles wake-up internally)
    def on_click():
        if pet._st != "sleeping":
            pet._open_chat_window()
    pet.clicked.connect(on_click)

    # Forward chat emotion requests to animator
    pet.request_emotion.connect(animator.set_emotion)

    # Sync animator emotions with pet visual
    _prev_emotion = ["idle"]

    def on_anim_emotion(emotion):
        prev = _prev_emotion[0]
        pet.set_emotion(emotion)
        # Wake-up sound
        if prev == "sleep" and emotion == "idle":
            sound_manager.play("yawn")
        # Happy sounds
        if emotion == "happy":
            sound_manager.play("cute_meow")
        # Hiss on angry
        if emotion == "angry":
            sound_manager.play("hiss")
        # Walk
        if emotion == "walk":
            sound_manager.play("walk_light")
        _prev_emotion[0] = emotion

    animator.emotion_changed.connect(on_anim_emotion)

    # ── Create Scheduler (proactive talk + focus mode) ──
    scheduler = ProactiveScheduler(pet, config)

    def on_proactive_talk(text):
        pet.show_bubble(text)
        animator.set_emotion("talk")
        QtTimer.singleShot(10000, lambda: (
            animator.set_emotion("idle") if animator.emotion == "talk" else None
        ))

    scheduler.talk_triggered.connect(on_proactive_talk)
    scheduler.focus_entered.connect(lambda: (
        pet.enter_focus_mode(),
        animator.set_emotion("sleep"),
    ))
    scheduler.focus_exited.connect(pet.exit_focus_mode)

    # Mark user activity on interaction
    pet.clicked.connect(lambda: scheduler.mark_user_active())
    pet.drag_started.connect(lambda: scheduler.mark_user_active())

    # ── Perception threads ──
    import time as _time
    _perception_cooldowns = {"摸鱼": 0, "代码": 0}

    def _perception_talk(text: str, tag: str, cooldown: int = 1800):
        now = _time.time()
        if now - _perception_cooldowns.get(tag, 0) < cooldown:
            return
        _perception_cooldowns[tag] = now
        pet.show_bubble(text)
        animator.set_emotion("talk")
        QtTimer.singleShot(10000, lambda: (
            animator.set_emotion("idle") if animator.emotion == "talk" else None
        ))

    # Screen perceiver
    screen_cfg = config.get("perception", {})
    screen_interval = screen_cfg.get("screen_capture_interval", 300)
    vision_client = agent.router.get_client()
    if vision_client:
        screen_perceiver = ScreenPerceiver(vision_client, interval=screen_interval)
        screen_perceiver.screen_understood.connect(
            lambda s: agent.handle_perception("screen", s)
        )
        screen_perceiver.start()

    # Clipboard monitor
    clip_interval = screen_cfg.get("clipboard_poll_interval", 2)
    clipboard_monitor = ClipboardMonitor(interval=clip_interval)
    def on_clipboard(text):
        talk = agent.handle_perception("clipboard", text)
        if talk:
            _perception_talk(talk, "代码", cooldown=1800)
    clipboard_monitor.clipboard_changed.connect(on_clipboard)
    clipboard_monitor.start()

    # Window monitor
    win_interval = screen_cfg.get("window_check_interval", 30)
    window_monitor = WindowMonitor(interval=win_interval)
    def on_window(title, tag):
        agent.handle_perception("window", title)
        if tag == "摸鱼":
            _perception_talk("哟，又来摸鱼了？你的KPI还好吗？", "摸鱼", cooldown=1800)
        elif tag == "找工作":
            pet.show_bubble("找工作呢？加油...虽然我不一定希望你走🐱")
        elif tag == "打游戏":
            _perception_talk("打游戏呢？注意休息，眼睛不累我都累了", "摸鱼", cooldown=1800)
    window_monitor.window_changed.connect(on_window)
    window_monitor.permission_denied.connect(
        lambda: pet.show_bubble("我看不清窗口了...去系统设置给我开个权限？")
    )
    # User idle → trigger dream check
    if hasattr(window_monitor, 'user_idle'):
        window_monitor.user_idle.connect(lambda idle: (
            dream_worker.on_user_leave() if idle else dream_worker.on_user_return()
        ))
    window_monitor.start()

    # ── Create Tray ──
    tray = TrayManager(pet)

    # ── Override close to minimize to tray ──
    def close_to_tray(event):
        event.ignore()
        pet.hide()
    pet.closeEvent = close_to_tray

    # ── Settings window ──
    def open_settings():
        from ui.settings_window import SettingsWindow
        dlg = SettingsWindow(agent=agent, sound_manager=sound_manager, parent=None)
        dlg.config_saved.connect(lambda: (
            agent.router.reload(),
            sound_manager.set_enabled(get_config().get("sound", {}).get("enabled", True)),
            sound_manager.set_volume(get_config().get("sound", {}).get("volume", 0.5)),
            tts_manager.set_enabled(get_config().get("voice", {}).get("enabled", False)),
            tts_manager.set_voice(get_config().get("voice", {}).get("voice", "zh-CN-YunxiNeural")),
        ))
        dlg.exec()

    tray.set_settings_callback(open_settings)

    # ── TTS speak on chat complete ──
    def on_chat_tts(emotion):
        if tts_manager.enabled and emotion != "idle":
            try:
                bubble = pet.chat_window._last_cat_bubble if pet.chat_window else None
                if bubble:
                    tts_manager.speak(bubble._full_text[:200])
            except Exception:
                pass

    pet.request_emotion.connect(on_chat_tts)

    # ── Cold start check ──
    if is_first_run():
        pet._open_chat_window()
        from ui.onboarding_dialog import OnboardingManager
        obm = OnboardingManager(pet.chat_window, pet)
        QtTimer.singleShot(500, obm.start)

    # ── Show pet ──
    pet.show()

    logger.info("deskagent started successfully")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
