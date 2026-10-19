import sys
import os
import re
import shutil
import signal
import json
import configparser
import platform
import subprocess
import logging
import string
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QGridLayout, QListWidget, QListWidgetItem, QLabel, 
                               QPushButton, QGroupBox, QComboBox, QLineEdit, 
                               QPlainTextEdit, QSplitter, QMessageBox, QCheckBox, 
                               QFormLayout, QFrame, QStyleFactory, QScrollArea,
                               QFileDialog, QSystemTrayIcon, QMenu, QStatusBar)
from PySide6.QtCore import Qt, QProcess, QTimer, Slot, Signal, QSize, QPropertyAnimation, QEasingCurve, QPoint, QEvent
from PySide6.QtGui import (QIcon, QAction, QColor, QPalette, QFont, QPixmap, QPainter, 
                           QLinearGradient, QKeySequence, QShortcut, QSyntaxHighlighter, 
                           QTextCharFormat)

# --- GLOBAL CONFIGURATION ---
APP_NAME = "Rclone Mount Manager"
VERSION = "1.0.5"

def get_base_dir() -> Path:
    """
    Get application portable base directory:
    - Development mode: directory of this script
    - Compiled executable (Nuitka / PyInstaller): directory of the executable
    """
    if globals().get("__compiled__", False) or getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()

REMOTES_DIR = BASE_DIR / "remotes"
CACHE_DIR   = BASE_DIR / "cache"
LOGS_DIR    = BASE_DIR / "logs"

RCLONE_EXE = "rclone.exe" if platform.system() == "Windows" else "rclone"

# --- LOGGING SETUP ---
LOGS_DIR.mkdir(parents=True, exist_ok=True)
APP_LOG = LOGS_DIR / "app.log"
LOG_MAX_SIZE = 2 * 1024 * 1024  # 2MB
LOG_BACKUP_COUNT = 6

