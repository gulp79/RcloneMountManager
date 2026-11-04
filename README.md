# 💾 Rclone Mount Manager

A modern, high-contrast dark-themed desktop application for managing rclone mounts with an intuitive GUI.

![Version](https://img.shields.io/badge/version-1.1.0-blue)
![Python](https://img.shields.io/badge/python-3.12+-green)
![Qt](https://img.shields.io/badge/Qt-PySide6-brightgreen)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)
[![GitHub release](https://img.shields.io/github/v/release/gulp79/RcloneMountManager?include_prereleases)](https://github.com/gulp79/RcloneMountManager/releases/latest)
![Total Downloads](https://img.shields.io/github/downloads/gulp79/RcloneMountManager/total)

<img width="958" height="515" alt="Rclone Mount Manager UI" src="https://github.com/user-attachments/assets/7a202b4d-cc9f-47d9-860e-ef8bf79fa62f" />

---

## ✨ Features

### Core Functionality
- 📂 **Direct `rclone.conf` Integration**: Available remotes are discovered and populated automatically from your existing `rclone.conf` without manual configuration duplication.
- 🚀 **One-Click Operations**: Fast Mount (green gradient) and Unmount (red alert) controls with process tracking.
- ⚙️ **Collapsible Performance Tuning**: Real-time adjustment of VFS Cache Mode, Cache Max Age, Directory Cache Time, Read Ahead Buffer, Bandwidth Limit, and Extra CLI Flags without touching raw config files.
- 🔄 **Runtime JSON Overrides & Friendly Aliases**: Custom friendly names and parameter edits in the GUI persist automatically per remote (`remotes/<id>.override.json`) with a single-click "Reset to Defaults" option.
- ➕ **Built-in Remote Management**: Use the "+ Add Remote" button to directly launch interactive `rclone config` in a terminal.
- 💾 **Drive Letter Detection (Windows)**: Automatically scans Windows for unused drive letters with `auto` (`*`) fallback.
- 📊 **VFS Cache Monitoring**: Real-time calculation and display of on-disk cached data size.
- 🧹 **Automatic Cleanup**: Clean cache and log directories automatically after unmount.
- 🕒 **Auto-Mount on Launch**: Option to automatically mount selected remotes when the app starts.

### Sleek Modern Dark UI & UX
- 🎨 **Deep Dark Palette**: Modern UI (`#0c0e14` / `#171b26`) designed for high contrast and readability.
- 🔍 **Instant Search & Filter**: Real-time remote filtering with `Ctrl+F` shortcut and automatic focus switching.
- ⌨️ **Keyboard Navigation**: Seamlessly navigate through remotes using **Up** / **Down** arrow keys.
- 🟢 **Live Status Indicators**: Real-time emerald green dots for running mounts, slate gray for stopped remotes, and active/inactive count badges.
- 📋 **Terminal-Style Live Log Stream**: Consolas log viewer featuring syntax highlighting (`[INFO]`, `[NOTICE]`, `[DEBUG]`, `[ERROR]`), auto-scroll toggle, copy to clipboard, and clear controls.
- 🖥️ **System Tray Integration**: Minimize to tray with context menu for unobtrusive background operation.

---

## 📋 Requirements

### System Requirements
- **Python**: 3.12 or higher
- **rclone**: Installed and added to PATH (or placed in the application directory).
  - *Optional*: Use [rclone-extra](https://github.com/gulp79/rclone-extra) for native Teldrive and Terabox support.
- **Windows**: [WinFsp](https://winfsp.dev/rel/) (required for mounting on Windows).
- **Linux**: FUSE support (`fuse` / `fuse3`).

### Python Dependencies
```
PySide6>=6.5.0
```

---

## 🚀 Installation & Setup

### 1. Configure rclone
Run the interactive rclone setup to configure your storage remotes:
```bash
rclone config
```

### 2. Download or Clone
```bash
git clone https://github.com/gulp79/RcloneMountManager.git
cd RcloneMountManager
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Setup Configuration File
Place your `rclone.conf` into the application root directory (or keep it in the default system location `~/.config/rclone/rclone.conf` / `%APPDATA%\rclone\rclone.conf`).

### 5. Launch the Application
```bash
python RcloneMountManager.py
```

---

## 📁 Project Structure

```
RcloneMountManager/
├── RcloneMountManager.py   # Single-file application (GUI + controller logic)
├── test_gui.py             # Headless unit test suite (PySide6 offscreen)
├── requirements.txt        # Python dependencies
├── RcloneMountManager.spec # PyInstaller build specification
├── icon.ico                # Application window & tray icon
├── rclone.conf             # (Optional) Portable rclone config
├── remotes/
│   └── <id>.override.json  # Runtime GUI overrides (per-remote)
├── cache/<id>/             # VFS cache directories per remote
└── logs/
    ├── app.log             # Rotating application log (UTF-8, 2 MB × 6 files)
    └── <id>/rclone.log     # Individual mount logs
```

---

## 🔧 Remote Configuration & Overrides

Remotes are read dynamically from your active **`rclone.conf`**.

### Configuration Resolution
The application locates `rclone.conf` using the following search order:
1. `rclone.conf` placed in the application root directory (portable mode).
2. Environment variable `RCLONE_CONFIG`.
3. Standard OS default paths:
   - **Windows**: `%APPDATA%\rclone\rclone.conf`
   - **Linux / macOS**: `~/.config/rclone/rclone.conf`

To add, edit, or remove remotes, simply run:
```bash
rclone config
```
or click the **"+ Add Remote"** button in the sidebar footer.

### Runtime Overrides (`remotes/<id>.override.json`)
You do not need to write or maintain `.properties` files for each remote.
- **Global Defaults**: Mount parameters start with high-performance defaults (`vfs-cache-mode = full`, `mountpoint = auto`, etc.).
- **Friendly Name (Alias)**: Set a custom display name in the settings panel (*Friendly Name (Alias)*) to customize the label shown in the sidebar list and top workspace bar without renaming your remote in `rclone.conf`.
- **Automatic Persistence**: When you change settings, drive letters, or friendly names, your configuration is saved automatically to `remotes/<id>.override.json`.
- **Reset to Defaults**: Clicking **Reset to Defaults** reverts the fields to the built-in global defaults.

---

## 🎮 Keyboard Shortcuts & Navigation

| Shortcut / Key | Action |
|---|---|
| `Ctrl + F` | Focus the remote search bar |
| `Down` / `Enter` (in search bar) | Jump focus directly into the remote list |
| `Up` / `Down` (in remote list) | Navigate through remotes and load details instantly |
| `Click` on any remote | Focus remote and select it |

---

## 🛠️ Building Executable (PyInstaller)

To bundle the application into a standalone portable Windows executable:

```bash
# 1. Install PyInstaller
pip install pyinstaller

# 2. Build using the provided spec file
pyinstaller RcloneMountManager.spec
```

The compiled standalone executable will be generated in `dist/RcloneMountManager.exe`.

> **Note on Portability:** `RcloneMountManager.exe` runs portably alongside its local `remotes/`, `cache/`, `logs/`, and `rclone.conf` folders, resolving relative paths safely via the executable directory.

---

## 🧪 Testing

The codebase includes automated unit tests that run headlessly without requiring a display:

```bash
# 1. Syntax check
python -m py_compile RcloneMountManager.py

# 2. Run headless unit tests
python -m unittest -v test_gui.py
```

---

## 📝 Logging & Safety

- **Application Logs (`logs/app.log`)**:
  - Automatically rotated at 2 MB with 6 backups (`backupCount=6`).
  - Encoded in `UTF-8` to prevent encoding errors with special symbols.
- **Path Traversal Safety**:
  - Cache and log cleanup procedures strictly check `path.is_relative_to(BASE_DIR)` to protect against deletion of system files.

---

## 📄 License

This project is provided as-is for personal and commercial use.

## 🙏 Acknowledgments

- [rclone](https://rclone.org/) — The ultimate cloud storage management tool.
- [PySide6 / Qt](https://www.qt.io/) — Modern Python GUI framework.
- [WinFsp](https://winfsp.dev/) — Windows FUSE file system provider.
