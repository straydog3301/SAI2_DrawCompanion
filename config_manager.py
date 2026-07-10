"""
config_manager.py - 統一設定管理模組

提供集中化的設定讀取、寫入、驗證與遷移功能。
支援設定版本控制、預設值合併、設定驗證。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional
from logger import get_logger

logger = get_logger()

# 設定檔案路徑
CONFIG_FILE = Path(__file__).parent / "config.json"
CONFIG_VERSION = 1  # 設定格式版本，用於未來遷移


# ─── 預設設定 ─────────────────────────────────────────────────────────────
DEFAULT_SETTINGS: dict[str, Any] = {
    # 基本設定
    "version": CONFIG_VERSION,
    "language": "zh_TW",
    "theme": "dark",
    "color_scheme": "purple",
    
    # 視窗設定
    "window_geometry": None,  # 視窗位置與大小
    "topmost": False,
    "mini_mode": False,
    
    # 追蹤器設定
    "tracker": {
        "auto_save_interval": 60,  # 自動儲存間隔（秒）
        "min_tracking_time": 5,    # 最小追蹤時間（秒）
        "auto_group_enabled": True,
        "group_by_folder": False,
    },
    
    # 縮時錄影設定
    "timelapse": {
        "fps": 30,
        "quality": "high",  # low, medium, high, ultra
        "capture_canvas_only": True,
        "output_format": "mp4",
        "ffmpeg_path": None,  # None 表示自動尋找
        "auto_start": False,
    },
    
    # 熱鍵設定
    "hotkeys": {
        "start_stop": "F12",
        "toggle_mini": "F11",
        "liquify_helper": "F9",
        "take_screenshot": "F10",
    },
    
    # 統計圖表設定
    "charts": {
        "default_view": "day",  # day, week, month, year
        "show_tooltips": True,
        "animation_enabled": True,
    },
    
    # 通知設定
    "notifications": {
        "enabled": True,
        "sound_enabled": False,
        "show_toast": True,
    },
    
    # 進階設定
    "advanced": {
        "debug_mode": False,
        "log_level": "INFO",  # DEBUG, INFO, WARNING, ERROR, CRITICAL
        "enable_crash_report": True,
        "check_updates": True,
    },
}


class ConfigManager:
    """
    設定管理器
    
    負責：
    - 載入/儲存設定
    - 設定驗證與修正
    - 版本遷移
    - 提供型別安全的設定存取
    """
    
    _instance: Optional["ConfigManager"] = None
    
    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._settings: dict[str, Any] = {}
        self._config_path = CONFIG_FILE
        self._load()
        self._initialized = True
        logger.info(f"設定管理器已初始化，設定檔路徑：{self._config_path}")
    
    def _load(self) -> None:
        """載入設定檔，若不存在則使用預設值"""
        if not self._config_path.exists():
            logger.info("設定檔不存在，使用預設設定")
            self._settings = self._deep_copy(DEFAULT_SETTINGS)
            self.save()
            return
        
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            
            # 版本檢查與遷移
            loaded_version = loaded.get("version", 0)
            if loaded_version < CONFIG_VERSION:
                logger.info(f"偵測到舊版設定 (v{loaded_version})，執行遷移至 v{CONFIG_VERSION}")
                loaded = self._migrate_settings(loaded, loaded_version)
            
            # 合併預設值（確保所有欄位存在）
            self._settings = self._merge_with_defaults(loaded)
            logger.info("設定載入成功")
            
        except json.JSONDecodeError as e:
            logger.error(f"設定檔 JSON 解析失敗：{e}")
            logger.warning("建立備份並使用預設設定")
            self._backup_corrupted_config()
            self._settings = self._deep_copy(DEFAULT_SETTINGS)
            self.save()
            
        except Exception as e:
            logger.error(f"載入設定時發生錯誤：{e}")
            self._settings = self._deep_copy(DEFAULT_SETTINGS)
    
    def _merge_with_defaults(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """遞迴合併載入的設定與預設值"""
        result = self._deep_copy(DEFAULT_SETTINGS)
        
        for key, value in loaded.items():
            if key not in result:
                # 未知的設定鍵，跳過但記錄日誌
                logger.debug(f"忽略未知的設定鍵：{key}")
                continue
            
            if isinstance(value, dict) and isinstance(result[key], dict):
                # 遞迴合併巢狀字典
                result[key] = self._merge_with_defaults_partial(result[key], value)
            else:
                # 基本型別直接覆蓋
                result[key] = value
        
        return result
    
    def _merge_with_defaults_partial(
        self, defaults: dict[str, Any], loaded: dict[str, Any]
    ) -> dict[str, Any]:
        """部分合併（用於巢狀字典）"""
        result = self._deep_copy(defaults)
        for key, value in loaded.items():
            if key in result:
                if isinstance(value, dict) and isinstance(result[key], dict):
                    result[key] = self._merge_with_defaults_partial(result[key], value)
                else:
                    result[key] = value
        return result
    
    def _migrate_settings(
        self, settings: dict[str, Any], from_version: int
    ) -> dict[str, Any]:
        """設定版本遷移"""
        result = self._deep_copy(settings)
        result["version"] = CONFIG_VERSION
        
        # 未來版本遷移邏輯可在此新增
        # if from_version < 1:
        #     ...
        
        logger.info(f"設定遷移完成：v{from_version} -> v{CONFIG_VERSION}")
        return result
    
    def _backup_corrupted_config(self) -> None:
        """備份損毀的設定檔"""
        backup_path = self._config_path.with_suffix(".json.bak")
        counter = 1
        while backup_path.exists():
            backup_path = self._config_path.with_name(f"config.json.bak.{counter}")
            counter += 1
        
        try:
            import shutil
            shutil.copy2(self._config_path, backup_path)
            logger.info(f"已備份損毀的設定檔至：{backup_path}")
        except Exception as e:
            logger.error(f"備份設定檔失敗：{e}")
    
    def save(self) -> bool:
        """儲存設定到檔案（原子性寫入）"""
        try:
            # 寫入臨時檔案
            temp_path = self._config_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=2)
            
            # 原子性替換
            temp_path.replace(self._config_path)
            logger.debug("設定已儲存")
            return True
            
        except Exception as e:
            logger.error(f"儲存設定失敗：{e}")
            # 清理臨時檔案
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        取得設定值
        
        支援點號分隔的路徑，例如：
        config.get("timelapse.fps") -> 30
        config.get("advanced.debug_mode") -> False
        """
        keys = key.split(".")
        value = self._settings
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> bool:
        """
        設定設定值
        
        支援點號分隔的路徑，例如：
        config.set("timelapse.fps", 60)
        """
        keys = key.split(".")
        current = self._settings
        
        # 導航到最後一層的前一層
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                logger.error(f"無效的設定路徑：{key}")
                return False
            current = current[k]
        
        # 設定最終值
        final_key = keys[-1]
        current[final_key] = value
        logger.debug(f"設定已更新：{key} = {value}")
        return self.save()
    
    def reset(self, key: Optional[str] = None) -> bool:
        """
        重設設定為預設值
        
        若未指定 key，則重設所有設定
        """
        if key is None:
            self._settings = self._deep_copy(DEFAULT_SETTINGS)
            logger.info("所有設定已重設為預設值")
        else:
            keys = key.split(".")
            current = DEFAULT_SETTINGS
            
            for k in keys[:-1]:
                if not isinstance(current, dict) or k not in current:
                    return False
                current = current[k]
            
            final_key = keys[-1]
            if final_key in current:
                self._set_nested_value(key, current[final_key])
                logger.info(f"設定已重設：{key}")
            else:
                return False
        
        return self.save()
    
    def _set_nested_value(self, key: str, value: Any) -> bool:
        """設定巢狀值"""
        keys = key.split(".")
        current = self._settings
        
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                return False
            current = current[k]
        
        current[keys[-1]] = value
        return True
    
    def get_all(self) -> dict[str, Any]:
        """取得所有設定的深拷貝"""
        return self._deep_copy(self._settings)
    
    def validate(self) -> list[str]:
        """
        驗證設定是否有效
        
        回傳：錯誤訊息列表，若為空則表示設定有效
        """
        errors = []
        
        # 驗證語言
        lang = self._settings.get("language", "")
        if lang not in ["zh_TW", "en_US", "ja_JP"]:
            errors.append(f"無效的語言設定：{lang}")
        
        # 驗證主題
        theme = self._settings.get("theme", "")
        if theme not in ["dark", "light"]:
            errors.append(f"無效的主題設定：{theme}")
        
        # 驗證 FPS
        fps = self.get("timelapse.fps", 0)
        if not (1 <= fps <= 120):
            errors.append(f"無效的 FPS 設定：{fps} (應為 1-120)")
        
        # 驗證熱鍵
        hotkeys = self._settings.get("hotkeys", {})
        seen_keys = set()
        for name, key in hotkeys.items():
            if key in seen_keys:
                errors.append(f"熱鍵衝突：{key} 被重複使用")
            seen_keys.add(key)
        
        if errors:
            for err in errors:
                logger.warning(f"設定驗證失敗：{err}")
        
        return errors
    
    @staticmethod
    def _deep_copy(obj: Any) -> Any:
        """深拷貝物件"""
        if isinstance(obj, dict):
            return {k: ConfigManager._deep_copy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [ConfigManager._deep_copy(item) for item in obj]
        else:
            return obj


# ─── 便利函式 ─────────────────────────────────────────────────────────────
def get_config() -> ConfigManager:
    """取得全域設定管理器實例"""
    return ConfigManager()


def init_config() -> ConfigManager:
    """初始化設定管理器（明確呼叫以確保初始化）"""
    return ConfigManager()


if __name__ == "__main__":
    # 測試用程式碼
    logger.info("測試設定管理器...")
    config = get_config()
    
    print("當前設定:")
    print(json.dumps(config.get_all(), indent=2, ensure_ascii=False))
    
    print("\n測試讀取:")
    print(f"  language: {config.get('language')}")
    print(f"  timelapse.fps: {config.get('timelapse.fps')}")
    print(f"  hotkeys.start_stop: {config.get('hotkeys.start_stop')}")
    
    print("\n測試寫入:")
    config.set("timelapse.fps", 60)
    print(f"  timelapse.fps 已改為：{config.get('timelapse.fps')}")
    
    print("\n驗證設定:")
    errors = config.validate()
    if errors:
        print("  驗證失敗:")
        for err in errors:
            print(f"    - {err}")
    else:
        print("  驗證通過 ✓")