logging.basicConfig(
    handlers=[RotatingFileHandler(APP_LOG, maxBytes=LOG_MAX_SIZE, backupCount=LOG_BACKUP_COUNT, encoding='utf-8')],
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Ensure required directories exist
for d in [REMOTES_DIR, CACHE_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- UTILITIES ---
def get_rclone_path():
    """Locate rclone binary in local folder or system PATH"""
    local_bin = BASE_DIR / RCLONE_EXE
    if local_bin.exists():
        return str(local_bin)
    return shutil.which("rclone") or RCLONE_EXE

logger.info(f"BASE_DIR = {BASE_DIR}")
logger.info(f"REMOTES_DIR = {REMOTES_DIR}")
logger.info(f"RCLONE PATH = {get_rclone_path()}")

def get_icon_path():
    """
    Resolve application icon path (compatible with PyInstaller onefile temp folder).
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = BASE_DIR
    
    icon_path = base_path / "icon.ico"
    return icon_path if icon_path.exists() else None

def get_dir_size_str(folder_path: Path) -> str:
    """Calculate formatted size of a directory on disk"""
    if not folder_path.exists():
        return "0 B"
    try:
        total = 0
        for entry in folder_path.glob("**/*"):
            if entry.is_file():
                total += entry.stat().st_size
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if total < 1024.0:
                return f"{total:.2f} {unit}"
            total /= 1024.0
        return f"{total:.2f} PB"
    except Exception:
        return "0 B"

def get_available_drive_letters():
    """Retrieve available Windows drive letters, or default list on non-Windows"""
    if platform.system() != "Windows":
        return ["Auto-assigned (*)"]
    used = set()
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                used.add(letter + ":")
            bitmask >>= 1
    except Exception:
        pass
    
    all_letters = [f"{c}:" for c in reversed(string.ascii_uppercase[3:])] # Z: down to D:
    available = [l for l in all_letters if l not in used]
    return ["Auto-assigned (*)"] + available + [l for l in all_letters if l in used]

def get_provider_info(remote_name: str, config_name: str):
    """Detect provider icon, tag, and descriptive title from remote name/config"""
    name_lower = f"{remote_name} {config_name}".lower()
    if "drive" in name_lower or "gdrive" in name_lower:
        return "☁️", "DRIVE", "Google Drive API"
    elif "dropbox" in name_lower:
        return "📦", "DROPBOX", "Dropbox API"
    elif "crypt" in name_lower:
        return "🔒", "CRYPT", "Rclone Crypt"
    elif "photo" in name_lower:
        return "🖼️", "PHOTOS", "Google Photos"
    elif "printer" in name_lower or "webdav" in name_lower:
        return "🌐", "WEBDAV", "WebDAV Storage"
    elif "onedrive" in name_lower:
        return "☁️", "ONEDRIVE", "Microsoft OneDrive"
    elif "pcloud" in name_lower:
        return "☁️", "PCLOUD", "pCloud Storage"
    elif "ftp" in name_lower:
        return "📡", "FTP", "FTP / SFTP"
    else:
        return "💾", "REMOTE", "Cloud Storage"

def create_sample_file():
    """Create _sample.properties template if missing"""
    sample_path = REMOTES_DIR / "_sample.properties"
    if not sample_path.exists():
        content = """# ============================================
# SAMPLE REMOTE CONFIGURATION
# ============================================
# Copy this file, rename it (e.g. pcloud.properties), and adjust settings.

[General]
name = Sample Remote
remote_name = remote:
mountpoint = auto
volname = MyRemoteVolume

[Rclone]
config_path = rclone.conf
extra_flags = --links

[Defaults]
vfs-cache-mode = full
vfs-cache-max-age = 30m
dir-cache-time = 1m
vfs-read-ahead = 128M
bwlimit = off
"""
        with open(sample_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info("Created sample configuration file")

# --- SYNTAX HIGHLIGHTER FOR LOG STREAM ---

class LogHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for rclone terminal log streams"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rules = []
        
        # [INFO] in Sky Blue
        info_format = QTextCharFormat()
        info_format.setForeground(QColor("#38bdf8"))
        info_format.setFontWeight(QFont.Bold)
        self.rules.append((r"\[INFO\]|INFO\s*:", info_format))
        
        # [SYSTEM], [CMD], [MOUNT] in Teal
        sys_format = QTextCharFormat()
        sys_format.setForeground(QColor("#2dd4bf"))
        sys_format.setFontWeight(QFont.Bold)
        self.rules.append((r"\[SYSTEM\]|\[CMD\]|\[MOUNT\]", sys_format))
        
        # [DEBUG] in Light Purple
        debug_format = QTextCharFormat()
        debug_format.setForeground(QColor("#a78bfa"))
        self.rules.append((r"\[DEBUG\]|DEBUG\s*:", debug_format))
        
        # [NOTICE], [WARN], [WARNING] in Amber
        warn_format = QTextCharFormat()
        warn_format.setForeground(QColor("#fbbf24"))
        warn_format.setFontWeight(QFont.Bold)
        self.rules.append((r"\[NOTICE\]|\[WARN(?:ING)?\]|NOTICE\s*:|WARN(?:ING)?\s*:", warn_format))
        
        # [ERROR], [CRITICAL] in Red
        error_format = QTextCharFormat()
        error_format.setForeground(QColor("#f87171"))
        error_format.setFontWeight(QFont.Bold)
        self.rules.append((r"\[ERROR\]|\[CRITICAL\]|ERROR\s*:", error_format))
        
        # Timestamps [HH:MM:SS] or YYYY/MM/DD HH:MM:SS in Slate
        time_format = QTextCharFormat()
        time_format.setForeground(QColor("#64748b"))
        self.rules.append((r"\[?\d{2,4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2}\]?|\[\d{2}:\d{2}:\d{2}\]", time_format))
        
        # Drive letter targets (e.g. Z:, C:)
        drive_format = QTextCharFormat()
        drive_format.setForeground(QColor("#34d399"))
        drive_format.setFontWeight(QFont.Bold)
        self.rules.append((r"\b[A-Za-z]:", drive_format))

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for match in re.finditer(pattern, text):
                start, end = match.span()
                self.setFormat(start, end - start, fmt)

# --- CONTROLLER LOGIC ---

class RemoteController:
    """Manages state, configuration, and QProcess execution for a single remote"""
    
    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.config_id = config_file.stem
        self.process = None
        self.is_running = False
        self.mount_timestamp = None
        self.error_message = ""
        
        # Load static configuration
        self.cfg = configparser.ConfigParser()
        self.cfg.read(config_file, encoding='utf-8')
        
        # Dedicated directories for this remote
        self.remote_cache = CACHE_DIR / self.config_id
        self.remote_log_dir = LOGS_DIR / self.config_id
        self.log_file = self.remote_log_dir / "rclone.log"
        
        # Load persisted overrides
        self.overrides_file = REMOTES_DIR / f"{self.config_id}.override.json"
        self.runtime_params = self._load_defaults()
        
        logger.info(f"Initialized remote controller: {self.config_id}")
        
    def _load_defaults(self):
        """Load default settings from properties file and merge saved JSON overrides"""
        params = {
            "vfs-cache-mode": self.cfg.get("Defaults", "vfs-cache-mode", fallback="full"),
            "vfs-cache-max-age": self.cfg.get("Defaults", "vfs-cache-max-age", fallback="30m"),
            "dir-cache-time": self.cfg.get("Defaults", "dir-cache-time", fallback="1m"),
            "vfs-read-ahead": self.cfg.get("Defaults", "vfs-read-ahead", fallback="128M"),
            "bwlimit": self.cfg.get("Defaults", "bwlimit", fallback="off"),
            "extra_flags": self.cfg.get("Rclone", "extra_flags", fallback="--links"),
            "mountpoint": self.cfg.get("General", "mountpoint", fallback="auto"),
            "auto_mount": False,
            "clean_logs": True
        }
        if self.overrides_file.exists():
            try:
                with open(self.overrides_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    params.update(saved)
                logger.info(f"Loaded overrides for {self.config_id}")
            except Exception as e:
                logger.error(f"Error loading overrides for {self.config_id}: {e}")
        return params

    def save_overrides(self, params):
        self.runtime_params.update(params)
        with open(self.overrides_file, 'w', encoding='utf-8') as f:
            json.dump(self.runtime_params, f, indent=4)
        logger.info(f"Saved overrides for {self.config_id}")

    def get_info(self):
        return {
            "name": self.cfg.get("General", "name", fallback=self.config_id),
            "remote": self.cfg.get("General", "remote_name", fallback=f"{self.config_id}:"),
            "mountpoint": self.runtime_params.get("mountpoint", self.cfg.get("General", "mountpoint", fallback="auto"))
        }

    def start_mount(self, params_ui):
        if self.is_running:
            logger.warning(f"Mount already running for {self.config_id}")
            return

        # Save UI parameter overrides
        self.save_overrides(params_ui)
        
        # Prepare directories
        self.remote_cache.mkdir(exist_ok=True)
        self.remote_log_dir.mkdir(exist_ok=True)

        cmd = [get_rclone_path(), "mount"]
        
        # Remote & Mountpoint
        remote = self.cfg.get("General", "remote_name", fallback=f"{self.config_id}:")
        selected_mp = params_ui.get("mountpoint", self.cfg.get("General", "mountpoint", fallback="auto"))
        
        # Mountpoint argument resolution
        if platform.system() == "Windows":
            if "auto" in selected_mp.lower() or "*" in selected_mp:
                cmd.extend([remote, "*"]) # Auto-assign drive letter
            elif ":" in selected_mp:
                drive_letter = selected_mp.split()[0]
                cmd.extend([remote, drive_letter])
            else:
                cmd.extend([remote, selected_mp])
        else:
            cmd.extend([remote, selected_mp])

        # Rclone config path resolution
        conf_path = self.cfg.get("Rclone", "config_path", fallback=None)
        if conf_path:
            if not os.path.isabs(conf_path):
                conf_path = str(BASE_DIR / conf_path)
            if Path(conf_path).exists():
                cmd.append(f"--config={conf_path}")
            else:
                logger.warning(f"Config file not found: {conf_path}, using default")
        elif (BASE_DIR / "rclone.conf").exists():
            cmd.append(f"--config={str(BASE_DIR / 'rclone.conf')}")

        # VFS & Performance Parameters
        cache_mode = params_ui.get("vfs-cache-mode", "full")
        if " " in cache_mode:
            cache_mode = cache_mode.split()[0]
        cmd.append(f"--vfs-cache-mode={cache_mode}")
        cmd.append(f"--vfs-cache-max-age={params_ui.get('vfs-cache-max-age', '30m')}")
        cmd.append(f"--dir-cache-time={params_ui.get('dir-cache-time', '1m')}")
        
        read_ahead = params_ui.get("vfs-read-ahead", "").strip()
        if read_ahead:
            cmd.append(f"--vfs-read-ahead={read_ahead}")

        bwlimit = params_ui.get("bwlimit", "").strip()
        if bwlimit and bwlimit.lower() != "off":
            cmd.append(f"--bwlimit={bwlimit}")

        cmd.append(f"--cache-dir={str(self.remote_cache)}")
        cmd.append(f"--log-file={str(self.log_file)}")
        cmd.append("--verbose")

        # Volname
        volname = self.cfg.get("General", "volname", fallback=None)
        if volname:
            cmd.append(f"--volname={volname}")

        # Extra flags
        extra_flags = params_ui.get("extra_flags", "").strip() or self.cfg.get("Rclone", "extra_flags", fallback="")
        if extra_flags:
            cmd.extend(extra_flags.split())

        cmd_str = ' '.join(cmd)
        logger.info(f"Executing mount command for {self.config_id}: {cmd_str}")

        self.process = QProcess()
        self.process.setProgram(cmd[0])
        self.process.setArguments(cmd[1:])
        self.process.start()
        
        self.is_running = True
        self.mount_timestamp = datetime.now()
        self.error_message = ""

    def stop_mount(self, clean_logs=True):
        if not self.process or not self.is_running:
            logger.warning(f"No running mount to stop for {self.config_id}")
            return

        logger.info(f"Stopping mount for {self.config_id}...")
        
        # Graceful shutdown with taskkill / fusermount fallback
        if platform.system() == "Windows":
            self.process.terminate()
            if not self.process.waitForFinished(3000):
                logger.warning(f"Terminate timeout for {self.config_id}, using taskkill")
                try:
                    subprocess.run(f"taskkill /F /T /PID {self.process.processId()}", 
                                   shell=True, check=True)
                except subprocess.CalledProcessError as e:
                    logger.error(f"Taskkill failed: {e}")
        else:
            mountpoint = self.cfg.get("General", "mountpoint", fallback="auto")
            if mountpoint != "auto":
                try:
                    subprocess.run(["fusermount", "-u", mountpoint], check=True)
                    logger.info(f"Fusermount successful for {mountpoint}")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Fusermount failed: {e}")
            self.process.terminate()
        
        self.process.waitForFinished()
        self.is_running = False
        self.process = None
        
        # Cleanup cache/logs
        self._cleanup(clean_logs)
        logger.info(f"Mount stopped for {self.config_id}")

    def _cleanup(self, clean_logs):
        """Safely cleans up cache and logs within BASE_DIR"""
        logger.info(f"Cleaning up {self.config_id}... (clean_logs={clean_logs})")
        
        # Safety Check: Guarantee deletion remains strictly inside application directory
        if self.remote_cache.exists() and self.remote_cache.is_relative_to(BASE_DIR):
            try:
                shutil.rmtree(self.remote_cache, ignore_errors=True)
                self.remote_cache.mkdir(exist_ok=True)
                logger.info(f"Cleaned cache for {self.config_id}")
            except Exception as e:
                logger.error(f"Error cleaning cache: {e}")
        
        if clean_logs and self.remote_log_dir.exists() and self.remote_log_dir.is_relative_to(BASE_DIR):
            try:
                shutil.rmtree(self.remote_log_dir, ignore_errors=True)
                self.remote_log_dir.mkdir(exist_ok=True)
                logger.info(f"Cleaned logs for {self.config_id}")
            except Exception as e:
                logger.error(f"Error cleaning logs: {e}")

    def get_mountpoint(self):
        """Return human-readable effective mountpoint"""
        mp = self.runtime_params.get("mountpoint", self.cfg.get("General", "mountpoint", fallback="auto"))
        if platform.system() == "Windows" and ("auto" in mp.lower() or "*" in mp):
            return "Auto-assigned"
        return mp

# --- MODERN UI COMPONENTS ---

class StatusIndicator(QLabel):
    """Modern status dot indicator supporting green, grey, yellow, and red states"""
    def __init__(self, parent=None, size=10):
        super().__init__(parent)
        self.size = size
        self.setFixedSize(size, size)
        self.status = "stopped"
        self.update_status("stopped")
        
    def update_status(self, status):
        self.status = status
        colors = {
            "running": "#10b981",  # Emerald Green
            "stopped": "#64748b",  # Slate Grey
            "starting": "#f59e0b", # Amber Yellow
            "mounting": "#f59e0b",
            "error": "#ef4444"     # Red
        }
        color = colors.get(status, "#64748b")
        radius = max(2, self.size // 2)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                border-radius: {radius}px;
                border: 1px solid rgba(255, 255, 255, 0.25);
            }}
        """)

class ModernButton(QPushButton):
    """Modern action button supporting custom gradient styles and heights"""
    def __init__(self, text, color="#10b981", parent=None, min_height=42):
        super().__init__(text, parent)
        self.base_color = color
        self.min_height = min_height
        self.setMinimumHeight(min_height)
        self.setCursor(Qt.PointingHandCursor)
        self._update_style()
        
    def _update_style(self):
        if self.base_color == "#ef4444":
            # Danger / Unmount style
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #ef4444;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 20px;
                    font-weight: bold;
                    font-size: 13px;
                    letter-spacing: 0.5px;
                }}
                QPushButton:hover {{
                    background-color: #dc2626;
                }}
                QPushButton:pressed {{
                    background-color: #b91c1c;
                }}
                QPushButton:disabled {{
                    background-color: #1e2533;
                    color: #475569;
                    border: 1px solid #283042;
                }}
            """)
        else:
            # Primary Mount gradient style
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #10b981, stop:1 #059669);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 20px;
                    font-weight: bold;
                    font-size: 13px;
                    letter-spacing: 0.5px;
                }}
                QPushButton:hover {{
                    background: #059669;
                }}
                QPushButton:pressed {{
                    background: #047857;
                }}
                QPushButton:disabled {{
                    background: #1e2533;
                    color: #475569;
                    border: 1px solid #283042;
                }}
            """)

