# EzvizFloatCam

> A lightweight Windows app that shows your Ezviz camera (via RTSP) in a floating, always-on-top, rounded glass-style window.

<p align="center">
<img src="assets/demo.gif">
</p>

<p align="center">
<img src="https://img.shields.io/github/v/release/tuananh511/ezviz-float-cam" alt="Release">
<img src="https://img.shields.io/github/license/tuananh511/ezviz-float-cam" alt="License">
<img src="https://img.shields.io/github/actions/workflow/status/tuananh511/ezviz-float-cam/build.yml" alt="Build">
</p>

> ✅ **Current status: Feature-complete (v0.7.0)** — a ready-to-run Windows `.exe` installer is available on the [Releases](../../releases) page.

---

## Overview

EzvizFloatCam connects to an Ezviz camera's RTSP stream and displays it in a small, frameless, rounded floating window that stays on top of other windows — similar to a picture-in-picture overlay. It lives in the system tray, reconnects automatically if the signal drops, and can be configured entirely through its settings UI, with no manual file editing required.

## Features

- Connects to and displays an Ezviz camera's RTSP stream
- Rounded, frosted-glass (blur) window; always-on-top; drag to move, drag the corner to resize
- System tray icon — toggle the stream, show/hide the window, quit
- Connection settings (IP/user/password) configurable from the UI, no file editing needed
- Optional launch on Windows startup (toggle in Settings or during install)
- Mute and emergency-recording icons on the floating window
- Automatic reconnect on signal loss — shows a "NO SIGNAL" static screen instead of a black screen, and recovers automatically once the connection returns
- "About" dialog (bottom-left icon on the window)
- Standalone `.exe` installer — no Python required
- Standard Windows installer/uninstaller (Inno Setup) — compatible with Control Panel / Revo Uninstaller
- Official GitHub Release with installer attached

## Installation

### For most users (recommended)

Go to the [Releases](../../releases/tag/v0.7.0) page, download `EzvizFloatCam-Setup-0.7.0.exe`, run it, and follow the install prompts. No Python required.

**Only requirement:** [VLC media player](https://www.videolan.org/vlc/) (desktop edition) must already be installed, since the app relies on VLC's `libvlc.dll` for video decoding — it is not bundled with the installer.

To uninstall, use **Control Panel → Apps & Features** or Revo Uninstaller, just like any other Windows application.

### For running/building from source

**Requirements:**
- Windows 10/11
- [Python 3.10+](https://www.python.org/downloads/)
- [VLC media player](https://www.videolan.org/vlc/) (desktop edition, needed for `libvlc.dll`)
- An Ezviz camera with RTSP enabled (in the Ezviz app: **Device Settings → Advanced Features → Platform/RTSP Address**, enable RTSP and set a dedicated RTSP password)

**Setup:**

```
git clone https://github.com/tuananh511/ezviz-float-cam.git
cd ezviz-float-cam
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**Building the `.exe`:**

```
build_exe.bat
```
(or `pyinstaller ezvizfloatcam.spec --noconfirm` if PyInstaller is already installed). The output binary is at `dist\EzvizFloatCam.exe` — it runs standalone without Python, but VLC must still be installed.

**Building the installer (Inno Setup):**

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php). Once `dist\EzvizFloatCam.exe` exists:

```
ISCC.exe installer\setup.iss
```

The installer is generated at `dist_installer\EzvizFloatCam-Setup-x.x.x.exe`. It registers the app in Apps & Features, optionally creates a desktop icon/startup entry during install, and can be uninstalled via Control Panel or Revo Uninstaller.

## Usage

### Camera configuration

**Recommended — via the UI:** run the app once (see below), right-click the tray icon → **Settings...** → enter the camera's RTSP IP/port/username/password → click **Test Connection** to verify before saving → click **Save**. The app reconnects immediately with the new settings, no restart needed.

**Manual (fallback):** run the app once to let it create a config file at `%APPDATA%\EzvizFloatCam\config.json`, then edit it directly:

```json
{
  "rtsp": {
    "ip": "192.168.1.100",
    "port": 554,
    "username": "admin",
    "password": "your-rtsp-password",
    "stream_type": "sub",
    "channel": "ch1"
  }
}
```
> `stream_type`: use `"sub"` for the lightweight stream (recommended for a small window), `"main"` for the higher-quality/heavier stream.
> ⚠️ The RTSP password is currently stored in plaintext (unencrypted) in `config.json` on your machine. This file is not committed to GitHub and is only readable by your own Windows user account (`%APPDATA%` is per-user), but this is not real encryption. For stronger security, consider setting a dedicated RTSP password on the camera (different from the main account password) via the Ezviz app.

### Running from source

```
cd src
python main.py
```

The window opens as a floating, frameless, rounded, always-on-top overlay — drag anywhere on the window (including over the video) to move it, drag the bottom-right corner to resize. Position and size are remembered for next time.

> The frosted-glass blur effect only works on Windows 10/11. On other operating systems the app falls back to a plain semi-transparent background without blur.

### System tray icon

The app runs in the background via a system tray icon (bottom-right of the screen, next to the clock):

- **Left-click / double-click the icon**: show/hide the camera window.
- **Right-click the icon** to open the menu:
  * **Show/Hide window**
  * **Start/Stop stream** — stop the stream to save CPU/bandwidth without closing the app.
  * **Settings...** — opens the dialog to enter RTSP IP/port/user/password, toggle launch on Windows startup, and test the connection before saving.
  * **Quit** — closes the app entirely (this is the only way to fully exit).

> Note: the camera window has no close button/titlebar (frameless). Pressing Alt+F4 or otherwise closing the window only **hides** it (the tray icon remains) — it does not quit the app. Click the tray icon again or choose "Show window" to bring it back.

### Icons on the floating window

- **Top-left:** connection status dot — green (streaming), amber (reconnecting), red (no signal/stopped).
- **Top-right:** mute / emergency-recording icon.
- **Bottom-left:** "i" icon — opens the About dialog (version, GitHub link, MIT license).
- **Bottom-right:** resize handle.

When the camera connection is lost, the window switches to a static-noise display with "RECONNECTING" / "NO SIGNAL" text instead of a black screen, and recovers automatically once the signal returns — no need to restart the app.

## Roadmap

- [ ] Contributions and bug reports welcome — this is an ongoing personal project. Please open an [Issue](../../issues) with a description and console log if you run into problems.

## License

MIT
