import sys
import os
import shutil
import signal
import json
import configparser
import platform
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QListWidget, QListWidgetItem, QLabel, 
                               QPushButton, QGroupBox, QComboBox, QLineEdit, 
                               QPlainTextEdit, QSplitter, QMessageBox, QCheckBox, 
                               QFormLayout, QFrame, QStyleFactory, QScrollArea,
                               QFileDialog, QSystemTrayIcon, QMenu)
from PySide6.QtCore import Qt, QProcess, QTimer, Slot, Signal, QSize, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QIcon, QAction, QColor, QPalette, QFont, QPixmap, QPainter, QLinearGradient

# --- CONFIGURAZIONE GLOBALE ---
APP_NAME = "Rclone Mount Manager"
VERSION = "1.0.0"

def get_base_dir() -> Path:
    """
    Cartella 'portabile' dell'app:
    - In sviluppo: cartella dello script
    - In exe (Nuitka/PyInstaller): cartella dell'eseguibile
    """
    if globals().get("__compiled__", False) or getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()

REMOTES_DIR = BASE_DIR / "remotes"
CACHE_DIR   = BASE_DIR / "cache"
LOGS_DIR    = BASE_DIR / "logs"

RCLONE_EXE = "rclone.exe" if platform.system() == "Windows" else "rclone"

# --- Logging (prima configuri, poi usi logger) ---
LOGS_DIR.mkdir(parents=True, exist_ok=True)
APP_LOG = LOGS_DIR / "app.log"
LOG_MAX_SIZE = 2 * 1024 * 1024  # 2MB
LOG_BACKUP_COUNT = 6

