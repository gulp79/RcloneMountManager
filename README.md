# 💾 Rclone Mount Manager

A modern, dark-themed desktop application for managing rclone mounts with an intuitive GUI.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.12+-green)
![Qt](https://img.shields.io/badge/Qt-PySide6-brightgreen)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)
[![GitHub release](https://img.shields.io/github/v/release/gulp79/RcloneMountManager?include_prereleases)](https://github.com/gulp79/RcloneMountManager/releases/latest)
![Total Downloads](https://img.shields.io/github/downloads/gulp79/RcloneMountManager/total)
![Latest Downloads](https://img.shields.io/github/downloads/gulp79/RcloneMountManager/latest/total)

<img width="1186" height="1025" alt="image" src="https://github.com/user-attachments/assets/d6938e9d-d5ee-4567-bdf2-0b64a6951617" />

## ✨ Features

### Core Functionality
- 📂 **Multiple Remote Management**: Handle multiple cloud storage mounts simultaneously
- 🚀 **One-Click Mount/Unmount**: Simple interface for mounting and unmounting
- ⚙️ **Configurable Parameters**: Edit VFS cache settings on-the-fly without modifying config files
- 📋 **Live Log Viewer**: Real-time monitoring of rclone operations
- 🧹 **Automatic Cleanup**: Clean cache and logs after unmount
- 💾 **Persistent Settings**: Save custom parameters per remote

### Modern UI
- 🎨 **Dark Theme**: Eye-friendly dark interface with modern design
- 🎯 **Status Indicators**: Visual feedback for running/stopped/error states
- 📊 **Organized Layout**: Clean sidebar with expandable details panel
- 🔄 **Real-time Updates**: Live process monitoring and log updates
- 🖱️ **Intuitive Controls**: Emoji icons and clear labels for all actions

### Utility Functions
- 📂 **Quick Access**: Open mount location, logs, and cache folders directly
- ⌨️ **Command Preview**: View the exact rclone command before execution
- 🕐 **Mount Timestamps**: Track when each mount was started
- 🔒 **Safe Unmount**: Graceful unmount with cleanup
- 📝 **Detailed Logging**: Application logs with automatic rotation (2MB max, keep 6 files)

## 📋 Requirements

### System Requirements
- **Python**: 3.12 or higher
- **rclone**: Must be installed and configured
- **Windows**: WinFsp driver (for mounting)
- **Linux**: FUSE support (usually pre-installed)

### Python Dependencies
```
PySide6>=6.5.0
```

## 🚀 Installation

### 1. Install rclone

I use rclone-extra https://github.com/gulp79/rclone-extra to have teldrive and terabox support, or use the official release.

### 2. Configure rclone
```bash
rclone config
```
Follow the interactive setup to add your cloud storage providers.

### 3. Download release exe and launch it 

### 4. Or install Python dependencies
```bash
pip install -r requirements.txt
```

### 5. Set up the application

```bash
# Clone or download the application
cd rclone-mount-manager

# Create required directories (done automatically on first run)
mkdir -p remotes cache logs

# Place your rclone.conf in the application folder
cp ~/.config/rclone/rclone.conf .
```

## 📁 Project Structure

```
rclone-mount-manager/
├── RcloneMountManager.py          # Main application (improved version)
├── main.py                   # Original application
├── requirements.txt          # Python dependencies
├── rclone.conf              # rclone configuration (not included)
├── remotes/                 # Remote configurations
│   ├── _sample.properties   # Example configuration (auto-created)
│   ├── pcloud.properties    # Your remote configs
│   └── gdrive.properties
├── cache/                   # VFS cache directories (per remote)
│   ├── pcloud/
│   └── gdrive/
└── logs/                    # Log files (per remote + app logs)
    ├── app.log              # Application log with rotation
    ├── pcloud/
    │   └── rclone.log
    └── gdrive/
        └── rclone.log
```

## 🔧 Configuration

### Creating a Remote Configuration

1. **Copy the sample file**:
```bash
cp remotes/_sample.properties remotes/myremote.properties
```

2. **Edit the configuration**:
```ini
[General]
# Display name in the UI
name = My Cloud Storage

# Remote name from rclone.conf (must end with :)
remote_name = myremote:

# Mount point
# Windows: "auto" for automatic letter, or "X:", "Y:", etc.
# Linux: absolute path like /mnt/myremote
mountpoint = auto

# Volume name (optional, recommended for Windows)
volname = MyCloudDrive

[Rclone]
# Path to rclone.conf (relative or absolute)
# If not specified, uses rclone.conf in app folder
config_path = rclone.conf

# Extra flags for rclone mount (optional)
# Example: --links --network-mode --poll-interval=10s
extra_flags = --links

[Defaults]
# VFS cache mode: off, minimal, writes, full
vfs_cache_mode = full

# Maximum age of cached data
vfs_cache_max_age = 30m

# Directory cache time
dir_cache_time = 1m
```

3. **Refresh the application** to see the new remote

### Runtime Parameter Overrides

When you modify parameters in the UI (VFS cache mode, cache age, directory cache time), they are saved to:
```
remotes/myremote.override.json
```

This allows you to change settings without editing the `.properties` file.

## 🎮 Usage

### Starting the Application

```bash
python RcloneMountManager.py
```

### Basic Workflow

1. **Select a Remote**: Click on a remote in the left sidebar
2. **Configure Settings**: Adjust VFS cache parameters if needed
3. **Mount**: Click the "🚀 MOUNT" button
4. **Monitor**: Watch the live log for mount status
5. **Access Files**: Click "📂 Open Mount" to browse files
6. **Unmount**: Click "⏹️ UNMOUNT" when done

### Quick Actions

- **🔄 Refresh**: Reload the remote list
- **📄 Open Logs**: View detailed rclone logs
- **💾 Open Cache**: Check VFS cache contents
- **⌨️ Show Command**: See the exact rclone command

### System Tray (Future)

Minimize to system tray for background operation (requires icon setup).

## 🛠️ Building Executables

### Using PyInstaller

```bash
# Install PyInstaller
pip install pyinstaller

# Create executable
pyinstaller --onefile --windowed \
    --name "RcloneMountManager" \
    --icon=icon.ico \
    RcloneMountManager.py

# Executable will be in dist/
```

### Using Nuitka

```bash
# Install Nuitka
pip install nuitka

# Create executable (optimized)
python -m nuitka \
    --standalone \
    --onefile \
    --windows-disable-console \
    --windows-icon-from-ico=icon.ico \
    --output-dir=build \
    --output-filename=RcloneMountManager.exe \
    RcloneMountManager.py
```

## 🔍 Troubleshooting

### Mount Fails on Windows
- **Issue**: "Mount failed" error
- **Solution**: Install WinFsp from https://winfsp.dev/rel/

### Mount Fails on Linux
- **Issue**: "fusermount: command not found"
- **Solution**: `sudo apt install fuse`

### Remote Not Found
- **Issue**: "Remote not found in rclone.conf"
- **Solution**: Run `rclone config` and verify the remote name

### Permission Denied
- **Issue**: Cannot access mounted drive
- **Solution**: Check rclone configuration and credentials

### Log Rotation Issues
- **Issue**: Logs growing too large
- **Solution**: Logs automatically rotate at 2MB (keeps 6 backups)

## 📝 Logging

### Application Logs
Location: `logs/app.log`
- Automatic rotation at 2MB
- Keeps 6 backup files
- Format: `YYYY-MM-DD HH:MM:SS - LEVEL - Message`

### Remote Logs
Location: `logs/<remote_name>/rclone.log`
- Per-remote logging
- Shows all rclone operations
- Can be cleared with "Clean logs after unmount" option

## 🔐 Security Notes

### Path Safety
- All file operations validate paths are within application directory
- No path traversal vulnerabilities
- Cleanup operations use `is_relative_to()` checks

### Config Files
- rclone.conf should be kept secure (contains credentials)
- Consider encrypting config with rclone's built-in encryption
- Never commit rclone.conf to version control

### Process Management
- Graceful shutdown attempts before force kill
- PID tracking for safe termination
- No orphaned processes

## 🤝 Contributing

Contributions are welcome! Areas for improvement:
- [ ] Custom application icon
- [ ] Animated transitions
- [ ] Multi-language support
- [ ] Import/Export configurations
- [ ] Advanced settings editor
- [ ] Search/filter remotes
- [ ] Template wizard for new remotes

## 📄 License

This project is provided as-is for personal and commercial use.

## 🙏 Acknowledgments

- **rclone**: The amazing cloud storage sync tool
- **Qt/PySide6**: Cross-platform GUI framework
- **WinFsp**: Windows FUSE implementation

## 📞 Support

For issues related to:
- **rclone**: See https://rclone.org/
- **WinFsp**: See https://winfsp.dev/
- **This application**: Open an issue on GitHub

## 🗺️ Roadmap

### v1.1 (Planned)
- [ ] System tray integration with quick actions
- [ ] Dark/Light theme toggle
- [ ] Custom application icon
- [ ] Notification system

### v1.2 (Planned)
- [ ] Remote template wizard
- [ ] Batch mount/unmount
- [ ] Configuration import/export
- [ ] Search and filters

### v2.0 (Future)
- [ ] Multi-language support
- [ ] Auto-update functionality
- [ ] Cloud sync for configs
- [ ] Advanced scheduling

---

**Made with ❤️ for the rclone community**