class ModernCard(QFrame):
    """Surface container card with sleek dark border and rounded corners"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #171b26;
                border-radius: 8px;
                border: 1px solid #283042;
                padding: 16px;
            }
        """)

class RemoteListItem(QWidget):
    """Custom sidebar list item with compact density (32px), icons, and status badges"""
    clicked = Signal(str)
    
    def __init__(self, remote_id: str, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("RemoteListItem")
        self.remote_id = remote_id
        self.name = name
        self.is_selected = False
        
        icon_str, tag_str, _ = get_provider_info(remote_id, name)
        self.provider_tag = tag_str
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignVCenter)
        
        # Status indicator dot
        self.status_indicator = StatusIndicator(size=10)
        layout.addWidget(self.status_indicator)
        
        # Provider icon
        self.icon_label = QLabel(icon_str)
        self.icon_label.setFont(QFont("Segoe UI Emoji", 11))
        layout.addWidget(self.icon_label)
        
        # Remote display name
        self.name_label = QLabel(name)
        self.name_label.setFont(QFont("Segoe UI", 9, QFont.Medium))
        self.name_label.setStyleSheet("color: #e2e8f0;")
        layout.addWidget(self.name_label, 1)
        
        # Tag badge (CURRENT or Provider)
        self.tag_label = QLabel(self.provider_tag)
        self.tag_label.setFont(QFont("Segoe UI", 8, QFont.Bold))
        layout.addWidget(self.tag_label)
        
        self.update_style()
        
    def setSelectedState(self, selected: bool):
        self.is_selected = selected
        if selected:
            self.tag_label.setText("CURRENT")
            self.tag_label.setStyleSheet("""
                color: #10b981;
                background-color: rgba(16, 185, 129, 0.15);
                border: 1px solid rgba(16, 185, 129, 0.4);
                border-radius: 4px;
                padding: 1px 6px;
            """)
        else:
            self.tag_label.setText(self.provider_tag)
            self.tag_label.setStyleSheet("""
                color: #64748b;
                background-color: transparent;
                border: 1px solid #283042;
                border-radius: 4px;
                padding: 1px 6px;
            """)
        self.update_style()

    def set_status(self, status: str):
        self.status_indicator.update_status(status)

    def update_style(self):
        if self.is_selected:
            self.setStyleSheet("""
                #RemoteListItem {
                    background-color: #1e293b;
                    border-radius: 6px;
                }
            """)
        else:
            self.setStyleSheet("""
                #RemoteListItem {
                    background-color: transparent;
                    border-radius: 6px;
                }
                #RemoteListItem:hover {
                    background-color: #171f2d;
                }
            """)
            self.tag_label.setStyleSheet("""
                color: #64748b;
                background-color: transparent;
                border: 1px solid #283042;
                border-radius: 4px;
                padding: 1px 6px;
            """)
        
    def mousePressEvent(self, event):
        self.clicked.emit(self.remote_id)
        # Transfer keyboard focus to the parent QListWidget for arrow key navigation
        parent = self.parentWidget()
        while parent:
            if isinstance(parent, QListWidget):
                parent.setFocus()
                break
            parent = parent.parentWidget()
        super().mousePressEvent(event)

# --- RIGHT DETAILS PANEL ---