logging.basicConfig(
    handlers=[RotatingFileHandler(APP_LOG, maxBytes=LOG_MAX_SIZE, backupCount=LOG_BACKUP_COUNT)],
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Assicuriamo che le directory esistano
for d in [REMOTES_DIR, CACHE_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- UTILS ---
def get_rclone_path():
    """Cerca rclone nella cartella locale o nel PATH"""
    local_bin = BASE_DIR / RCLONE_EXE
    if local_bin.exists():
        return str(local_bin)
    return shutil.which("rclone") or RCLONE_EXE

# Log diagnostici (ora logger e get_rclone_path esistono)
logger.info(f"BASE_DIR = {BASE_DIR}")
logger.info(f"REMOTES_DIR = {REMOTES_DIR}")
logger.info(f"RCLONE PATH = {get_rclone_path()}")


# --- UTILS ---
def get_rclone_path():
    """Cerca rclone nella cartella locale o nel PATH"""
    local_bin = BASE_DIR / RCLONE_EXE
    if local_bin.exists():
        return str(local_bin)
    return shutil.which("rclone") or RCLONE_EXE

def create_sample_file():
    """Crea il file _sample.properties se non esiste"""
    sample_path = REMOTES_DIR / "_sample.properties"
    if not sample_path.exists():
        content = """# ============================================
# SAMPLE REMOTE CONFIGURATION
# ============================================
# Questo è un file di esempio per configurare un nuovo remote.
# Copia questo file, rinominalo (es: pcloud.properties) e modifica i valori.

[General]
# Nome visualizzato nell'interfaccia
name = Sample Remote

# Nome del remote in rclone.conf (deve finire con :)
remote_name = remote:

# Mountpoint: 
# - Windows: usa "auto" per lettera automatica, oppure "X:", "Y:", etc.
# - Linux: percorso assoluto come /mnt/myremote
mountpoint = auto

# Nome volume (opzionale, consigliato per Windows)
volname = MyRemoteVolume

[Rclone]
# Percorso al file di configurazione rclone
# Usa path relativo (es: rclone.conf) o assoluto
# Se non specificato, cerca rclone.conf nella cartella dell'app
config_path = rclone.conf

# Flag extra per rclone mount (opzionali)
# Esempio: --links --network-mode --poll-interval=10s
extra_flags = --links

[Defaults]
# Modalità cache VFS
# Opzioni: off, minimal, writes, full (consigliato: full)
vfs-cache-mode = full

# Età massima cache (esempi: 30m, 1h, 24h)
vfs-cache-max-age = 30m

# Tempo cache directory (esempi: 1m, 5m, 30m)
dir-cache-time = 1m

# ============================================
# FINE CONFIGURAZIONE
# ============================================
"""
        with open(sample_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info("Created sample configuration file")

# --- LOGICA CORE (CONTROLLER) ---

class RemoteController:
    """Gestisce logica, stato e processo di un singolo remote"""
    
    def __init__(self, config_file):
        self.config_file = config_file
        self.config_id = config_file.stem
        self.process = None
        self.is_running = False
        self.mount_timestamp = None
        self.error_message = ""
        
        # Carica configurazione statica
        self.cfg = configparser.ConfigParser()
        self.cfg.read(config_file, encoding='utf-8')
        
        # Percorsi specifici per questo remote
        self.remote_cache = CACHE_DIR / self.config_id
        self.remote_log_dir = LOGS_DIR / self.config_id
        self.log_file = self.remote_log_dir / "rclone.log"
        
        # Carica overrides salvati
        self.overrides_file = REMOTES_DIR / f"{self.config_id}.override.json"
        self.runtime_params = self._load_defaults()
        
        logger.info(f"Initialized remote controller: {self.config_id}")
        
    def _load_defaults(self):
        """Carica defaults dal file properties, poi sovrascrive con JSON se esiste"""
        params = {
            "vfs-cache-mode": self.cfg.get("Defaults", "vfs-cache-mode", fallback="full"),
            "vfs-cache-max-age": self.cfg.get("Defaults", "vfs-cache-max-age", fallback="30m"),
            "dir-cache-time": self.cfg.get("Defaults", "dir-cache-time", fallback="1m"),
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
        self.runtime_params = params
        with open(self.overrides_file, 'w', encoding='utf-8') as f:
            json.dump(params, f, indent=4)
        logger.info(f"Saved overrides for {self.config_id}")

    def get_info(self):
        return {
            "name": self.cfg.get("General", "name", fallback=self.config_id),
            "remote": self.cfg.get("General", "remote_name"),
            "mountpoint": self.cfg.get("General", "mountpoint", fallback="auto")
        }

    def start_mount(self, params_ui):
        if self.is_running:
            logger.warning(f"Mount already running for {self.config_id}")
            return

        # Aggiorna e salva parametri UI
        self.save_overrides(params_ui)
        
        # Prepara directory
        self.remote_cache.mkdir(exist_ok=True)
        self.remote_log_dir.mkdir(exist_ok=True)

        cmd = [get_rclone_path(), "mount"]
        
        # Remote e Mountpoint
        remote = self.cfg.get("General", "remote_name")
        mountpoint = self.cfg.get("General", "mountpoint", fallback="auto")
        
        # Gestione Mountpoint Windows
        if platform.system() == "Windows" and mountpoint.lower() == "auto":
             cmd.extend([remote, "*"]) # Assegna lettera automatica
        else:
             cmd.extend([remote, mountpoint])

        # Config File - Priorità: config_path specificato > rclone.conf locale > rclone.conf sistema
        conf_path = self.cfg.get("Rclone", "config_path", fallback=None)
        if conf_path:
            # Se relativo, risolvi rispetto alla base dir
            if not os.path.isabs(conf_path):
                conf_path = str(BASE_DIR / conf_path)
            if Path(conf_path).exists():
                cmd.append(f"--config={conf_path}")
            else:
                logger.warning(f"Config file not found: {conf_path}, using default")
        elif (BASE_DIR / "rclone.conf").exists():
            cmd.append(f"--config={str(BASE_DIR / 'rclone.conf')}")
        # Altrimenti usa il config di sistema (default di rclone)

        # Runtime Params
        cmd.append(f"--vfs-cache-mode={params_ui['vfs-cache-mode']}")
        cmd.append(f"--vfs-cache-max-age={params_ui['vfs-cache-max-age']}")
        cmd.append(f"--dir-cache-time={params_ui['dir-cache-time']}")
        cmd.append(f"--cache-dir={str(self.remote_cache)}")
        cmd.append(f"--log-file={str(self.log_file)}")
        cmd.append("--verbose")

        # Volname
        volname = self.cfg.get("General", "volname", fallback=None)
        if volname:
            cmd.append(f"--volname={volname}")

        # Extra Flags dal properties
        extras = self.cfg.get("Rclone", "extra_flags", fallback="")
        if extras:
            cmd.extend(extras.split())

        cmd_str = ' '.join(cmd)
        logger.info(f"Executing mount command for {self.config_id}: {cmd_str}")
        print(f"[MOUNT] {cmd_str}")

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
        
        # Tentativo Graceful
        if platform.system() == "Windows":
            # Windows: terminate con fallback a taskkill
            self.process.terminate()
            if not self.process.waitForFinished(3000):
                logger.warning(f"Terminate timeout for {self.config_id}, using taskkill")
                try:
                    subprocess.run(f"taskkill /F /T /PID {self.process.processId()}", 
                                   shell=True, check=True)
                except subprocess.CalledProcessError as e:
                    logger.error(f"Taskkill failed: {e}")
        else:
            # Linux: fusermount
            mountpoint = self.cfg.get("General", "mountpoint")
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
        
        # Cleanup
        self._cleanup(clean_logs)
        logger.info(f"Mount stopped for {self.config_id}")

    def _cleanup(self, clean_logs):
        """Pulisce cache e log con safety checks"""
        logger.info(f"Cleaning up {self.config_id}... (clean_logs={clean_logs})")
        
        # Safety Check: Assicurarsi che stiamo cancellando dentro la cartella dell'app
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
        """Ritorna il mountpoint effettivo"""
        mp = self.cfg.get("General", "mountpoint", fallback="auto")
        if platform.system() == "Windows" and mp.lower() == "auto":
            return "Auto-assigned"
        return mp

# --- MODERN UI COMPONENTS ---

class StatusIndicator(QLabel):
    """Indicatore di stato moderno con colore e animazione"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.status = "stopped"
        self.update_status("stopped")
        
    def update_status(self, status):
        self.status = status
        colors = {
            "running": "#4CAF50",
            "stopped": "#757575",
            "error": "#F44336"
        }
        color = colors.get(status, "#757575")
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                border-radius: 6px;
                border: 2px solid rgba(255, 255, 255, 0.2);
            }}
        """)

class ModernButton(QPushButton):
    """Pulsante moderno con hover effects"""
    def __init__(self, text, color="#2196F3", parent=None):
        super().__init__(text, parent)
        self.base_color = color
        self.setMinimumHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        self._update_style()
        
    def _update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self.base_color}, stop:1 {self._darken(self.base_color)});
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-weight: bold;
                font-size: 12px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self._lighten(self.base_color)}, stop:1 {self.base_color});
            }}
            QPushButton:pressed {{
                background: {self._darken(self.base_color)};
            }}
            QPushButton:disabled {{
                background: #424242;
                color: #757575;
            }}
        """)
    
    def _lighten(self, color, factor=1.2):
        c = QColor(color)
        h, s, v, a = c.getHsv()
        v = min(255, int(v * factor))
        c.setHsv(h, s, v, a)
        return c.name()
    
    def _darken(self, color, factor=0.8):
        c = QColor(color)
        h, s, v, a = c.getHsv()
        v = int(v * factor)
        c.setHsv(h, s, v, a)
        return c.name()

class ModernCard(QFrame):
    """Card moderno con ombra"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #2b2b2b;
                border-radius: 12px;
                border: 1px solid #3a3a3a;
                padding: 16px;
            }
        """)

class RemoteListItem(QWidget):
    """Widget personalizzato per item della lista remotes"""
    clicked = Signal(str)
    
    def __init__(self, remote_id, name, parent=None):
        super().__init__(parent)
        self.remote_id = remote_id
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        
        # Status indicator
        self.status_indicator = StatusIndicator()
        layout.addWidget(self.status_indicator)
        
        # Icon
        icon_label = QLabel("💾")
        icon_label.setFont(QFont("Segoe UI Emoji", 12))
        layout.addWidget(icon_label)
        
        # Name
        name_label = QLabel(name)
        name_label.setFont(QFont("Segoe UI", 10, QFont.Medium))
        name_label.setStyleSheet("color: #ffffff;")
        layout.addWidget(name_label, 1)
        
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border-radius: 8px;
            }
            QWidget:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
        """)
        
    def mousePressEvent(self, event):
        self.clicked.emit(self.remote_id)
        super().mousePressEvent(event)

