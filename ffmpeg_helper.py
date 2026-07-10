"""
ffmpeg_helper.py - FFmpeg 下載與管理工具

提供自動下載、安裝驗證、路徑配置等功能。
支援從官方源頭下載靜態編譯的 FFmpeg。
"""

from __future__ import annotations

import os
import sys
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Callable
import urllib.request
import urllib.error

from logger import get_logger

logger = get_logger()

# FFmpeg 下載來源（使用 GitHub mirror）
FFMPEG_URLS = {
    "windows": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
}

# 預設安裝位置
FFMPEG_INSTALL_DIR = Path(__file__).parent / "ffmpeg"
FFMPEG_EXE = FFMPEG_INSTALL_DIR / "bin" / "ffmpeg.exe"


class FFmpegDownloader:
    """FFmpeg 下載器"""
    
    def __init__(self, install_dir: Optional[Path] = None):
        self.install_dir = install_dir or FFMPEG_INSTALL_DIR
        self.progress_callback: Optional[Callable[[int, int], None]] = None
    
    def set_progress_callback(self, callback: Callable[[int, int], None]):
        """設定下載進度回調函式 callback(downloaded, total)"""
        self.progress_callback = callback
    
    def _report_progress(self, downloaded: int, total: int):
        """報告下載進度"""
        if self.progress_callback:
            try:
                self.progress_callback(downloaded, total)
            except Exception as e:
                logger.debug(f"進度回調失敗：{e}")
    
    def is_installed(self) -> bool:
        """檢查 FFmpeg 是否已安裝"""
        return FFMPEG_EXE.exists()
    
    def get_version(self) -> Optional[str]:
        """取得 FFmpeg 版本資訊"""
        if not self.is_installed():
            return None
        
        try:
            import subprocess
            result = subprocess.run(
                [str(FFMPEG_EXE), "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            if result.returncode == 0:
                # 回傳第一行
                return result.stdout.split('\n')[0]
        except Exception as e:
            logger.error(f"取得 FFmpeg 版本失敗：{e}")
        
        return None
    
    def download(self, force: bool = False) -> bool:
        """
        下載並安裝 FFmpeg
        
        Args:
            force: 強制重新下載
            
        Returns:
            bool: 是否成功
        """
        if self.is_installed() and not force:
            logger.info("FFmpeg 已安裝")
            return True
        
        try:
            url = FFMPEG_URLS.get(sys.platform)
            if not url:
                logger.error(f"不支援的平台：{sys.platform}")
                return False
            
            logger.info(f"開始下載 FFmpeg: {url}")
            
            # 建立臨時檔案
            temp_fd, temp_path = tempfile.mkstemp(suffix=".zip")
            os.close(temp_fd)
            
            try:
                # 下載檔案
                self._download_file(url, temp_path)
                
                # 解壓縮
                logger.info("解壓縮中...")
                self._extract_and_install(temp_path)
                
                # 驗證安裝
                if self.is_installed():
                    version = self.get_version()
                    logger.info(f"FFmpeg 安裝成功：{version}")
                    return True
                else:
                    logger.error("FFmpeg 安裝驗證失敗")
                    return False
                    
            finally:
                # 清理臨時檔案
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                        
        except Exception as e:
            logger.error(f"FFmpeg 下載失敗：{e}", exc_info=True)
            return False
    
    def _download_file(self, url: str, dest: str):
        """下載檔案並回報進度"""
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (SAI2 DrawCompanion)'}
            )
            
            with urllib.request.urlopen(req, timeout=300) as response:
                total = int(response.getheader('Content-Length', 0))
                downloaded = 0
                
                with open(dest, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        
                        downloaded += len(chunk)
                        f.write(chunk)
                        self._report_progress(downloaded, total)
                        
        except urllib.error.URLError as e:
            raise RuntimeError(f"網路錯誤：{e.reason}")
        except Exception as e:
            raise RuntimeError(f"下載失敗：{e}")
    
    def _extract_and_install(self, zip_path: str):
        """解壓縮並安裝到目標目錄"""
        # 建立安裝目錄
        self.install_dir.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # 找到包含 bin 的根目錄
            root_dir = None
            for name in zf.namelist():
                if name.endswith('bin/ffmpeg.exe'):
                    root_dir = name.split('bin/')[0]
                    break
            
            if not root_dir:
                # 嘗試其他結構
                for name in zf.namelist():
                    if 'bin/ffmpeg.exe' in name:
                        parts = name.split('/')
                        if len(parts) > 1:
                            root_dir = parts[0]
                            break
            
            if not root_dir:
                raise RuntimeError("無法在 ZIP 中找到 FFmpeg")
            
            logger.debug(f"找到 FFmpeg 根目錄：{root_dir}")
            
            # 解壓縮必要檔案
            for member in zf.namelist():
                if member.startswith(root_dir):
                    # 計算相對路徑
                    rel_path = member[len(root_dir):]
                    if rel_path:
                        dest_path = self.install_dir / rel_path.lstrip('/')
                        
                        # 建立目錄
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # 寫入檔案
                        if not member.endswith('/'):
                            with zf.open(member) as src:
                                with open(dest_path, 'wb') as dst:
                                    shutil.copyfileobj(src, dst)
        
        logger.info(f"FFmpeg 已安裝至：{self.install_dir}")
    
    def uninstall(self) -> bool:
        """移除已安裝的 FFmpeg"""
        try:
            if self.install_dir.exists():
                shutil.rmtree(self.install_dir)
                logger.info("FFmpeg 已移除")
                return True
            return False
        except Exception as e:
            logger.error(f"移除 FFmpeg 失敗：{e}")
            return False


def find_ffmpeg_auto() -> Optional[str]:
    """
    自動尋找 FFmpeg
    
    搜尋順序：
    1. 內建安裝目錄
    2. 系統 PATH
    3. 常見安裝位置
    
    Returns:
        FFmpeg 執行檔路徑，若找不到則回傳 None
    """
    # 1. 檢查內建安裝
    if FFMPEG_EXE.exists():
        logger.debug(f"找到內建 FFmpeg: {FFMPEG_EXE}")
        return str(FFMPEG_EXE)
    
    # 2. 檢查系統 PATH
    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    
    import shutil
    found = shutil.which(ffmpeg_name)
    if found:
        logger.debug(f"在 PATH 中找到 FFmpeg: {found}")
        return found
    
    # 3. 常見安裝位置（Windows）
    if sys.platform == "win32":
        common_paths = [
            Path(r"C:\Program Files\FFmpeg\bin\ffmpeg.exe"),
            Path(r"C:\Program Files (x86)\FFmpeg\bin\ffmpeg.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "FFmpeg" / "bin" / "ffmpeg.exe",
        ]
        
        for path in common_paths:
            if path.exists():
                logger.debug(f"在常見位置找到 FFmpeg: {path}")
                return str(path)
    
    logger.warning("未找到 FFmpeg")
    return None


def ensure_ffmpeg(
    auto_download: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> tuple[bool, Optional[str]]:
    """
    確保 FFmpeg 可用
    
    Args:
        auto_download: 若未找到是否自動下載
        progress_callback: 下載進度回調
        
    Returns:
        (success, path_or_error): 成功時回傳路徑，失敗時回傳錯誤訊息
    """
    # 嘗試尋找現有的 FFmpeg
    path = find_ffmpeg_auto()
    if path:
        return True, path
    
    # 需要下載
    if not auto_download:
        return False, "FFmpeg 未安裝，請手動安裝或啟用自動下載"
    
    # 執行下載
    downloader = FFmpegDownloader()
    if progress_callback:
        downloader.set_progress_callback(progress_callback)
    
    if downloader.download():
        return True, str(FFMPEG_EXE)
    else:
        return False, "FFmpeg 下載失敗"


# ─── CLI 介面 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="FFmpeg 管理工具")
    parser.add_argument("--install", action="store_true", help="安裝 FFmpeg")
    parser.add_argument("--uninstall", action="store_true", help="移除 FFmpeg")
    parser.add_argument("--check", action="store_true", help="檢查安裝狀態")
    parser.add_argument("--force", action="store_true", help="強制重新下載")
    
    args = parser.parse_args()
    
    downloader = FFmpegDownloader()
    
    if args.check:
        if downloader.is_installed():
            print(f"✓ FFmpeg 已安裝")
            version = downloader.get_version()
            if version:
                print(f"  版本：{version}")
            print(f"  路徑：{FFMPEG_EXE}")
        else:
            print("✗ FFmpeg 未安裝")
    
    elif args.install:
        print("正在下載 FFmpeg...")
        
        def show_progress(downloaded, total):
            if total > 0:
                pct = (downloaded / total) * 100
                bar_len = 40
                filled = int(bar_len * downloaded / total)
                bar = '█' * filled + '░' * (bar_len - filled)
                print(f"\r[{bar}] {pct:.1f}% ({downloaded/1024/1024:.1f}/{total/1024/1024:.1f} MB)", end='', flush=True)
        
        downloader.set_progress_callback(show_progress)
        
        if downloader.download(force=args.force):
            print("\n✓ 安裝成功!")
        else:
            print("\n✗ 安裝失敗")
            sys.exit(1)
    
    elif args.uninstall:
        if downloader.uninstall():
            print("✓ 已移除 FFmpeg")
        else:
            print("✗ 移除失敗")
            sys.exit(1)
    
    else:
        parser.print_help()