class RemoteWidget(QWidget):
    """Right-hand remote details panel: Overview, Actions, Collapsible Settings, and Terminal Stream"""
    status_changed = Signal()
    
    def __init__(self):
        super().__init__()
        self.current_controller = None
        self.settings_expanded = False
        
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.update_log_view)
        self.log_timer.setInterval(1000)
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # =========================================================================
        # CARD 1: REMOTE OVERVIEW & HEADER
        # =========================================================================
        header_card = ModernCard()
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(16, 16, 16, 16)
        header_layout.setSpacing(14)
        
        # Large Avatar Box
        self.avatar_box = QFrame()
        self.avatar_box.setFixedSize(48, 48)
        self.avatar_box.setStyleSheet("""
            QFrame {
                background-color: rgba(16, 185, 129, 0.1);
                border: 1px solid rgba(16, 185, 129, 0.3);
                border-radius: 8px;
            }
        """)
        avatar_layout = QVBoxLayout(self.avatar_box)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_avatar_icon = QLabel("💾")
        self.lbl_avatar_icon.setAlignment(Qt.AlignCenter)
        self.lbl_avatar_icon.setFont(QFont("Segoe UI Emoji", 18))
        avatar_layout.addWidget(self.lbl_avatar_icon)
        header_layout.addWidget(self.avatar_box)
        
        # Remote Info Center Column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # Row 1: Title and Remote Name Tag
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.lbl_name = QLabel("Select a remote")
        self.lbl_name.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.lbl_name.setStyleSheet("color: #ffffff;")
        title_row.addWidget(self.lbl_name)
        
        self.lbl_remote_tag = QLabel("remote:")
        self.lbl_remote_tag.setFont(QFont("Consolas", 9))
        self.lbl_remote_tag.setStyleSheet("""
            color: #94a3b8;
            background-color: #1e2533;
            border: 1px solid #283042;
            border-radius: 4px;
            padding: 2px 6px;
        """)
        title_row.addWidget(self.lbl_remote_tag)
        title_row.addStretch()
        info_layout.addLayout(title_row)
        
        # Row 2: Status Indicator, Target, Cache Size
        status_subrow = QHBoxLayout()
        status_subrow.setSpacing(8)
        self.status_indicator = StatusIndicator(size=10)
        status_subrow.addWidget(self.status_indicator)
        
        self.lbl_status = QLabel("Status: STOPPED")
        self.lbl_status.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_status.setStyleSheet("color: #64748b;")
        status_subrow.addWidget(self.lbl_status)
        
        dot_sep1 = QLabel("•")
        dot_sep1.setStyleSheet("color: #475569;")
        status_subrow.addWidget(dot_sep1)
        
        self.lbl_target = QLabel("Target: Auto-assigned")
        self.lbl_target.setFont(QFont("Segoe UI", 9))
        self.lbl_target.setStyleSheet("color: #94a3b8;")
        status_subrow.addWidget(self.lbl_target)
        
        dot_sep2 = QLabel("•")
        dot_sep2.setStyleSheet("color: #475569;")
        status_subrow.addWidget(dot_sep2)
        
        self.lbl_cached_data = QLabel("Cached data: 0 B")
        self.lbl_cached_data.setFont(QFont("Segoe UI", 9))
        self.lbl_cached_data.setStyleSheet("color: #94a3b8;")
        status_subrow.addWidget(self.lbl_cached_data)
        
        status_subrow.addStretch()
        info_layout.addLayout(status_subrow)
        
        header_layout.addLayout(info_layout, 1)
        
        # Right Side: Mountpoint Dropdown
        mp_container = QVBoxLayout()
        mp_container.setSpacing(4)
        mp_title = QLabel("MOUNT POINT")
        mp_title.setFont(QFont("Segoe UI", 8, QFont.Bold))
        mp_title.setStyleSheet("color: #64748b;")
        mp_container.addWidget(mp_title)
        
        self.combo_mountpoint = QComboBox()
        self.combo_mountpoint.addItems(get_available_drive_letters())
        self.combo_mountpoint.setMinimumWidth(180)
        self.combo_mountpoint.currentTextChanged.connect(self.on_mountpoint_changed)
        self._style_combobox(self.combo_mountpoint)
        mp_container.addWidget(self.combo_mountpoint)
        
        header_layout.addLayout(mp_container)
        main_layout.addWidget(header_card)
        
        # =========================================================================
        # CARD 2: ACTION TOOLBAR & OPERATIONS
        # =========================================================================
        action_card = ModernCard()
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(16, 16, 16, 16)
        action_layout.setSpacing(12)
        
        # Row 1: Primary Action Buttons
        btn_action_row = QHBoxLayout()
        btn_action_row.setSpacing(12)
        
        self.btn_mount = ModernButton("▶ MOUNT REMOTE", "#10b981", min_height=42)
        self.btn_mount.clicked.connect(self.on_mount)
        btn_action_row.addWidget(self.btn_mount, 1)
        
        self.btn_unmount = ModernButton("■ UNMOUNT", "#ef4444", min_height=42)
        self.btn_unmount.setEnabled(False)
        self.btn_unmount.clicked.connect(self.on_unmount)
        btn_action_row.addWidget(self.btn_unmount, 1)
        
        action_layout.addLayout(btn_action_row)
        
        # Row 2: Secondary Utility Buttons
        util_row = QHBoxLayout()
        util_row.setSpacing(8)
        
        self.btn_open_mount = QPushButton("📂 Open Mount")
        self.btn_open_mount.setEnabled(False)
        self.btn_open_mount.clicked.connect(self.on_open_mount)
        self._style_util_button(self.btn_open_mount)
        util_row.addWidget(self.btn_open_mount)
        
        self.btn_open_logs = QPushButton("📄 Open Logs")
        self.btn_open_logs.clicked.connect(self.on_open_logs)
        self._style_util_button(self.btn_open_logs)
        util_row.addWidget(self.btn_open_logs)
        
        self.btn_open_cache = QPushButton("📡 Open Cache")
        self.btn_open_cache.clicked.connect(self.on_open_cache)
        self._style_util_button(self.btn_open_cache)
        util_row.addWidget(self.btn_open_cache)
        
        self.btn_show_command = QPushButton("⌨️ Show Command")
        self.btn_show_command.clicked.connect(self.on_show_command)
        self._style_util_button(self.btn_show_command)
        util_row.addWidget(self.btn_show_command)
        
        action_layout.addLayout(util_row)
        
        # Row 3: Checkboxes & Cache Path Info
        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        
        self.chk_clean_logs = QCheckBox("Clean cache and logs after unmount")
        self.chk_clean_logs.setChecked(True)
        self._style_checkbox(self.chk_clean_logs)
        options_row.addWidget(self.chk_clean_logs)
        
        self.chk_auto_mount = QCheckBox("Auto-mount on application launch")
        self.chk_auto_mount.setChecked(False)
        self.chk_auto_mount.toggled.connect(self.on_auto_mount_toggled)
        self._style_checkbox(self.chk_auto_mount)
        options_row.addWidget(self.chk_auto_mount)
        
        options_row.addStretch()
        
        self.lbl_cache_dir = QLabel("VFS Cache Directory: cache/")
        self.lbl_cache_dir.setFont(QFont("Consolas", 8))
        self.lbl_cache_dir.setStyleSheet("color: #64748b;")
        options_row.addWidget(self.lbl_cache_dir)
        
        action_layout.addLayout(options_row)
        main_layout.addWidget(action_card)
        
        # =========================================================================
        # CARD 3: VFS & PERFORMANCE SETTINGS (COLLAPSIBLE)
        # =========================================================================
        self.settings_card = ModernCard()
        settings_outer_layout = QVBoxLayout(self.settings_card)
        settings_outer_layout.setContentsMargins(16, 12, 16, 12)
        settings_outer_layout.setSpacing(10)
        
        # Collapsible Card Header
        settings_header_row = QHBoxLayout()
        
        self.btn_toggle_settings = QPushButton("⚙️ VFS & PERFORMANCE SETTINGS  ▸")
        self.btn_toggle_settings.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_settings.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_toggle_settings.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #e2e8f0;
                text-align: left;
                padding: 4px 0px;
            }
            QPushButton:hover {
                color: #38bdf8;
            }
        """)
        self.btn_toggle_settings.clicked.connect(self.toggle_settings)
        settings_header_row.addWidget(self.btn_toggle_settings)
        
        settings_header_row.addStretch()
        
        self.btn_reset_defaults = QPushButton("Reset to Defaults")
        self.btn_reset_defaults.setCursor(Qt.PointingHandCursor)
        self.btn_reset_defaults.setFont(QFont("Segoe UI", 9))
        self.btn_reset_defaults.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #94a3b8;
                text-decoration: underline;
                padding: 4px 8px;
            }
            QPushButton:hover {
                color: #38bdf8;
            }
        """)
        self.btn_reset_defaults.clicked.connect(self.reset_settings_to_defaults)
        settings_header_row.addWidget(self.btn_reset_defaults)
        
        settings_outer_layout.addLayout(settings_header_row)
        
        # Body: 3-column QGridLayout for settings
        self.group_settings = QGroupBox()
        self.group_settings.setStyleSheet("QGroupBox { border: none; background: transparent; }")
        grid_layout = QGridLayout(self.group_settings)
        grid_layout.setHorizontalSpacing(16)
        grid_layout.setVerticalSpacing(12)
        grid_layout.setContentsMargins(0, 6, 0, 0)
        
        # Col 1, Row 0: VFS Cache Mode
        vfs_container = QVBoxLayout()
        vfs_container.setSpacing(3)
        vfs_lbl_row = QHBoxLayout()
        vfs_label = QLabel("VFS Cache Mode")
        vfs_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        vfs_label.setStyleSheet("color: #e2e8f0;")
        vfs_lbl_row.addWidget(vfs_label)
        vfs_lbl_row.addStretch()
        vfs_tag = QLabel("--vfs-cache-mode")
        vfs_tag.setFont(QFont("Consolas", 8))
        vfs_tag.setStyleSheet("color: #2dd4bf;")
        vfs_lbl_row.addWidget(vfs_tag)
        vfs_container.addLayout(vfs_lbl_row)
        
        self.combo_cache_mode = QComboBox()
        self.combo_cache_mode.addItems(["off", "minimal", "writes", "full (Complete caching - Recommended)"])
        self.combo_cache_mode.setCurrentIndex(3)
        self._style_combobox(self.combo_cache_mode)
        vfs_container.addWidget(self.combo_cache_mode)
        
        vfs_desc = QLabel("Enables full file caching for seek support in video players and random writes.")
        vfs_desc.setWordWrap(True)
        vfs_desc.setFont(QFont("Segoe UI", 8))
        vfs_desc.setStyleSheet("color: #64748b;")
        vfs_container.addWidget(vfs_desc)
        grid_layout.addLayout(vfs_container, 0, 0)
        
        # Col 2, Row 0: Cache Max Age
        age_container = QVBoxLayout()
        age_container.setSpacing(3)
        age_lbl_row = QHBoxLayout()
        age_label = QLabel("Cache Max Age")
        age_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        age_label.setStyleSheet("color: #e2e8f0;")
        age_lbl_row.addWidget(age_label)
        age_lbl_row.addStretch()
        age_tag = QLabel("--vfs-cache-max-age")
        age_tag.setFont(QFont("Consolas", 8))
        age_tag.setStyleSheet("color: #2dd4bf;")
        age_lbl_row.addWidget(age_tag)
        age_container.addLayout(age_lbl_row)
        
        self.combo_cache_age = QComboBox()
        self.combo_cache_age.setEditable(True)
        self.combo_cache_age.addItems(["30m", "1h", "12h", "24h"])
        self.combo_cache_age.setCurrentText("30m")
        self._style_combobox(self.combo_cache_age)
        age_container.addWidget(self.combo_cache_age)
        
        age_desc = QLabel("Max duration unused cached objects remain stored on the local drive.")
        age_desc.setWordWrap(True)
        age_desc.setFont(QFont("Segoe UI", 8))
        age_desc.setStyleSheet("color: #64748b;")
        age_container.addWidget(age_desc)
        grid_layout.addLayout(age_container, 0, 1)
        
        # Col 3, Row 0: Dir Cache Time
        dir_container = QVBoxLayout()
        dir_container.setSpacing(3)
        dir_lbl_row = QHBoxLayout()
        dir_label = QLabel("Dir Cache Time")
        dir_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        dir_label.setStyleSheet("color: #e2e8f0;")
        dir_lbl_row.addWidget(dir_label)
        dir_lbl_row.addStretch()
        dir_tag = QLabel("--dir-cache-time")
        dir_tag.setFont(QFont("Consolas", 8))
        dir_tag.setStyleSheet("color: #2dd4bf;")
        dir_lbl_row.addWidget(dir_tag)
        dir_container.addLayout(dir_lbl_row)
        
        self.combo_dir_cache = QComboBox()
        self.combo_dir_cache.setEditable(True)
        self.combo_dir_cache.addItems(["1m", "5m", "15m", "30m"])
        self.combo_dir_cache.setCurrentText("1m")
        self._style_combobox(self.combo_dir_cache)
        dir_container.addWidget(self.combo_dir_cache)
        
        dir_desc = QLabel("Directory list cache retention before querying the cloud API again.")
        dir_desc.setWordWrap(True)
        dir_desc.setFont(QFont("Segoe UI", 8))
        dir_desc.setStyleSheet("color: #64748b;")
        dir_container.addWidget(dir_desc)
        grid_layout.addLayout(dir_container, 0, 2)
        
        # Col 1, Row 1: Read Ahead Buffer
        ra_container = QVBoxLayout()
        ra_container.setSpacing(3)
        ra_lbl_row = QHBoxLayout()
        ra_label = QLabel("Read Ahead Buffer")
        ra_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        ra_label.setStyleSheet("color: #e2e8f0;")
        ra_lbl_row.addWidget(ra_label)
        ra_lbl_row.addStretch()
        ra_tag = QLabel("--vfs-read-ahead")
        ra_tag.setFont(QFont("Consolas", 8))
        ra_tag.setStyleSheet("color: #2dd4bf;")
        ra_lbl_row.addWidget(ra_tag)
        ra_container.addLayout(ra_lbl_row)
        
        self.edit_read_ahead = QLineEdit("128M")
        self._style_line_edit(self.edit_read_ahead)
        ra_container.addWidget(self.edit_read_ahead)
        
        ra_desc = QLabel("Amount of data to read ahead sequentially.")
        ra_desc.setWordWrap(True)
        ra_desc.setFont(QFont("Segoe UI", 8))
        ra_desc.setStyleSheet("color: #64748b;")
        ra_container.addWidget(ra_desc)
        grid_layout.addLayout(ra_container, 1, 0)
        
        # Col 2, Row 1: Bandwidth Limit
        bw_container = QVBoxLayout()
        bw_container.setSpacing(3)
        bw_lbl_row = QHBoxLayout()
        bw_label = QLabel("Bandwidth Limit")
        bw_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        bw_label.setStyleSheet("color: #e2e8f0;")
        bw_lbl_row.addWidget(bw_label)
        bw_lbl_row.addStretch()
        bw_tag = QLabel("--bwlimit")
        bw_tag.setFont(QFont("Consolas", 8))
        bw_tag.setStyleSheet("color: #2dd4bf;")
        bw_lbl_row.addWidget(bw_tag)
        bw_container.addLayout(bw_lbl_row)
        
        self.edit_bwlimit = QLineEdit("off")
        self._style_line_edit(self.edit_bwlimit)
        bw_container.addWidget(self.edit_bwlimit)
        
        bw_desc = QLabel("Network bandwidth cap. Default is 'off' (unmetered).")
        bw_desc.setWordWrap(True)
        bw_desc.setFont(QFont("Segoe UI", 8))
        bw_desc.setStyleSheet("color: #64748b;")
        bw_container.addWidget(bw_desc)
        grid_layout.addLayout(bw_container, 1, 1)
        
        # Col 3, Row 1: Extra Flags
        flags_container = QVBoxLayout()
        flags_container.setSpacing(3)
        flags_lbl_row = QHBoxLayout()
        flags_label = QLabel("Extra Flags")
        flags_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        flags_label.setStyleSheet("color: #e2e8f0;")
        flags_lbl_row.addWidget(flags_label)
        flags_lbl_row.addStretch()
        flags_tag = QLabel("CLI Options")
        flags_tag.setFont(QFont("Consolas", 8))
        flags_tag.setStyleSheet("color: #94a3b8;")
        flags_lbl_row.addWidget(flags_tag)
        flags_container.addLayout(flags_lbl_row)
        
        self.edit_extra_flags = QLineEdit("--links")
        self._style_line_edit(self.edit_extra_flags)
        flags_container.addWidget(self.edit_extra_flags)
        
        flags_desc = QLabel("Custom arguments passed directly into the background process.")
        flags_desc.setWordWrap(True)
        flags_desc.setFont(QFont("Segoe UI", 8))
        flags_desc.setStyleSheet("color: #64748b;")
        flags_container.addWidget(flags_desc)
        grid_layout.addLayout(flags_container, 1, 2)
        
        settings_outer_layout.addWidget(self.group_settings)
        
        # Closed by default to reclaim vertical space
        self.group_settings.setVisible(False)
        main_layout.addWidget(self.settings_card)
        
        # =========================================================================
        # CARD 4: LIVE LOG STREAM TERMINAL
        # =========================================================================
        log_card = ModernCard()
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 14, 16, 14)
        log_layout.setSpacing(10)
        
        # Terminal Header
        log_header_row = QHBoxLayout()
        log_header_row.setSpacing(8)
        
        log_title = QLabel(">_ Live Log Stream")
        log_title.setFont(QFont("Consolas", 10, QFont.Bold))
        log_title.setStyleSheet("color: #38bdf8;")
        log_header_row.addWidget(log_title)
        
        log_sub = QLabel("(Last 20 lines)")
        log_sub.setFont(QFont("Segoe UI", 8))
        log_sub.setStyleSheet("color: #64748b;")
        log_header_row.addWidget(log_sub)
        
        log_header_row.addStretch()
        
        self.chk_auto_scroll = QCheckBox("Auto-scroll")
        self.chk_auto_scroll.setChecked(True)
        self._style_checkbox(self.chk_auto_scroll)
        log_header_row.addWidget(self.chk_auto_scroll)
        
        sep_log = QLabel("|")
        sep_log.setStyleSheet("color: #334155;")
        log_header_row.addWidget(sep_log)
        
        self.btn_copy_log = QPushButton("📋 Copy")
        self._style_util_button(self.btn_copy_log, min_height=24)
        self.btn_copy_log.clicked.connect(self.copy_log_to_clipboard)
        log_header_row.addWidget(self.btn_copy_log)
        
        self.btn_clear_log = QPushButton("🗑️ Clear")
        self._style_util_button(self.btn_clear_log, min_height=24)
        self.btn_clear_log.clicked.connect(self.clear_log_viewer)
        log_header_row.addWidget(self.btn_clear_log)
        
        log_layout.addLayout(log_header_row)
        
        # Terminal Log View
        self.log_viewer = QPlainTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMinimumHeight(180)
        self.log_viewer.setFont(QFont("Consolas", 10))
        self.log_viewer.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0a0c10;
                color: #e2e8f0;
                border: 1px solid #1e2533;
                border-radius: 6px;
                padding: 12px;
                font-family: 'Consolas', 'JetBrains Mono', 'Courier New', monospace;
            }
        """)
        self.log_highlighter = LogHighlighter(self.log_viewer.document())
        log_layout.addWidget(self.log_viewer)
        
        main_layout.addWidget(log_card)
        main_layout.addStretch()

    # --- STYLE HELPERS ---
    def _style_combobox(self, combo):
        combo.setStyleSheet("""
            QComboBox {
                background-color: #121620;
                border: 1px solid #2d3748;
                border-radius: 6px;
                padding: 6px 10px;
                color: #e2e8f0;
                font-size: 11px;
                min-height: 28px;
            }
            QComboBox:hover {
                border-color: #38bdf8;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #171b26;
                selection-background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #283042;
                padding: 4px;
            }
        """)

    def _style_line_edit(self, edit):
        edit.setStyleSheet("""
            QLineEdit {
                background-color: #121620;
                border: 1px solid #2d3748;
                border-radius: 6px;
                padding: 6px 10px;
                color: #e2e8f0;
                font-size: 11px;
                min-height: 20px;
            }
            QLineEdit:focus {
                border-color: #38bdf8;
            }
        """)

    def _style_util_button(self, btn, min_height=30):
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #171b26;
                border: 1px solid #283042;
                border-radius: 6px;
                padding: 6px 12px;
                color: #cbd5e1;
                font-size: 11px;
                min-height: {min_height}px;
            }}
            QPushButton:hover {{
                background-color: #202736;
                border-color: #38bdf8;
                color: #ffffff;
            }}
            QPushButton:pressed {{
                background-color: #121620;
            }}
            QPushButton:disabled {{
                background-color: #121620;
                color: #475569;
                border-color: #1e2533;
            }}
        """)

    def _style_checkbox(self, chk):
        chk.setStyleSheet("""
            QCheckBox {
                color: #cbd5e1;
                font-size: 11px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #2d3748;
                background-color: #121620;
            }
            QCheckBox::indicator:checked {
                background-color: #10b981;
                border-color: #10b981;
            }
        """)

    # --- SLOTS & ACTIONS ---
    def toggle_settings(self):
        """Toggle visibility of mount settings section"""
        self.settings_expanded = not self.settings_expanded
        self.group_settings.setVisible(self.settings_expanded)
        arrow = "▾" if self.settings_expanded else "▸"
        self.btn_toggle_settings.setText(f"⚙️ VFS & PERFORMANCE SETTINGS  {arrow}")

    def reset_settings_to_defaults(self):
        """Reset form fields to defaults defined in .properties file"""
        if not self.current_controller:
            return
        cfg = self.current_controller.cfg
        self.combo_cache_mode.setCurrentText(cfg.get("Defaults", "vfs-cache-mode", fallback="full"))
        self.combo_cache_age.setCurrentText(cfg.get("Defaults", "vfs-cache-max-age", fallback="30m"))
        self.combo_dir_cache.setCurrentText(cfg.get("Defaults", "dir-cache-time", fallback="1m"))
        self.edit_read_ahead.setText(cfg.get("Defaults", "vfs-read-ahead", fallback="128M"))
        self.edit_bwlimit.setText(cfg.get("Defaults", "bwlimit", fallback="off"))
        self.edit_extra_flags.setText(cfg.get("Rclone", "extra_flags", fallback="--links"))
        logger.info(f"Reset settings to defaults for {self.current_controller.config_id}")

    def on_mountpoint_changed(self, text):
        letter = text.split()[0] if text else "Auto"
        self.btn_mount.setText(f"▶ MOUNT REMOTE ({letter})")

    def on_auto_mount_toggled(self, checked):
        if self.current_controller:
            self.current_controller.save_overrides({"auto_mount": checked})

    def copy_log_to_clipboard(self):
        text = self.log_viewer.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def clear_log_viewer(self):
        self.log_viewer.clear()

    def load_remote(self, controller: RemoteController):
        self.current_controller = controller
        info = controller.get_info()
        name = info['name']
        remote = info['remote']
        
        self.lbl_name.setText(name)
        self.lbl_remote_tag.setText(remote)
        
        icon_str, tag_str, _ = get_provider_info(controller.config_id, name)
        self.lbl_avatar_icon.setText(icon_str)
        
        # Load parameters
        params = controller.runtime_params
        mode = params.get("vfs-cache-mode", "full")
        # Match combo item
        for idx in range(self.combo_cache_mode.count()):
            if self.combo_cache_mode.itemText(idx).startswith(mode):
                self.combo_cache_mode.setCurrentIndex(idx)
                break
        
        self.combo_cache_age.setCurrentText(params.get("vfs-cache-max-age", "30m"))
        self.combo_dir_cache.setCurrentText(params.get("dir-cache-time", "1m"))
        self.edit_read_ahead.setText(params.get("vfs-read-ahead", "128M"))
        self.edit_bwlimit.setText(params.get("bwlimit", "off"))
        self.edit_extra_flags.setText(params.get("extra_flags", "--links"))
        
        # Mountpoint
        mp = params.get("mountpoint", info.get("mountpoint", "auto"))
        idx = self.combo_mountpoint.findText(mp)
        if idx >= 0:
            self.combo_mountpoint.setCurrentIndex(idx)
        else:
            self.combo_mountpoint.setCurrentText(mp)
            
        self.chk_auto_mount.setChecked(params.get("auto_mount", False))
        self.lbl_cache_dir.setText(f"VFS Cache Directory: cache/{controller.config_id}/")
        
        self.refresh_state()

    def refresh_state(self):
        if not self.current_controller:
            return
            
        running = self.current_controller.is_running
        self.btn_mount.setEnabled(not running)
        self.btn_unmount.setEnabled(running)
        self.btn_open_mount.setEnabled(running)
        self.group_settings.setEnabled(not running)
        
        # Calculate cached data size
        size_str = get_dir_size_str(self.current_controller.remote_cache)
        self.lbl_cached_data.setText(f"Cached data: {size_str}")
        
        # Update target text
        mp_text = self.current_controller.get_mountpoint()
        self.lbl_target.setText(f"Target: {mp_text}")
        
        if running:
            self.status_indicator.update_status("running")
            pid = self.current_controller.process.processId() if self.current_controller.process else "N/A"
            self.lbl_status.setText(f"Status: RUNNING (PID: {pid})")
            self.lbl_status.setStyleSheet("color: #10b981; font-weight: bold;")
            
            if not self.log_timer.isActive():
                self.log_timer.start()
        else:
            self.status_indicator.update_status("stopped")
            self.lbl_status.setText("Status: STOPPED")
            self.lbl_status.setStyleSheet("color: #64748b; font-weight: bold;")
            self.log_timer.stop()

    def on_mount(self):
        if not self.current_controller: 
            return
        
        rclone_path = get_rclone_path()
        if not shutil.which(rclone_path):
            QMessageBox.critical(self, "❌ Error", 
                f"Rclone executable not found: {rclone_path}\n\n"
                "Please install rclone or place it in the application folder.")
            return

        cache_mode = self.combo_cache_mode.currentText().split()[0]
        params = {
            "vfs-cache-mode": cache_mode,
            "vfs-cache-max-age": self.combo_cache_age.currentText(),
            "dir-cache-time": self.combo_dir_cache.currentText(),
            "vfs-read-ahead": self.edit_read_ahead.text(),
            "bwlimit": self.edit_bwlimit.text(),
            "extra_flags": self.edit_extra_flags.text(),
            "mountpoint": self.combo_mountpoint.currentText(),
            "clean_logs": self.chk_clean_logs.isChecked(),
            "auto_mount": self.chk_auto_mount.isChecked()
        }
        
        try:
            self.status_indicator.update_status("starting")
            self.current_controller.start_mount(params)
            if self.current_controller.process:
                self.current_controller.process.finished.connect(self.on_process_finished)
            self.refresh_state()
            self.status_changed.emit()
            logger.info(f"Mount initiated for {self.current_controller.config_id}")
        except Exception as e:
            self.refresh_state()
            self.status_changed.emit()
            logger.error(f"Mount error: {e}")
            QMessageBox.critical(self, "❌ Mount Error", str(e))

    def on_unmount(self):
        if not self.current_controller: 
            return
        self.current_controller.stop_mount(clean_logs=self.chk_clean_logs.isChecked())
        self.refresh_state()
        self.status_changed.emit()

    def on_process_finished(self):
        self.refresh_state()
        self.status_changed.emit()
        self.log_viewer.appendPlainText("\n--- [SYSTEM] PROCESS TERMINATED ---\n")
        logger.info(f"Process finished for {self.current_controller.config_id}")

    def on_open_mount(self):
        if not self.current_controller or not self.current_controller.is_running:
            return
        
        mountpoint = self.current_controller.get_mountpoint()
        if platform.system() == "Windows":
            if mountpoint == "Auto-assigned":
                QMessageBox.information(self, "ℹ️ Info", 
                    "Cannot open auto-assigned drive directly. Check assigned drive letter in File Explorer.")
            else:
                letter = mountpoint.split()[0]
                os.startfile(letter)
        else:
            subprocess.Popen(["xdg-open", mountpoint])

    def on_open_logs(self):
        if not self.current_controller:
            return
        path = self.current_controller.remote_log_dir
        path.mkdir(exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def on_open_cache(self):
        if not self.current_controller:
            return
        path = self.current_controller.remote_cache
        path.mkdir(exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def on_show_command(self):
        if not self.current_controller:
            return
        
        cache_mode = self.combo_cache_mode.currentText().split()[0]
        params = {
            "vfs-cache-mode": cache_mode,
            "vfs-cache-max-age": self.combo_cache_age.currentText(),
            "dir-cache-time": self.combo_dir_cache.currentText(),
            "vfs-read-ahead": self.edit_read_ahead.text(),
            "bwlimit": self.edit_bwlimit.text(),
            "extra_flags": self.edit_extra_flags.text(),
            "mountpoint": self.combo_mountpoint.currentText()
        }
        
        cmd = [get_rclone_path(), "mount"]
        remote = self.current_controller.cfg.get("General", "remote_name", fallback=f"{self.current_controller.config_id}:")
        selected_mp = params["mountpoint"]
        
        if platform.system() == "Windows":
            if "auto" in selected_mp.lower() or "*" in selected_mp:
                cmd.extend([remote, "*"])
            elif ":" in selected_mp:
                cmd.extend([remote, selected_mp.split()[0]])
            else:
                cmd.extend([remote, selected_mp])
        else:
            cmd.extend([remote, selected_mp])
        
        cmd.append(f"--vfs-cache-mode={params['vfs-cache-mode']}")
        cmd.append(f"--vfs-cache-max-age={params['vfs-cache-max-age']}")
        cmd.append(f"--dir-cache-time={params['dir-cache-time']}")
        
        if params["vfs-read-ahead"].strip():
            cmd.append(f"--vfs-read-ahead={params['vfs-read-ahead'].strip()}")
        if params["bwlimit"].strip() and params["bwlimit"].strip().lower() != "off":
            cmd.append(f"--bwlimit={params['bwlimit'].strip()}")
            
        cmd.append(f"--cache-dir={str(self.current_controller.remote_cache)}")
        cmd.append(f"--log-file={str(self.current_controller.log_file)}")
        cmd.append("--verbose")
        
        volname = self.current_controller.cfg.get("General", "volname", fallback=None)
        if volname:
            cmd.append(f"--volname={volname}")
        if params["extra_flags"].strip():
            cmd.extend(params["extra_flags"].strip().split())
        
        cmd_str = ' '.join(cmd)
        
        msg = QMessageBox(self)
        msg.setWindowTitle("⌨️ Mount Command Preview")
        msg.setText("The following command will be executed:")
        msg.setDetailedText(cmd_str)
        msg.setIcon(QMessageBox.Information)
        msg.setStyleSheet("QMessageBox { background-color: #171b26; color: #ffffff; }")
        msg.exec()

    def update_log_view(self):
        if not self.current_controller or not self.current_controller.log_file.exists():
            return
            
        try:
            with open(self.current_controller.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                last_lines = lines[-20:] if len(lines) > 20 else lines
                self.log_viewer.setPlainText("".join(last_lines))
                if self.chk_auto_scroll.isChecked():
                    self.log_viewer.verticalScrollBar().setValue(self.log_viewer.verticalScrollBar().maximum())
        except Exception as e:
            logger.error(f"Error reading log: {e}")

# --- MAIN WINDOW ---

class MainWindow(QMainWindow):
    """Main window with sidebar filtering, status counters, and details panel"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1240, 780)
        
        icon_path = get_icon_path()
        if icon_path and icon_path.exists():
            app_icon = QIcon(str(icon_path))
            self.setWindowIcon(app_icon)
            QApplication.instance().setWindowIcon(app_icon)
            logger.info(f"Loaded icon from: {icon_path}")
        
        self.controllers = {}
        self._setup_tray()
        
        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Top Title & Workspace Bar ---
        top_bar = QFrame()
        top_bar.setStyleSheet("""
            QFrame {
                background-color: #0c0e14;
                border-bottom: 1px solid #1e2533;
                padding: 6px 14px;
            }
        """)
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        top_bar_layout.setSpacing(10)
        
        logo_lbl = QLabel("☁️")
        logo_lbl.setFont(QFont("Segoe UI Emoji", 12))
        top_bar_layout.addWidget(logo_lbl)
        
        app_title = QLabel(APP_NAME)
        app_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        app_title.setStyleSheet("color: #ffffff;")
        top_bar_layout.addWidget(app_title)
        
        ver_badge = QLabel(f"v{VERSION}")
        ver_badge.setFont(QFont("Consolas", 8))
        ver_badge.setStyleSheet("""
            color: #94a3b8;
            background-color: #171b26;
            border: 1px solid #283042;
            border-radius: 4px;
            padding: 1px 6px;
        """)
        top_bar_layout.addWidget(ver_badge)
        
        ready_dot = QLabel("● Ready")
        ready_dot.setFont(QFont("Segoe UI", 9))
        ready_dot.setStyleSheet("color: #10b981;")
        top_bar_layout.addWidget(ready_dot)
        
        top_bar_layout.addStretch()
        
        self.lbl_active_workspace = QLabel("Select a remote to manage")
        self.lbl_active_workspace.setFont(QFont("Segoe UI", 9))
        self.lbl_active_workspace.setStyleSheet("color: #64748b;")
        top_bar_layout.addWidget(self.lbl_active_workspace)
        
        root_layout.addWidget(top_bar)
        
        # --- Main Split Layout (Sidebar + Details) ---
        main_content = QWidget()
        main_layout = QHBoxLayout(main_content)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # =========================================================================
        # LEFT SIDEBAR
        # =========================================================================
        sidebar = QFrame()
        sidebar.setFixedWidth(290)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #0f131e;
                border-right: 1px solid #1e2533;
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        
        # Sidebar Header: Title, Counter Badges, Search Filter
        header = QWidget()
        header.setStyleSheet("background-color: #0f131e; border-bottom: 1px solid #1e2533;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 14, 14, 12)
        header_layout.setSpacing(10)
        
        # Row 1: REMOTES title & status badges
        header_top_row = QHBoxLayout()
        header_top_row.setSpacing(8)
        
        title_icon = QLabel("⚡ REMOTES")
        title_icon.setFont(QFont("Segoe UI", 10, QFont.Bold))
        title_icon.setStyleSheet("color: #e2e8f0; letter-spacing: 0.5px;")
        header_top_row.addWidget(title_icon)
        
        header_top_row.addStretch()
        
        self.badge_active = QLabel("0 Active")
        self.badge_active.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.badge_active.setStyleSheet("""
            color: #10b981;
            background-color: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 4px;
            padding: 2px 6px;
        """)
        header_top_row.addWidget(self.badge_active)
        
        self.badge_inactive = QLabel("0 Inactive")
        self.badge_inactive.setFont(QFont("Segoe UI", 8))
        self.badge_inactive.setStyleSheet("""
            color: #64748b;
            background-color: #171b26;
            border: 1px solid #283042;
            border-radius: 4px;
            padding: 2px 6px;
        """)
        header_top_row.addWidget(self.badge_inactive)
        header_layout.addLayout(header_top_row)
        
        # Row 2: Search filter with shortcut
        search_box = QHBoxLayout()
        search_box.setSpacing(6)
        
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText("Filter remotes (Ctrl+F)...")
        self.search_filter.textChanged.connect(self.filter_remotes)
        self.search_filter.installEventFilter(self)
        self.search_filter.setStyleSheet("""
            QLineEdit {
                background-color: #121620;
                border: 1px solid #283042;
                border-radius: 6px;
                padding: 6px 10px;
                color: #e2e8f0;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #38bdf8;
            }
        """)
        search_box.addWidget(self.search_filter, 1)
        
        # Shortcut Ctrl+F
        shortcut_filter = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_filter.activated.connect(self.search_filter.setFocus)
        
        self.btn_search_refresh = QPushButton("🔄")
        self.btn_search_refresh.setFixedSize(28, 28)
        self.btn_search_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_search_refresh.setStyleSheet("""
            QPushButton {
                background-color: #171b26;
                border: 1px solid #283042;
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #202736;
                border-color: #38bdf8;
            }
        """)
        self.btn_search_refresh.clicked.connect(self.refresh_remotes)
        search_box.addWidget(self.btn_search_refresh)
        
        header_layout.addLayout(search_box)
        sidebar_layout.addWidget(header, 0)
        
        # Remote List Widget
        self.list_widget = QListWidget()
        self.list_widget.setFocusPolicy(Qt.StrongFocus)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.currentItemChanged.connect(self.on_current_item_changed)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                outline: none;
                padding: 6px;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 2px 0px;
            }
            QListWidget::item:selected {
                background: transparent;
            }
        """)
        self.list_widget.setSpacing(1)
        sidebar_layout.addWidget(self.list_widget, 1)
        
        # Sidebar Footer
        footer = QWidget()
        footer.setStyleSheet("background-color: #0f131e; border-top: 1px solid #1e2533;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 12, 14, 12)
        footer_layout.setSpacing(8)
        
        self.btn_add_remote = QPushButton("+ Add Remote")
        self.btn_add_remote.setCursor(Qt.PointingHandCursor)
        self.btn_add_remote.setStyleSheet("""
            QPushButton {
                background-color: #171b26;
                border: 1px solid #283042;
                border-radius: 6px;
                padding: 8px 14px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #202736;
                border-color: #10b981;
                color: #ffffff;
            }
        """)
        self.btn_add_remote.clicked.connect(self.on_add_remote)
        footer_layout.addWidget(self.btn_add_remote, 1)
        
        self.btn_open_config = QPushButton("⚙️")
        self.btn_open_config.setFixedSize(34, 34)
        self.btn_open_config.setCursor(Qt.PointingHandCursor)
        self.btn_open_config.setStyleSheet("""
            QPushButton {
                background-color: #171b26;
                border: 1px solid #283042;
                border-radius: 6px;
                color: #e2e8f0;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #202736;
                border-color: #38bdf8;
            }
        """)
        self.btn_open_config.clicked.connect(self.on_open_config_folder)
        footer_layout.addWidget(self.btn_open_config)
        
        sidebar_layout.addWidget(footer, 0)
        main_layout.addWidget(sidebar)
        
        # =========================================================================
        # RIGHT PANEL: DETAILS SCROLL AREA
        # =========================================================================
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.details_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.details_scroll.setStyleSheet("QScrollArea { background-color: #0c0e14; }")
        
        self.details_panel = RemoteWidget()
        self.details_panel.setStyleSheet("QWidget { background-color: #0c0e14; }")
        self.details_panel.status_changed.connect(self.on_remote_status_changed)
        self.details_scroll.setWidget(self.details_panel)
        main_layout.addWidget(self.details_scroll, 1)
        
        root_layout.addWidget(main_content, 1)
        
        # --- Bottom Status Bar ---
        bottom_bar = QFrame()
        bottom_bar.setStyleSheet("""
            QFrame {
                background-color: #0c0e14;
                border-top: 1px solid #1e2533;
                padding: 4px 14px;
            }
        """)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(12)
        
        # Driver Status Check
        driver_status = "WinFsp Available" if platform.system() == "Windows" else "FUSE Available"
        driver_dot = QLabel(f"● {driver_status}")
        driver_dot.setFont(QFont("Segoe UI", 8))
        driver_dot.setStyleSheet("color: #10b981;")
        bottom_layout.addWidget(driver_dot)
        
        sep_b1 = QLabel("|")
        sep_b1.setStyleSheet("color: #334155;")
        bottom_layout.addWidget(sep_b1)
        
        conf_lbl = QLabel(f"Config: {(BASE_DIR / 'rclone.conf').name}")
        conf_lbl.setFont(QFont("Segoe UI", 8))
        conf_lbl.setStyleSheet("color: #64748b;")
        bottom_layout.addWidget(conf_lbl)
        
        bottom_layout.addStretch()
        
        self.lbl_active_processes = QLabel("Active Processes: 0")
        self.lbl_active_processes.setFont(QFont("Segoe UI", 8))
        self.lbl_active_processes.setStyleSheet("color: #94a3b8;")
        bottom_layout.addWidget(self.lbl_active_processes)
        
        sep_b2 = QLabel("|")
        sep_b2.setStyleSheet("color: #334155;")
        bottom_layout.addWidget(sep_b2)
        
        enc_lbl = QLabel("Encoding: UTF-8")
        enc_lbl.setFont(QFont("Segoe UI", 8))
        enc_lbl.setStyleSheet("color: #64748b;")
        bottom_layout.addWidget(enc_lbl)
        
        root_layout.addWidget(bottom_bar)
        
        # Populate initial remotes
        create_sample_file()
        self.refresh_remotes()
        
        # Global periodic refresh timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_processes)
        self.timer.start(2000)
        
        # Auto-mount on launch check
        QTimer.singleShot(500, self.auto_mount_launch_remotes)
        
        logger.info("MainWindow initialized")

    def _setup_tray(self):
        """Setup system tray icon and context menu"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("System tray is not available on this platform")
            return
        
        self.tray = QSystemTrayIcon(self)
        icon_path = get_icon_path()
        if icon_path and icon_path.exists():
            self.tray.setIcon(QIcon(str(icon_path)))
        else:
            from PySide6.QtWidgets import QStyle
            self.tray.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
            
        tray_menu = QMenu()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        tray_menu.addAction(quit_action)
        
        self.tray.setContextMenu(tray_menu)
        self.tray.show()

    def filter_remotes(self, text: str):
        """Filter list items by search query"""
        query = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if isinstance(widget, RemoteListItem):
                match = (not query) or (query in widget.name.lower()) or (query in widget.remote_id.lower())
                item.setHidden(not match)

    def refresh_remotes(self):
        """Scan remotes directory, instantiate controllers, and populate sidebar list"""
        self.list_widget.clear()
        self.controllers = {}
        
        files = list(REMOTES_DIR.glob("*.properties"))
        for f in files:
            if f.name.startswith("_"): 
                continue
            
            try:
                ctl = RemoteController(f)
                self.controllers[f.stem] = ctl
                
                # Create custom remote row
                item_widget = RemoteListItem(f.stem, ctl.get_info()["name"])
                item_widget.clicked.connect(self.on_remote_clicked)
                
                item = QListWidgetItem(self.list_widget)
                item.setSizeHint(QSize(250, 32))
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, item_widget)
            except Exception as e:
                logger.error(f"Error loading remote {f}: {e}")
        
        self.update_status_counts()
        self.update_remote_list_statuses()
        
        # Select first remote if available and nothing is selected
        if self.controllers and not self.details_panel.current_controller:
            first_id = next(iter(self.controllers.keys()))
            self.on_remote_clicked(first_id)
        
        logger.info(f"Loaded {len(self.controllers)} remotes")

    def update_status_counts(self):
        """Update active and inactive counter badges"""
        active = sum(1 for c in self.controllers.values() if c.is_running)
        inactive = len(self.controllers) - active
        self.badge_active.setText(f"{active} Active")
        self.badge_inactive.setText(f"{inactive} Inactive")
        self.lbl_active_processes.setText(f"Active Processes: {active}")

    def on_remote_status_changed(self):
        """Handle status change notification from RemoteWidget"""
        self.update_status_counts()
        self.update_remote_list_statuses()

    def update_remote_list_statuses(self):
        """Synchronize status dot indicators for all remotes in the sidebar list"""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if isinstance(widget, RemoteListItem):
                ctl = self.controllers.get(widget.remote_id)
                if ctl and ctl.is_running:
                    widget.set_status("running")
                else:
                    widget.set_status("stopped")

    def on_current_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        """Handle keyboard arrow navigation (Up/Down) on QListWidget"""
        if not current:
            return
        widget = self.list_widget.itemWidget(current)
        if isinstance(widget, RemoteListItem):
            self.on_remote_clicked(widget.remote_id)

    def eventFilter(self, watched, event):
        """Enable pressing Down/Enter in the search box to jump directly to list items"""
        if watched == self.search_filter and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Enter, Qt.Key_Return):
                self.list_widget.setFocus()
                if self.list_widget.count() > 0:
                    current = self.list_widget.currentItem()
                    if not current or current.isHidden():
                        for i in range(self.list_widget.count()):
                            item = self.list_widget.item(i)
                            if not item.isHidden():
                                self.list_widget.setCurrentItem(item)
                                break
                return True
        return super().eventFilter(watched, event)

    def on_remote_clicked(self, remote_id: str):
        """Handle remote selection, load details, and synchronize selection highlight"""
        if remote_id in self.controllers:
            ctl = self.controllers[remote_id]
            self.details_panel.load_remote(ctl)
            self.lbl_active_workspace.setText(f"{ctl.get_info()['name']} — Active Workspace")
            
            # Synchronize selection highlight
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                widget = self.list_widget.itemWidget(item)
                if isinstance(widget, RemoteListItem):
                    is_current = (widget.remote_id == remote_id)
                    widget.setSelectedState(is_current)
                    if is_current and self.list_widget.currentItem() != item:
                        self.list_widget.blockSignals(True)
                        self.list_widget.setCurrentItem(item)
                        self.list_widget.blockSignals(False)
            
            self.list_widget.setFocus()

    def on_add_remote(self):
        """Open remotes directory in file manager or prompt template creation"""
        if platform.system() == "Windows":
            os.startfile(str(REMOTES_DIR))
        else:
            subprocess.Popen(["xdg-open", str(REMOTES_DIR)])

    def on_open_config_folder(self):
        """Open application directory in file manager"""
        if platform.system() == "Windows":
            os.startfile(str(BASE_DIR))
        else:
            subprocess.Popen(["xdg-open", str(BASE_DIR)])

    def auto_mount_launch_remotes(self):
        """Mount remotes marked with auto_mount=True on application launch"""
        for r_id, ctl in self.controllers.items():
            if ctl.runtime_params.get("auto_mount", False) and not ctl.is_running:
                logger.info(f"Auto-mounting remote on launch: {r_id}")
                ctl.start_mount(ctl.runtime_params)
        self.update_status_counts()
        self.update_remote_list_statuses()
        self.details_panel.refresh_state()

    def check_processes(self):
        """Check for external process termination and update status badges"""
        for ctl in self.controllers.values():
            if ctl.process and ctl.process.state() == QProcess.NotRunning:
                if ctl.is_running:
                    ctl.is_running = False
                    
        self.update_status_counts()
        self.update_remote_list_statuses()
        if self.details_panel.current_controller:
            self.details_panel.refresh_state()

    def closeEvent(self, event):
        """Handle application close with prompt if mounts are active"""
        running_mounts = [name for name, ctl in self.controllers.items() if ctl.is_running]
        
        if running_mounts:
            reply = QMessageBox.question(
                self, 
                "Active Mounts Running", 
                f"There are {len(running_mounts)} active mount(s) running. Do you want to unmount all before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            elif reply == QMessageBox.Yes:
                for name in running_mounts:
                    self.controllers[name].stop_mount(clean_logs=True)
        
        logger.info("Application closing")
        event.accept()

# --- THEME & ENTRY POINT ---

def apply_modern_dark_theme(app):
    """Apply high-contrast modern dark palette and global stylesheet"""
    app.setStyle("Fusion")
    
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0c0e14"))
    palette.setColor(QPalette.WindowText, QColor("#e2e8f0"))
    palette.setColor(QPalette.Base, QColor("#0f131e"))
    palette.setColor(QPalette.AlternateBase, QColor("#171b26"))
    palette.setColor(QPalette.Text, QColor("#e2e8f0"))
    palette.setColor(QPalette.BrightText, QColor("#f43f5e"))
    palette.setColor(QPalette.PlaceholderText, QColor("#64748b"))
    palette.setColor(QPalette.Button, QColor("#171b26"))
    palette.setColor(QPalette.ButtonText, QColor("#e2e8f0"))
    palette.setColor(QPalette.Highlight, QColor("#10b981"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.Link, QColor("#38bdf8"))
    palette.setColor(QPalette.LinkVisited, QColor("#818cf8"))
    palette.setColor(QPalette.ToolTipBase, QColor("#171b26"))
    palette.setColor(QPalette.ToolTipText, QColor("#e2e8f0"))
    app.setPalette(palette)
    
    # Global scrollbars stylesheet strictly following AGENTS.md rules
    app.setStyleSheet("""
        QToolTip {
            background-color: #171b26;
            color: #ffffff;
            border: 1px solid #283042;
            border-radius: 4px;
            padding: 6px;
        }
        QScrollBar:vertical {
            background: #0f131e;
            width: 10px;
            margin: 0px;
            border: none;
        }
        QScrollBar::handle:vertical {
            background: #283042;
            border-radius: 5px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover {
            background: #3b82f6;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            border: none;
            background: none;
            height: 0px;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }
        QScrollBar:horizontal {
            background: #0f131e;
            height: 10px;
            margin: 0px;
            border: none;
        }
        QScrollBar::handle:horizontal {
            background: #283042;
            border-radius: 5px;
            min-width: 24px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #3b82f6;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            border: none;
            background: none;
            width: 0px;
        }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
            background: none;
        }
    """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_modern_dark_theme(app)
    
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("RcloneManager")
    
    window = MainWindow()
    window.show()
    
    logger.info(f"Application started - {APP_NAME} v{VERSION}")
    sys.exit(app.exec())