# --- MAIN PANELS ---

class RemoteWidget(QWidget):
    """Pannello dettagli remote (versione moderna)"""
    
    def __init__(self):
        super().__init__()
        self.current_controller = None
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.update_log_view)
        self.log_timer.setInterval(1000)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # --- Header Card ---
        header_card = ModernCard()
        header_layout = QVBoxLayout(header_card)
        
        self.lbl_name = QLabel("Select a remote")
        self.lbl_name.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_name.setStyleSheet("color: #ffffff;")
        header_layout.addWidget(self.lbl_name)
        
        status_layout = QHBoxLayout()
        self.status_indicator = StatusIndicator()
        status_layout.addWidget(self.status_indicator)
        
        self.lbl_status = QLabel("Status: Not Selected")
        self.lbl_status.setFont(QFont("Segoe UI", 10))
        self.lbl_status.setStyleSheet("color: #b0b0b0;")
        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch()
        
        self.lbl_timestamp = QLabel()
        self.lbl_timestamp.setFont(QFont("Segoe UI", 9))
        self.lbl_timestamp.setStyleSheet("color: #808080;")
        status_layout.addWidget(self.lbl_timestamp)
        
        header_layout.addLayout(status_layout)
        layout.addWidget(header_card)
        
        # --- Settings Card ---
        settings_card = ModernCard()
        settings_layout = QVBoxLayout(settings_card)
        
        settings_title = QLabel("⚙️ Mount Settings")
        settings_title.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        settings_title.setStyleSheet("color: #ffffff; margin-bottom: 8px;")
        settings_layout.addWidget(settings_title)
        
        self.group_settings = QGroupBox()
        self.group_settings.setStyleSheet("""
            QGroupBox {
                border: none;
                background: transparent;
            }
        """)
        form_layout = QFormLayout(self.group_settings)
        form_layout.setSpacing(15)
        form_layout.setContentsMargins(0, 0, 0, 0)
        
        # VFS Cache Mode
        cache_label = QLabel("VFS Cache Mode:")
        cache_label.setStyleSheet("color: #e0e0e0; font-weight: 500;")
        self.combo_cache_mode = QComboBox()
        self.combo_cache_mode.addItems(["off", "minimal", "writes", "full"])
        self.combo_cache_mode.setCurrentText("full")
        self.combo_cache_mode.setStyleSheet("""
            QComboBox {
                background-color: #1e1e1e;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 8px 12px;
                color: #ffffff;
                min-height: 32px;
            }
            QComboBox:hover {
                border-color: #2196F3;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2b2b;
                selection-background-color: #2196F3;
                color: #ffffff;
                border: 1px solid #4a4a4a;
            }
        """)
        form_layout.addRow(cache_label, self.combo_cache_mode)
        
        # Cache Max Age
        age_label = QLabel("Cache Max Age:")
        age_label.setStyleSheet("color: #e0e0e0; font-weight: 500;")
        self.edit_cache_age = QLineEdit("30m")
        self.edit_cache_age.setPlaceholderText("e.g., 30m, 1h, 24h")
        self._style_line_edit(self.edit_cache_age)
        form_layout.addRow(age_label, self.edit_cache_age)
        
        # Dir Cache Time
        dir_label = QLabel("Dir Cache Time:")
        dir_label.setStyleSheet("color: #e0e0e0; font-weight: 500;")
        self.edit_dir_cache = QLineEdit("1m")
        self.edit_dir_cache.setPlaceholderText("e.g., 1m, 5m, 30m")
        self._style_line_edit(self.edit_dir_cache)
        form_layout.addRow(dir_label, self.edit_dir_cache)
        
        settings_layout.addWidget(self.group_settings)
        layout.addWidget(settings_card)
        
        # --- Action Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        self.btn_mount = ModernButton("🚀 MOUNT", "#4CAF50")
        self.btn_mount.clicked.connect(self.on_mount)
        btn_layout.addWidget(self.btn_mount)
        
        self.btn_unmount = ModernButton("⏹️ UNMOUNT", "#F44336")
        self.btn_unmount.setEnabled(False)
        self.btn_unmount.clicked.connect(self.on_unmount)
        btn_layout.addWidget(self.btn_unmount)
        
        layout.addLayout(btn_layout)
        
        # --- Utility Buttons ---
        util_layout = QHBoxLayout()
        util_layout.setSpacing(8)
        
        self.btn_open_mount = QPushButton("📂 Open Mount")
        self.btn_open_mount.setEnabled(False)
        self.btn_open_mount.clicked.connect(self.on_open_mount)
        self._style_util_button(self.btn_open_mount)
        util_layout.addWidget(self.btn_open_mount)
        
        self.btn_open_logs = QPushButton("📄 Open Logs")
        self.btn_open_logs.clicked.connect(self.on_open_logs)
        self._style_util_button(self.btn_open_logs)
        util_layout.addWidget(self.btn_open_logs)
        
        self.btn_open_cache = QPushButton("💾 Open Cache")
        self.btn_open_cache.clicked.connect(self.on_open_cache)
        self._style_util_button(self.btn_open_cache)
        util_layout.addWidget(self.btn_open_cache)
        
        self.btn_show_command = QPushButton("⌨️ Show Command")
        self.btn_show_command.clicked.connect(self.on_show_command)
        self._style_util_button(self.btn_show_command)
        util_layout.addWidget(self.btn_show_command)
        
        layout.addLayout(util_layout)
        
        # --- Options ---
        self.chk_clean_logs = QCheckBox("🗑️ Clean logs after unmount")
        self.chk_clean_logs.setChecked(True)
        self.chk_clean_logs.setStyleSheet("""
            QCheckBox {
                color: #e0e0e0;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #4a4a4a;
                background-color: #1e1e1e;
            }
            QCheckBox::indicator:checked {
                background-color: #2196F3;
                border-color: #2196F3;
            }
        """)
        layout.addWidget(self.chk_clean_logs)
        
        # --- Log Viewer Card ---
        log_card = ModernCard()
        log_layout = QVBoxLayout(log_card)
        
        log_title = QLabel("📋 Live Log (Last 20 lines)")
        log_title.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        log_title.setStyleSheet("color: #ffffff; margin-bottom: 8px;")
        log_layout.addWidget(log_title)
        
        self.log_viewer = QPlainTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMinimumHeight(200)
        self.log_viewer.setFont(QFont("Consolas", 10))
        self.log_viewer.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 12px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
        """)
        log_layout.addWidget(self.log_viewer)
        
        layout.addWidget(log_card)
        layout.addStretch()
        
    def _style_line_edit(self, edit):
        edit.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e1e;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 8px 12px;
                color: #ffffff;
                min-height: 20px;
            }
            QLineEdit:focus {
                border-color: #2196F3;
            }
        """)
    
    def _style_util_button(self, btn):
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 8px 16px;
                color: #e0e0e0;
                font-size: 10px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #2196F3;
            }
            QPushButton:pressed {
                background-color: #1e1e1e;
            }
            QPushButton:disabled {
                background-color: #1e1e1e;
                color: #757575;
                border-color: #2a2a2a;
            }
        """)
        
    def load_remote(self, controller: RemoteController):
        self.current_controller = controller
        info = controller.get_info()
        self.lbl_name.setText(f"💾 {info['name']}")
        
        # Load params
        params = controller.runtime_params
        self.combo_cache_mode.setCurrentText(params.get("vfs-cache-mode", "full"))
        self.edit_cache_age.setText(params.get("vfs-cache-max-age", "30m"))
        self.edit_dir_cache.setText(params.get("dir-cache-time", "1m"))
        
        self.refresh_state()

    def refresh_state(self):
        if not self.current_controller:
            return
            
        running = self.current_controller.is_running
        self.btn_mount.setEnabled(not running)
        self.btn_unmount.setEnabled(running)
        self.btn_open_mount.setEnabled(running)
        self.group_settings.setEnabled(not running)
        
        if running:
            self.status_indicator.update_status("running")
            pid = self.current_controller.process.processId() if self.current_controller.process else "N/A"
            self.lbl_status.setText(f"Status: 🟢 RUNNING (PID: {pid})")
            self.lbl_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
            
            if self.current_controller.mount_timestamp:
                ts = self.current_controller.mount_timestamp.strftime("%H:%M:%S")
                self.lbl_timestamp.setText(f"Mounted at: {ts}")
            
            if not self.log_timer.isActive():
                self.log_timer.start()
        else:
            self.status_indicator.update_status("stopped")
            self.lbl_status.setText("Status: ⚫ STOPPED")
            self.lbl_status.setStyleSheet("color: #757575;")
            self.lbl_timestamp.setText("")
            self.log_timer.stop()

    def on_mount(self):
        if not self.current_controller: 
            return
        
        # Validazione base
        rclone_path = get_rclone_path()
        if not shutil.which(rclone_path):
            QMessageBox.critical(self, "❌ Error", 
                f"Rclone executable not found: {rclone_path}\n\n"
                "Please install rclone or place it in the application folder.")
            return

        params = {
            "vfs-cache-mode": self.combo_cache_mode.currentText(),
            "vfs-cache-max-age": self.edit_cache_age.text(),
            "dir-cache-time": self.edit_dir_cache.text()
        }
        
        try:
            self.current_controller.start_mount(params)
            if self.current_controller.process:
                self.current_controller.process.finished.connect(self.on_process_finished)
            self.refresh_state()
            logger.info(f"Mount initiated for {self.current_controller.config_id}")
        except Exception as e:
            logger.error(f"Mount error: {e}")
            QMessageBox.critical(self, "❌ Mount Error", str(e))

    def on_unmount(self):
        if not self.current_controller: 
            return
        self.current_controller.stop_mount(clean_logs=self.chk_clean_logs.isChecked())
        self.refresh_state()

    def on_process_finished(self):
        self.refresh_state()
        self.log_viewer.appendPlainText("\n--- ⚠️ PROCESS TERMINATED ---\n")
        logger.info(f"Process finished for {self.current_controller.config_id}")

    def on_open_mount(self):
        if not self.current_controller or not self.current_controller.is_running:
            return
        
        mountpoint = self.current_controller.get_mountpoint()
        if platform.system() == "Windows":
            if mountpoint == "Auto-assigned":
                QMessageBox.information(self, "ℹ️ Info", 
                    "Cannot open auto-assigned drive. Check drive letters in File Explorer.")
            else:
                os.startfile(mountpoint)
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
        
        # Ricostruisce il comando che verrebbe eseguito
        params = {
            "vfs-cache-mode": self.combo_cache_mode.currentText(),
            "vfs-cache-max-age": self.edit_cache_age.text(),
            "dir-cache-time": self.edit_dir_cache.text()
        }
        
        cmd = [get_rclone_path(), "mount"]
        remote = self.current_controller.cfg.get("General", "remote_name")
        mountpoint = self.current_controller.cfg.get("General", "mountpoint", fallback="auto")
        
        if platform.system() == "Windows" and mountpoint.lower() == "auto":
            cmd.extend([remote, "*"])
        else:
            cmd.extend([remote, mountpoint])
        
        cmd.append(f"--vfs-cache-mode={params['vfs-cache-mode']}")
        cmd.append(f"--vfs-cache-max-age={params['vfs-cache-max-age']}")
        cmd.append(f"--dir-cache-time={params['dir-cache-time']}")
        cmd.append(f"--cache-dir={str(self.current_controller.remote_cache)}")
        cmd.append(f"--log-file={str(self.current_controller.log_file)}")
        cmd.append("--verbose")
        
        volname = self.current_controller.cfg.get("General", "volname", fallback=None)
        if volname:
            cmd.append(f"--volname={volname}")
        
        cmd_str = ' '.join(cmd)
        
        msg = QMessageBox(self)
        msg.setWindowTitle("⌨️ Mount Command")
        msg.setText("The following command will be executed:")
        msg.setDetailedText(cmd_str)
        msg.setIcon(QMessageBox.Information)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #2b2b2b;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        msg.exec()

    def update_log_view(self):
        if not self.current_controller or not self.current_controller.log_file.exists():
            return
            
        try:
            with open(self.current_controller.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                last_lines = lines[-20:] if len(lines) > 20 else lines
                self.log_viewer.setPlainText("".join(last_lines))
                self.log_viewer.verticalScrollBar().setValue(self.log_viewer.verticalScrollBar().maximum())
        except Exception as e:
            logger.error(f"Error reading log: {e}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"💾 {APP_NAME} v{VERSION}")
        self.resize(1200, 500)
        self.controllers = {}
        
        # Setup System Tray (se supportato)
        self._setup_tray()
        
        # Main Widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Left Sidebar ---
        sidebar = QFrame()
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a1a, stop:1 #252526);
                border-right: 1px solid #3a3a3a;
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        
        # Sidebar Header
        header = QWidget()
        header.setStyleSheet("background: #1a1a1a; border-bottom: 1px solid #3a3a3a;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel("💾 Remotes")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #ffffff; border: none;")
        header_layout.addWidget(title)
        
        subtitle = QLabel("Manage your cloud mounts")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setStyleSheet("color: #808080; border: none;")
        header_layout.addWidget(subtitle)
        
        sidebar_layout.addWidget(header)
        
        # Remote List
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
                padding: 8px;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 4px 0px;
            }
            QListWidget::item:selected {
                background: rgba(33, 150, 243, 0.2);
                border-radius: 8px;
            }
        """)
        self.list_widget.setSpacing(4)
        sidebar_layout.addWidget(self.list_widget)
        
        # Sidebar Footer
        footer = QWidget()
        footer.setStyleSheet("background: #1a1a1a; border-top: 1px solid #3a3a3a;")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.clicked.connect(self.refresh_remotes)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 10px;
                color: #e0e0e0;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #2196F3;
            }
        """)
        footer_layout.addWidget(self.btn_refresh)
        
        sidebar_layout.addWidget(footer)
        
        main_layout.addWidget(sidebar)
        
        # --- Right Panel (Details) ---
        self.details_panel = RemoteWidget()
        self.details_panel.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e1e1e, stop:1 #252526);
            }
        """)
        main_layout.addWidget(self.details_panel, 1)
        
        # Load data
        create_sample_file()
        self.refresh_remotes()
        
        # Global Refresh Timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_processes)
        self.timer.start(2000)
        
        logger.info("MainWindow initialized")

    def _setup_tray(self):
        """Setup system tray icon"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        
        self.tray = QSystemTrayIcon(self)
        # TODO: Add custom icon
        # self.tray.setIcon(QIcon("icon.png"))
        
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

    def refresh_remotes(self):
        self.list_widget.clear()
        self.controllers = {}
        
        files = list(REMOTES_DIR.glob("*.properties"))
        for f in files:
            if f.name.startswith("_"): 
                continue
            
            try:
                ctl = RemoteController(f)
                self.controllers[f.stem] = ctl
                
                # Create custom widget item
                item_widget = RemoteListItem(f.stem, ctl.get_info()["name"])
                item_widget.clicked.connect(self.on_remote_clicked)
                
                item = QListWidgetItem(self.list_widget)
                item.setSizeHint(item_widget.sizeHint())
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, item_widget)
            except Exception as e:
                logger.error(f"Error loading remote {f}: {e}")
        
        logger.info(f"Loaded {len(self.controllers)} remotes")

    def on_remote_clicked(self, remote_id):
        if remote_id in self.controllers:
            self.details_panel.load_remote(self.controllers[remote_id])
            logger.info(f"Selected remote: {remote_id}")

    def check_processes(self):
        """Check if processes died externally and update UI"""
        if self.details_panel.current_controller:
            proc = self.details_panel.current_controller.process
            if proc and proc.state() == QProcess.NotRunning:
                if self.details_panel.current_controller.is_running:
                    self.details_panel.current_controller.is_running = False
                    self.details_panel.refresh_state()

    def closeEvent(self, event):
        """Handle window close"""
        # Check if any mounts are running
        running_mounts = [name for name, ctl in self.controllers.items() if ctl.is_running]
        
        if running_mounts:
            reply = QMessageBox.question(
                self, 
                "Active Mounts", 
                f"There are {len(running_mounts)} active mount(s). Do you want to unmount all before closing?",
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
    """Apply modern dark theme with custom palette"""
    app.setStyle("Fusion")
    
    palette = QPalette()
    # Background colors
    palette.setColor(QPalette.Window, QColor("#1e1e1e"))
    palette.setColor(QPalette.WindowText, QColor("#ffffff"))
    palette.setColor(QPalette.Base, QColor("#252526"))
    palette.setColor(QPalette.AlternateBase, QColor("#2b2b2b"))
    
    # Text colors
    palette.setColor(QPalette.Text, QColor("#ffffff"))
    palette.setColor(QPalette.BrightText, QColor("#ff5252"))
    palette.setColor(QPalette.PlaceholderText, QColor("#808080"))
    
    # Button colors
    palette.setColor(QPalette.Button, QColor("#2b2b2b"))
    palette.setColor(QPalette.ButtonText, QColor("#ffffff"))
    
    # Selection colors
    palette.setColor(QPalette.Highlight, QColor("#2196F3"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    
    # Links
    palette.setColor(QPalette.Link, QColor("#2196F3"))
    palette.setColor(QPalette.LinkVisited, QColor("#9C27B0"))
    
    # Tooltips
    palette.setColor(QPalette.ToolTipBase, QColor("#2b2b2b"))
    palette.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    
    app.setPalette(palette)
    
    # Global stylesheet
    app.setStyleSheet("""
        QToolTip {
            background-color: #2b2b2b;
            color: #ffffff;
            border: 1px solid #4a4a4a;
            border-radius: 4px;
            padding: 6px;
        }
        QScrollBar:vertical {
            background: #1e1e1e;
            width: 12px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #4a4a4a;
            border-radius: 6px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background: #5a5a5a;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QScrollBar:horizontal {
            background: #1e1e1e;
            height: 12px;
            margin: 0px;
        }
        QScrollBar::handle:horizontal {
            background: #4a4a4a;
            border-radius: 6px;
            min-width: 20px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #5a5a5a;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
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
