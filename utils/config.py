import json
import os
import shutil
import copy

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "config.json")
_EXAMPLE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.example.json")

_config_cache = None


def get_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if not os.path.exists(_CONFIG_PATH):
        shutil.copy(_EXAMPLE_PATH, _CONFIG_PATH)
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _config_cache = json.load(f)
    _apply_proxy(_config_cache)
    return _config_cache


def save_config(config: dict) -> None:
    global _config_cache
    _config_cache = copy.deepcopy(config)
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    _apply_proxy(config)


def reload_config() -> dict:
    global _config_cache
    _config_cache = None
    return get_config()


def is_first_run() -> bool:
    if not os.path.exists(_CONFIG_PATH):
        return True
    config = get_config()
    api_key = config.get("chat", {}).get("api_key", "")
    return api_key == "YOUR_DEEPSEEK_API_KEY"


def export_data() -> str:
    import os as _os, json as _json, shutil as _shutil
    export_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "data", "export")
    _os.makedirs(export_dir, exist_ok=True)

    # Export config (without API key)
    cfg = get_config()
    cfg_safe = dict(cfg)
    cfg_safe["chat"]["api_key"] = "***"
    cfg_safe["vision"]["api_key"] = "***"
    with open(_os.path.join(export_dir, "config_backup.json"), "w", encoding="utf-8") as f:
        _json.dump(cfg_safe, f, indent=2, ensure_ascii=False)

    # Export memories
    db_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "data", "memory.db")
    if _os.path.exists(db_path):
        _shutil.copy(db_path, _os.path.join(export_dir, "memory_backup.db"))

    return export_dir


def clear_all_data():
    import os as _os, glob as _glob
    data_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "data")
    for fname in ["memory.db", "app.log"]:
        path = _os.path.join(data_dir, fname)
        if _os.path.exists(path):
            try:
                _os.remove(path)
            except PermissionError:
                pass  # File in use, skip
    export_dir = _os.path.join(data_dir, "export")
    if _os.path.exists(export_dir):
        import shutil as _shutil
        _shutil.rmtree(export_dir)

    # Reset config but keep the file
    from utils.config import get_config, save_config
    cfg = get_config()
    cfg["chat"]["api_key"] = "YOUR_DEEPSEEK_API_KEY"
    cfg["vision"]["api_key"] = "YOUR_GEMINI_API_KEY"
    save_config(cfg)


def _apply_proxy(config: dict) -> None:
    proxy = config.get("proxy", {})
    if proxy.get("enabled", False):
        http_proxy = proxy.get("http", "")
        https_proxy = proxy.get("https", "")
        if http_proxy:
            os.environ["HTTP_PROXY"] = http_proxy
            os.environ["http_proxy"] = http_proxy
        if https_proxy:
            os.environ["HTTPS_PROXY"] = https_proxy
            os.environ["https_proxy"] = https_proxy
    else:
        for key in ["HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"]:
            os.environ.pop(key, None)
