"""
logger.py - 結構化日誌系統與錯誤處理模組

提供：
  - 結構化日誌記錄（含時間戳、層級、模組、訊息）
  - 自動日誌輪替（保留最近 7 天）
  - 例外攔截與報告生成
  - 效能監控輔助
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from logging.handlers import RotatingFileHandler
import threading


# ─── 日誌配置 ─────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent / 'logs'
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB per file
BACKUP_COUNT = 7  # 保留 7 個備份檔


class StructuredLogger:
    """結構化日誌管理器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self.logger = None
        self.log_file = None
        
    def setup(self, name: str = 'SAI2_DrawCompanion', 
              level: int = logging.INFO,
              console_output: bool = False) -> logging.Logger:
        """
        初始化日誌系統
        
        Args:
            name: 日誌名稱
            level: 日誌層級 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            console_output: 是否同時輸出到控制台
        
        Returns:
            配置完成的 logger 實例
        """
        # 確保日誌目錄存在
        LOG_DIR.mkdir(exist_ok=True)
        
        # 清理舊日誌（超過 7 天）
        self._cleanup_old_logs()
        
        # 建立 logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        
        # 清除現有的 handlers（避免重複）
        self.logger.handlers.clear()
        
        # 建立格式化器
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        
        # 檔案處理器（使用輪替）
        log_file = LOG_DIR / f'{name}.log'
        self.log_file = str(log_file)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # 可選的控制台輸出（除錯用）
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        
        self.info(f"日誌系統已啟動 - {name}")
        self.info(f"Python 版本：{sys.version}")
        self.info(f"工作目錄：{os.getcwd()}")
        
        return self.logger
    
    def _cleanup_old_logs(self):
        """清理超過 7 天的舊日誌檔"""
        if not LOG_DIR.exists():
            return
        
        cutoff = datetime.now() - timedelta(days=BACKUP_COUNT)
        
        for log_file in LOG_DIR.glob('*.log'):
            try:
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if mtime < cutoff:
                    log_file.unlink()
                    self.logger and self.logger.debug(f"已刪除舊日誌：{log_file}")
            except Exception:
                pass
    
    def debug(self, msg: str, **kwargs):
        self.logger and self.logger.debug(msg, **kwargs)
    
    def info(self, msg: str, **kwargs):
        self.logger and self.logger.info(msg, **kwargs)
    
    def warning(self, msg: str, **kwargs):
        self.logger and self.logger.warning(msg, **kwargs)
    
    def error(self, msg: str, exc_info: bool = False, **kwargs):
        self.logger and self.logger.error(msg, exc_info=exc_info, **kwargs)
    
    def critical(self, msg: str, exc_info: bool = False, **kwargs):
        self.logger and self.logger.critical(msg, exc_info=exc_info, **kwargs)
    
    def exception(self, msg: str, **kwargs):
        """記錄例外並附上堆疊追蹤"""
        self.logger and self.logger.exception(msg, **kwargs)
    
    def get_log_file_path(self) -> str | None:
        """取得目前日誌檔路徑"""
        return self.log_file


# ─── 全域例外處理器 ───────────────────────────────────────────────────────

def install_exception_hook(logger: logging.Logger | None = None):
    """
    安裝全域例外攔截器，捕捉未處理的例外
    
    Args:
        logger: 要使用的 logger，若為 None 則使用預設 logger
    """
    log = logger or StructuredLogger().logger
    
    def excepthook(exc_type, exc_value, exc_traceback):
        # 忽略 KeyboardInterrupt（使用者主動中斷）
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        # 記錄完整例外資訊
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        tb_str = ''.join(tb_lines)
        
        if log:
            log.critical("未處理的例外發生:\n%s", tb_str)
        else:
            # 若 logger 尚未初始化，寫入 stderr
            print(f"CRITICAL ERROR:\n{tb_str}", file=sys.stderr)
        
        # 可選：產生錯誤報告檔
        _generate_crash_report(exc_type, exc_value, tb_str)
    
    sys.excepthook = excepthook


def _generate_crash_report(exc_type, exc_value, tb_str):
    """產生崩潰報告檔"""
    try:
        report_file = LOG_DIR / f'crash_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("SAI2 DrawCompanion 崩潰報告\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"時間：{datetime.now().isoformat()}\n")
            f.write(f"Python 版本：{sys.version}\n")
            f.write(f"平台：{sys.platform}\n")
            f.write(f"例外類型：{exc_type.__name__}\n")
            f.write(f"例外訊息：{exc_value}\n\n")
            f.write("堆疊追蹤:\n")
            f.write("-" * 40 + "\n")
            f.write(tb_str)
        
        if StructuredLogger().logger:
            StructuredLogger().logger.info(f"崩潰報告已儲存：{report_file}")
    except Exception:
        pass


# ─── 便捷函式 ─────────────────────────────────────────────────────────────

def get_logger() -> logging.Logger:
    """取得全域 logger 實例"""
    sl = StructuredLogger()
    if sl.logger is None:
        sl.setup()
    return sl.logger


def log_function_call(logger: logging.Logger | None = None):
    """
    裝飾器：記錄函式呼叫與執行時間
    
    Usage:
        @log_function_call()
        def my_function():
            pass
    """
    def decorator(func):
        import functools
        import time
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            log = logger or get_logger()
            func_name = func.__name__
            
            log.debug(f">>> 進入 {func_name}")
            start = time.perf_counter()
            
            try:
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                log.debug(f"<<< 離開 {func_name} (耗時：{elapsed:.3f}s)")
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start
                log.error(f"!!! {func_name} 執行失敗 (耗時：{elapsed:.3f}s): {e}", exc_info=True)
                raise
        
        return wrapper
    return decorator


# ─── 初始化 ───────────────────────────────────────────────────────────────

# 模組載入時自動初始化（可被 main.py 覆蓋）
_default_logger = StructuredLogger()
