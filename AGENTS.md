# AGENTS.md — Rclone Mount Manager

> Everything an AI agent needs to work effectively on this project.

---

## Language

All code, comments, docstrings, log messages, UI strings, and commit messages **must be in English**. Convert any legacy non-English text when editing nearby code.

---

## Codebase at a Glance

```
RcloneMountManager/
├── RcloneMountManager.py   # Single-file app: all GUI + controller logic
├── test_gui.py             # Headless unit tests (PySide6 offscreen)
├── requirements.txt        # PySide6>=6.5.0
├── RcloneMountManager.spec # PyInstaller build spec
├── icon.ico
├── remotes/
│   ├── _sample.properties  # Ignored by loader (leading underscore)
│   ├── <id>.properties     # Per-remote config (configparser format)
│   └── <id>.override.json  # Runtime UI overrides saved on mount
├── cache/<id>/             # VFS cache per remote
└── logs/
    ├── app.log             # Rotating, UTF-8, 2 MB × 6
    └── <id>/rclone.log
```

**One file.** All changes go in `RcloneMountManager.py`. The test file is `test_gui.py`.

---

## Key Classes

| Class | Purpose |
|---|---|
| `RemoteController` | Owns a `QProcess` running `rclone mount`, handles start/stop/cleanup |
| `MainWindow` | Top-level window; builds sidebar + right panel |
| `RemoteWidget` | Right-hand details panel: status, buttons, collapsible settings, live log |
| `RemoteListItem` | Custom sidebar row widget (compact, 32 px tall) |
| `StatusIndicator` | Coloured dot label; `size=` param, default 10 px |
| `ModernButton` | Gradient `QPushButton`; `min_height=` param, default 36 px |
| `ModernCard` | Dark `QFrame` used as a section container |

---

## Layout Rules (do not break these)

- **Right panel** (`RemoteWidget`) must stay inside `self.details_scroll` (`QScrollArea`, `widgetResizable=True`, no horizontal scrollbar). Removing it forces a minimum window height that breaks small screens.
- **Sidebar stretch**: `sidebar_layout` must use stretch `0 / 1 / 0` for header / `list_widget` / footer so the list fills available space and scrolls when there are many remotes.
- **Sidebar items**: `QListWidgetItem.setSizeHint(QSize(250, 32))`, inner margins `(8, 4, 8, 4)`, spacing `8`, `Qt.AlignVCenter`.
- **Selection sync**: `on_remote_clicked` must call `list_widget.setCurrentItem(item)` after loading the remote in the details panel.
- **Mount Settings** section (`settings_card`) is collapsible; default state is collapsed (`group_settings.isHidden() == True`). Toggle via `toggle_settings()`.
- **Scrollbar stylesheet**: always declare `QScrollBar::add-page` and `QScrollBar::sub-page` with `background: none` to prevent rendering artifacts.

---

## RemoteController Behaviour

```
start_mount()  →  builds rclone command, starts QProcess, sets is_running = True
stop_mount()   →  Windows: terminate() + taskkill fallback after 3 s
                  Linux:   fusermount -u <mountpoint>, then terminate()
_cleanup()     →  deletes cache/logs only if path.is_relative_to(BASE_DIR)  ← safety check, never remove
```

Config resolution order for `--config`: `config_path` in `.properties` → `BASE_DIR/rclone.conf` → rclone default.

Mountpoint `auto` on Windows → passes `*` as the mountpoint argument (auto-assign drive letter).

---

## Logging

```python
RotatingFileHandler(APP_LOG, maxBytes=2*1024*1024, backupCount=6, encoding='utf-8')
```

`encoding='utf-8'` is mandatory on Windows to avoid `UnicodeEncodeError` with emoji characters in log strings.

---

## Portable Path Resolution

```python
get_base_dir()   # dev → Path(__file__).parent  |  exe → Path(sys.executable).parent
get_icon_path()  # checks sys._MEIPASS first (PyInstaller), then BASE_DIR
```

Always use `BASE_DIR` for relative path resolution, never `os.getcwd()`.

---

## Verification (run after every change)

```bash
# 1. Syntax
python -m py_compile RcloneMountManager.py

# 2. Tests (headless, no display required)
python -m unittest -v test_gui.py
```

Tests use `QApplication(["-platform", "offscreen"])`. Never depend on an active display. All tests live in a single `TestRcloneMountManager(unittest.TestCase)` class.

When adding a new test:
- Import only what you need inside the test method to keep setup fast.
- Prefer asserting structural properties (widget hierarchy, margins, flags) over pixel-level layout.
- Clean up any temp files in `tearDown` or `finally` blocks.

---

## Building

```bash
# PyInstaller (preferred, uses existing spec)
pyinstaller RcloneMountManager.spec

# Nuitka
python -m nuitka --standalone --onefile --windows-disable-console \
    --windows-icon-from-ico=icon.ico \
    --output-dir=build --output-filename=RcloneMountManager.exe \
    RcloneMountManager.py
```

The `.spec` file already bundles `icon.ico` via `datas=[('icon.ico', '.')]`.

---

## Coding Conventions

- PEP 8. No type-ignore hacks without a comment explaining why.
- Docstrings on every class and non-trivial method.
- Use `logger.info/warning/error` — never bare `print()` in production code paths.
- Keep all Qt stylesheet strings as raw inline strings inside the relevant `__init__`. Do not move them to a separate theme file unless the user requests it.
- Do not introduce new dependencies without updating `requirements.txt`.
