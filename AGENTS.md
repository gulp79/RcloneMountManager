# AI Agents Development & Maintenance Guide

This document defines guidelines, architectural patterns, coding standards, and operational workflows for AI agents working on, maintaining, and updating the **Rclone Mount Manager** application.

---

## 🌐 Language Requirement (Strict Rule)

> [!IMPORTANT]
> **ALL code comments, docstrings, variable/function names, UI strings, log messages, commit messages, and documentation updates MUST BE IN ENGLISH.**
> Existing legacy comments or docstrings in other languages should be converted to English when touching the relevant code sections.

---

## 🤖 AI Development Team Roles

### 1. Manager (Architect & PM)
- **Role**: Requirements analysis, task breakdown, and technical planning.
- **Workflow**:
  - Review user requirements and inspect the codebase.
  - Break tasks down into clear, atomic milestones.
  - Define architectural decisions, UI layout changes, and technical risks.
  - Ensure compatibility with both Windows and Linux, as well as PyInstaller / Nuitka packaging.
  - Validate the Tester's results before marking a milestone complete.

### 2. Developer (Python Engineer)
- **Role**: Code implementation, refactoring, and bug fixes.
- **Workflow**:
  - Implement changes adhering strictly to the plan formulated by the Manager.
  - Keep code modular, clean, and adhering to PEP 8 standards.
  - Maintain docstrings and inline comments in **English**.
  - Respect existing architectural abstractions (`RemoteController`, `MainWindow`, `RemoteWidget`, etc.).

### 3. Tester (QA Engineer)
- **Role**: Code quality assurance, static verification, and automated testing.
- **Workflow**:
  - Review modified code for syntax errors, regressions, and layout stability.
  - Run static syntax verification (`python -m py_compile RcloneMountManager.py`).
  - Maintain and execute the unit test suite (`python -m unittest -v test_gui.py`).
  - Always run GUI tests using Qt offscreen mode (`QApplication(["-platform", "offscreen"])`) so tests can run in headless CI/CD and sandbox environments.

---

## 📁 Project Architecture & File Structure

```text
RcloneMountManager/
├── RcloneMountManager.py     # Main application file (GUI, controllers, process lifecycle)
├── test_gui.py               # Automated unit test suite (headless offscreen tests)
├── requirements.txt          # Python runtime dependencies (PySide6>=6.5.0)
├── RcloneMountManager.spec   # PyInstaller build specification
├── icon.ico                  # Application icon (Windows ICO format)
├── remotes/                  # Remote configuration storage
│   ├── _sample.properties    # Sample configuration template
│   ├── <name>.properties     # Individual remote settings
│   └── <name>.override.json  # Runtime UI parameter overrides
├── cache/                    # Local VFS cache per remote (<remote_id>/)
└── logs/                     # Log files
    ├── app.log               # Main application log (UTF-8, rotated 2MB x 6 backups)
    └── <remote_id>/          # Per-remote rclone logs
        └── rclone.log
```

---

## 🧩 Core Architectural Components

### 1. Process & Controller Logic (`RemoteController`)
- **Process Management**:
  - Uses `QProcess` to run `rclone mount`.
  - Termination sequence:
    - **Windows**: Calls `self.process.terminate()`. If not finished within 3000 ms, falls back to `taskkill /F /T /PID <pid>`.
    - **Linux**: Calls `fusermount -u <mountpoint>` first, followed by `self.process.terminate()`.
- **Safety Checks**:
  - Directory cleanup (`_cleanup`) MUST ALWAYS verify path containment using `is_relative_to(BASE_DIR)` to prevent deleting arbitrary system files.
- **Configuration & Overrides**:
  - Remote properties are stored in `.properties` files (`configparser`).
  - Dynamic UI adjustments (cache mode, cache age, dir cache time) are persisted in `<remote_id>.override.json`.

### 2. User Interface (`MainWindow`, `RemoteListItem`, `RemoteWidget`)
- **Split Layout (`MainWindow`)**:
  - **Left Sidebar** (`QFrame`, fixed width 280px):
    - `header`: Title & subtitle (compact padding: `16px 12px 16px 10px`). Layout stretch factor `0`.
    - `list_widget` (`QListWidget`): Shows all remotes. Layout stretch factor `1`.
    - `footer`: Contains the "Refresh" button. Layout stretch factor `0`.
  - **Right Details Panel (`details_scroll`)**:
    - **Crucial Layout Rule**: The right panel (`RemoteWidget`) MUST remain enclosed inside `self.details_scroll = QScrollArea()`. This prevents the details panel from enforcing a large minimum window height that would break non-maximized windows or small screens.
- **Compact Sidebar Item Density (`RemoteListItem`)**:
  - Item height is set via `QListWidgetItem.setSizeHint(QSize(250, 28))`.
  - Layout margins: `contentsMargins(8, 2, 8, 2)` (minimal 2px vertical padding).
  - Internal spacing: `setSpacing(8)`.
  - Explicit vertical centering: `layout.setAlignment(Qt.AlignVCenter)`.
  - Status indicator: `StatusIndicator(size=10)` (10x10 px).
  - Emoji icon: 10pt font.
  - Name label: 9pt font, Medium weight.
  - Border radius for hover and selection: 4px.
  - **Selection Synchronization**: When a `RemoteListItem` is clicked, `on_remote_clicked` must update `list_widget.setCurrentItem(item)` to keep visual selection synchronized.

### 3. Styling & Theming (`apply_modern_dark_theme`)
- Qt `Fusion` style with dark palette.
- **Scrollbar Styling**:
  - Custom scrollbars defined in `app.setStyleSheet`.
  - Always keep `QScrollBar::add-page` and `QScrollBar::sub-page` set to `background: none;` to avoid rendering artifacts or invisible scrollbars across different platforms.

### 4. Portable Path Resolution & Bundling
- `get_base_dir()` automatically handles:
  - Development mode (`Path(__file__).resolve().parent`).
  - PyInstaller / Nuitka compiled mode (`sys.executable` parent or `_MEIPASS`).
- `get_icon_path()` checks both `sys._MEIPASS` and `BASE_DIR`.
- All file logging (`RotatingFileHandler`) must explicitly use `encoding='utf-8'` to prevent `UnicodeEncodeError` with emojis on Windows.

---

## 🛠️ Testing & Verification Guidelines

When making any changes to the codebase, follow these verification steps:

1. **Syntax Check**:
   ```bash
   python -m py_compile RcloneMountManager.py
   ```

2. **Automated Unit Tests**:
   ```bash
   python -m unittest -v test_gui.py
   ```
   - When writing new tests, keep them self-contained using Python's standard library `unittest` and `PySide6`.
   - Never rely on an active desktop display in tests; always pass `["-platform", "offscreen"]` to `QApplication`.

3. **Responsive GUI Verification**:
   - Verify the window resizes cleanly below 600px height without clipping controls.
   - Verify sidebar scrolling remains smooth when 20+ remotes are configured.
   - Ensure the selection highlight follows the clicked remote item.

---

## 📦 Building Executables

### PyInstaller
```bash
pyinstaller RcloneMountManager.spec
```
Or with CLI flags:
```bash
pyinstaller --onefile --windowed --name "RcloneMountManager" --icon=icon.ico RcloneMountManager.py
```

### Nuitka
```bash
python -m nuitka --standalone --onefile --windows-disable-console --windows-icon-from-ico=icon.ico --output-dir=build --output-filename=RcloneMountManager.exe RcloneMountManager.py
```
