#!/usr/bin/env python3
# run: python3 ~/Downloads/QuickClip/quickclip.py
# run: python3 ~/Downloads/quickclip.py
# python %USERPROFILE%\Downloads\quickclip.py
# http://localhost:8080/viewer.html


# QuickClip — Clipboard + Screenshot Monitor
# Monitors clipboard text AND system screenshots, saves both to a live HTML dashboard.
#
# Dependencies:
#   pip3 install pynput pyperclip pillow watchdog --break-system-packages
#
# Screenshot detection strategy (per OS):
#   Windows  — watches %USERPROFILE%\Pictures\Screenshots via watchdog
#   macOS    — watches ~/Desktop (default Cmd+Shift+3/4 target) via watchdog
#   Linux    — watches ~/Pictures and ~/Desktop via watchdog;
#              also polls clipboard for image data (some tools write to clipboard)

import json, os, sys, subprocess, platform, threading, time, hashlib, shutil, base64
from datetime import datetime
from pathlib import Path

# ── Ensure UTF-8 console output (needed for emoji on Windows) ──────────────────
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# ── Project directories ────────────────────────────────────────────────────────
SAVE_DIR        = Path.home() / "QuickClip_Notes"
CLIPS_FILE      = SAVE_DIR / "clips.json"
SHOTS_FILE      = SAVE_DIR / "screenshots.json"   # NEW: screenshot metadata store
SHOTS_DIR       = SAVE_DIR / "screenshots"         # NEW: local copies of screenshots
SAVE_DIR.mkdir(exist_ok=True)
SHOTS_DIR.mkdir(exist_ok=True)

OS = platform.system()   # "Windows" | "Linux" | "Darwin"

# ── Screenshot watch folders (per OS) ─────────────────────────────────────────
# These are the default locations where each OS saves screenshots.
def _screenshot_watch_dirs() -> list[Path]:
    """Return OS-appropriate directories to watch for new screenshot files."""
    home = Path.home()
    if OS == "Windows":
        # Check registry for My Pictures (handles OneDrive and other folder redirections)
        pictures_dir = None
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                val, _ = winreg.QueryValueEx(key, "My Pictures")
                pictures_dir = Path(os.path.expandvars(val))
        except Exception:
            pass

        dirs = []
        if pictures_dir:
            dirs.extend([pictures_dir / "Screenshots", pictures_dir])
        
        # Fallback/alternative standard locations
        dirs.extend([
            home / "Pictures" / "Screenshots", 
            home / "Pictures",
            home / "OneDrive" / "Pictures" / "Screenshots",
            home / "OneDrive" / "Pictures"
        ])
        return dirs
    elif OS == "Darwin":
        # macOS default: Desktop (Cmd+Shift+3/4) and Downloads
        return [home / "Desktop", home / "Downloads"]
    else:  # Linux
        return [home / "Pictures", home / "Desktop", home / "Downloads"]

# Resolve to unique existing directories to watch
SCREENSHOT_WATCH_DIRS = []
for d in _screenshot_watch_dirs():
    if d.exists() and d not in SCREENSHOT_WATCH_DIRS:
        SCREENSHOT_WATCH_DIRS.append(d)

# Image file extensions we consider as screenshots
SCREENSHOT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

# ═══════════════════════════════════════════════════════════════════════════════
#  CLIPBOARD TEXT  (unchanged from original, except minor refactor)
# ═══════════════════════════════════════════════════════════════════════════════

def load_clips() -> list:
    if CLIPS_FILE.exists():
        try:
            return json.loads(CLIPS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_clips(clips: list):
    CLIPS_FILE.write_text(json.dumps(clips, ensure_ascii=False, indent=2), encoding="utf-8")

def add_clip(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    clips = load_clips()
    if clips and clips[0]["text"] == text:
        return False   # exact duplicate at top — skip
    clips.insert(0, {"text": text, "time": datetime.now().strftime("%d %b %Y, %I:%M %p")})
    save_clips(clips[:500])
    return True

def get_clipboard_text() -> str:
    """Read plain-text from the system clipboard, cross-platform."""
    if OS == "Windows":
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except Exception:
            pass

    if OS == "Linux":
        for cmd in (
            ["wl-paste", "-n"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
        ):
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                return res.stdout or ""
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

    # Generic / macOS fallback
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception as e:
        print(f"⚠️ Clipboard read error: {e}")
        if OS == "Linux":
            print("💡 Install xclip or wl-clipboard:")
            print("   Debian/Ubuntu: sudo apt install xclip wl-clipboard")
        return ""

def clipboard_monitor():
    """Background thread: polls clipboard for text every 0.5 s."""
    try:
        last_text = get_clipboard_text()
    except Exception:
        last_text = ""

    while True:
        try:
            time.sleep(0.5)
            current = get_clipboard_text()
            if current and current.strip() and current != last_text:
                last_text = current
                if add_clip(current):
                    generate_viewer()
                    print(f"  ✅ Clipboard: {current[:60].replace(chr(10),' ')}...")
        except Exception:
            pass

def is_code(text: str) -> bool:
    indicators = ["def ", "import ", "class ", "const ", "let ", "function",
                  "<html>", "css", "void ", "#include", "public class", "fn ", "impl "]
    if any(ind in text for ind in indicators):
        return True
    if len(text.splitlines()) > 3 and any(c in text for c in ['{', '}', ';', '=', ':', '(', ')']):
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#  SCREENSHOT STORAGE
# ═══════════════════════════════════════════════════════════════════════════════

def load_shots() -> list:
    """Load screenshot metadata list from JSON."""
    if SHOTS_FILE.exists():
        try:
            return json.loads(SHOTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_shots(shots: list):
    SHOTS_FILE.write_text(json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8")

def _file_hash(path: Path) -> str:
    """Return an MD5 hex digest of a file (for duplicate detection)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def add_screenshot(src_path: Path) -> bool:
    """
    Copy a new screenshot into SHOTS_DIR, record metadata, return True if saved.
    Skips duplicates based on file hash.
    """
    src_path = Path(src_path)
    if not src_path.exists() or src_path.suffix.lower() not in SCREENSHOT_EXTENSIONS:
        return False

    # Wait briefly so the OS finishes writing the file before we read it
    time.sleep(0.4)

    try:
        file_hash = _file_hash(src_path)
    except Exception:
        return False

    shots = load_shots()

    # Duplicate check: same hash already recorded?
    if any(s.get("hash") == file_hash for s in shots):
        return False

    # Copy file to our managed screenshots folder
    timestamp = datetime.now()
    dest_name = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{src_path.name}"
    dest_path = SHOTS_DIR / dest_name
    try:
        shutil.copy2(src_path, dest_path)
    except Exception as e:
        print(f"  ⚠️ Screenshot copy failed: {e}")
        return False

    # Build a small base64 thumbnail (max 300 px wide) for the HTML preview
    thumb_b64 = _make_thumbnail_b64(dest_path)

    shots.insert(0, {
        "filename": dest_name,
        "original": str(src_path),
        "time": timestamp.strftime("%d %b %Y, %I:%M %p"),
        "hash": file_hash,
        "thumb_b64": thumb_b64,   # inline data-URI thumbnail
    })
    save_shots(shots[:200])   # keep at most 200 screenshots
    return True

def _make_thumbnail_b64(img_path: Path, max_width: int = 300) -> str:
    """
    Return a base64 PNG data-URI for a resized thumbnail, or "" on failure.
    Uses Pillow if available, otherwise falls back to raw base64 of the original.
    """
    try:
        from PIL import Image
        with Image.open(img_path) as im:
            # Convert to RGB so we can always save as JPEG (handles RGBA PNGs)
            im = im.convert("RGB")
            ratio = max_width / max(im.width, 1)
            if ratio < 1:
                new_size = (int(im.width * ratio), int(im.height * ratio))
                im = im.resize(new_size, Image.LANCZOS)
            import io
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=75)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        # Pillow not installed — embed the raw file as-is (larger but works)
        try:
            raw = img_path.read_bytes()
            mime = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
            return f"data:{mime};base64," + base64.b64encode(raw).decode()
        except Exception:
            return ""
    except Exception:
        return ""

# ═══════════════════════════════════════════════════════════════════════════════
#  SCREENSHOT MONITORING
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_new_file(path: Path):
    """Called whenever a new file appears in a watched directory."""
    if path.suffix.lower() not in SCREENSHOT_EXTENSIONS:
        return
    # Simple heuristic: file must be < 5 min old to be considered a fresh screenshot
    try:
        age = time.time() - path.stat().st_mtime
        if age > 300:
            return
    except Exception:
        return

    if add_screenshot(path):
        generate_viewer()
        print(f"  📸 Screenshot saved: {path.name}")

def start_screenshot_monitor_watchdog():
    """
    Use the `watchdog` library to efficiently watch filesystem events.
    This avoids polling and keeps CPU usage very low.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class _ScreenshotHandler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    _handle_new_file(Path(event.src_path))

            def on_moved(self, event):
                # Some tools write to a temp file then rename (move) it
                if not event.is_directory:
                    _handle_new_file(Path(event.dest_path))

        observer = Observer()
        for watch_dir in SCREENSHOT_WATCH_DIRS:
            observer.schedule(_ScreenshotHandler(), str(watch_dir), recursive=False)
            print(f"  👁️  Watching: {watch_dir}")

        observer.start()
        return observer   # caller keeps reference so it isn't GC'd

    except ImportError:
        print("  ⚠️ watchdog not installed — falling back to polling screenshot monitor.")
        print("     Install with: pip3 install watchdog --break-system-packages")
        return None

def start_screenshot_monitor_polling():
    """
    Fallback: scan watched directories every 2 s for new image files.
    Slightly higher CPU cost than watchdog but requires no extra library.
    """
    known: set[str] = set()

    # Seed with files already present so we don't re-import old screenshots
    for d in SCREENSHOT_WATCH_DIRS:
        for f in d.iterdir():
            if f.suffix.lower() in SCREENSHOT_EXTENSIONS:
                known.add(str(f))

    def _poll():
        while True:
            time.sleep(2)
            for d in SCREENSHOT_WATCH_DIRS:
                try:
                    for f in d.iterdir():
                        key = str(f)
                        if key not in known and f.suffix.lower() in SCREENSHOT_EXTENSIONS:
                            known.add(key)
                            _handle_new_file(f)
                except Exception:
                    pass

    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    return t

def screenshot_monitor():
    """
    Start screenshot monitoring using watchdog if available, else polling.
    macOS/Linux may also get screenshots via clipboard image polling (Pillow needed).
    """
    observer = start_screenshot_monitor_watchdog()

    # On macOS and Linux, some screenshot tools (e.g. Flameshot, macOS Cmd+Ctrl+Shift+4)
    # put the image directly onto the clipboard without saving a file.
    # We handle that by polling the clipboard for image data.
    if OS in ("Darwin", "Linux"):
        _start_clipboard_image_monitor()

    if observer is None:
        # watchdog unavailable — use polling thread
        start_screenshot_monitor_polling()
    # else watchdog is running in its own thread

def _start_clipboard_image_monitor():
    """
    Poll the clipboard for image data (macOS / Linux).
    If an image is found, save it as a PNG into SHOTS_DIR.
    Requires Pillow (PIL) to grab the image.
    """
    def _poll():
        last_hash = ""
        while True:
            time.sleep(1)
            try:
                from PIL import ImageGrab
                img = ImageGrab.grabclipboard()
                if img is None:
                    continue
                # Convert to bytes to hash
                import io
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                raw = buf.getvalue()
                h = hashlib.md5(raw).hexdigest()
                if h == last_hash:
                    continue
                last_hash = h
                # Save to screenshots dir
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = SHOTS_DIR / f"clipboard_{ts}.png"
                dest.write_bytes(raw)
                if add_screenshot(dest):
                    generate_viewer()
                    print(f"  📸 Clipboard image saved: {dest.name}")
            except ImportError:
                break   # Pillow not installed — silently stop
            except Exception:
                pass

    t = threading.Thread(target=_poll, daemon=True)
    t.start()

# ═══════════════════════════════════════════════════════════════════════════════
#  HTML VIEWER  (two-panel layout: text left, screenshots right)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_viewer():
    """Regenerate the HTML dashboard with current clips and screenshots."""
    clips = load_clips()
    shots = load_shots()

    # ── Text clip cards ────────────────────────────────────────────────────────
    clip_rows = ""
    for c in clips:
        text = c["text"]
        preview = text[:600].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        code_class = " clip-code" if is_code(text) else ""
        escaped = (text.replace("&", "&amp;").replace("<", "&lt;")
                       .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))
        clip_rows += f"""<div class="clip-card" onclick="copyClip(this)" data-text="{escaped}">
          <div class="clip-content{code_class}">{preview}</div>
          <div class="clip-footer">
            <div class="clip-time"><span>🕒</span><span>{c['time']}</span></div>
            <div class="clip-action-hint">Click to Copy ✨</div>
          </div>
        </div>\n"""

    empty_clips = """<div class="empty-state">
      <div class="empty-icon">📭</div>
      <div class="empty-title">Abhi koi clip nahi hai</div>
      <p class="empty-desc">Koi text copy karo ya <strong>Ctrl+Alt+Q</strong> dabao.</p>
    </div>"""

    # ── Screenshot cards ───────────────────────────────────────────────────────
    shot_rows = ""
    for s in shots:
        thumb = s.get("thumb_b64", "")
        fname = s.get("filename", "screenshot")
        # Full image path relative to viewer.html (both in SAVE_DIR)
        full_path = f"screenshots/{fname}"
        img_tag = (f'<img src="{thumb}" class="shot-thumb" alt="{fname}" '
                   f'onclick="openShot(\'{full_path}\')">'
                   if thumb else
                   f'<div class="shot-placeholder">🖼️</div>')
        shot_rows += f"""<div class="shot-card">
          {img_tag}
          <div class="shot-footer">
            <div class="clip-time"><span>📸</span><span>{s['time']}</span></div>
            <div class="shot-name">{fname[:30]}</div>
          </div>
        </div>\n"""

    empty_shots = """<div class="empty-state">
      <div class="empty-icon">🖼️</div>
      <div class="empty-title">Koi screenshot nahi</div>
      <p class="empty-desc">Screenshot lo — ye page pe apne aap aa jayega!</p>
    </div>"""

    # ── Full HTML ──────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>QuickClip Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-gradient: linear-gradient(135deg, #090d16 0%, #111827 100%);
      --panel-bg: rgba(17, 24, 39, 0.75);
      --card-bg: rgba(31, 41, 55, 0.45);
      --card-hover: rgba(55, 65, 81, 0.6);
      --border-color: rgba(255, 255, 255, 0.08);
      --border-hover: rgba(99, 102, 241, 0.45);
      --text-main: #f3f4f6;
      --text-muted: #9ca3af;
      --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
      --accent-color: #6366f1;
      --accent-light: #c084fc;
      --success: #10b981;
      --radius-lg: 16px;
      --radius-md: 12px;
      --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: var(--bg-gradient);
      color: var(--text-main);
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}

    /* ── Header ── */
    header {{
      width: 100%;
      background: rgba(10,15,30,0.85);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border-color);
      position: sticky;
      top: 0;
      z-index: 10;
      padding: 14px 24px;
    }}
    .header-inner {{
      max-width: 1400px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .logo-container {{ display: flex; align-items: center; gap: 10px; }}
    .logo-icon {{ font-size: 26px; filter: drop-shadow(0 2px 8px rgba(99,102,241,.3)); }}
    h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: 22px;
      font-weight: 700;
      background: var(--accent-gradient);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .badges {{ display: flex; gap: 10px; }}
    .badge {{
      background: var(--accent-gradient);
      color: #fff;
      font-size: 12px;
      font-weight: 600;
      padding: 5px 12px;
      border-radius: 20px;
    }}
    .badge.green {{ background: linear-gradient(135deg,#10b981,#059669); }}

    /* ── Two-panel layout ── */
    .panels {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0;
      flex: 1;
      max-width: 1400px;
      width: 100%;
      margin: 0 auto;
      padding: 0;
    }}
    @media (max-width: 900px) {{
      .panels {{ grid-template-columns: 1fr; }}
    }}

    .panel {{
      padding: 20px 20px 60px;
      border-right: 1px solid var(--border-color);
      overflow-y: auto;
      max-height: calc(100vh - 56px);
    }}
    .panel:last-child {{ border-right: none; }}

    .panel-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 16px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    /* ── Search ── */
    .search-wrapper {{
      position: relative;
      margin-bottom: 16px;
    }}
    .search-icon {{
      position: absolute;
      left: 14px;
      top: 50%;
      transform: translateY(-50%);
      font-size: 14px;
      pointer-events: none;
    }}
    .search-input {{
      width: 100%;
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      color: var(--text-main);
      font-family: 'Inter', sans-serif;
      font-size: 14px;
      padding: 10px 14px 10px 38px;
      outline: none;
      transition: var(--transition);
    }}
    .search-input:focus {{
      border-color: var(--accent-color);
      background: rgba(99,102,241,.08);
    }}

    /* ── Clip cards ── */
    .clip-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 14px 16px;
      margin-bottom: 12px;
      cursor: pointer;
      transition: var(--transition);
    }}
    .clip-card:hover {{ background: var(--card-hover); border-color: var(--border-hover); transform: translateY(-1px); }}
    .clip-card.copied {{ border-color: var(--success); background: rgba(16,185,129,.1); }}
    .clip-content {{
      font-size: 13.5px;
      line-height: 1.65;
      color: var(--text-main);
      word-break: break-word;
      white-space: pre-wrap;
      max-height: 160px;
      overflow: hidden;
    }}
    .clip-code {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      background: rgba(0,0,0,.25);
      border-radius: 8px;
      padding: 10px;
    }}
    .clip-footer {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 10px;
    }}
    .clip-time {{
      display: flex;
      align-items: center;
      gap: 5px;
      font-size: 11px;
      color: var(--text-muted);
    }}
    .clip-action-hint {{
      font-size: 11px;
      color: var(--accent-light);
      opacity: 0;
      transform: translateX(6px);
      transition: var(--transition);
    }}
    .clip-card:hover .clip-action-hint {{ opacity: 1; transform: translateX(0); }}

    /* ── Screenshot cards ── */
    .shots-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 12px;
    }}
    .shot-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      overflow: hidden;
      transition: var(--transition);
    }}
    .shot-card:hover {{ border-color: var(--border-hover); transform: translateY(-2px); box-shadow: 0 8px 20px rgba(0,0,0,.3); }}
    .shot-thumb {{
      width: 100%;
      aspect-ratio: 16/9;
      object-fit: cover;
      display: block;
      cursor: zoom-in;
      background: rgba(0,0,0,.3);
    }}
    .shot-placeholder {{
      width: 100%;
      aspect-ratio: 16/9;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 36px;
      background: rgba(0,0,0,.2);
    }}
    .shot-footer {{
      padding: 8px 10px;
    }}
    .shot-name {{
      font-size: 10px;
      color: var(--text-muted);
      margin-top: 3px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    /* ── Lightbox ── */
    #lightbox {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.88);
      z-index: 1000;
      justify-content: center;
      align-items: center;
      cursor: zoom-out;
    }}
    #lightbox.open {{ display: flex; }}
    #lightbox img {{
      max-width: 92vw;
      max-height: 90vh;
      border-radius: 10px;
      box-shadow: 0 24px 60px rgba(0,0,0,.6);
    }}
    #lightbox-close {{
      position: fixed;
      top: 20px;
      right: 28px;
      color: #fff;
      font-size: 30px;
      cursor: pointer;
      z-index: 1001;
      opacity: .7;
      transition: opacity .2s;
    }}
    #lightbox-close:hover {{ opacity: 1; }}

    /* ── Toast ── */
    .toast {{
      position: fixed;
      bottom: 28px;
      left: 50%;
      transform: translateX(-50%) translateY(20px);
      background: var(--accent-gradient);
      color: #fff;
      font-weight: 600;
      font-size: 14px;
      padding: 12px 24px;
      border-radius: 30px;
      box-shadow: 0 10px 25px rgba(99,102,241,.35);
      opacity: 0;
      transition: var(--transition);
      z-index: 100;
      pointer-events: none;
    }}
    .toast.show {{ opacity: 1; transform: translateX(-50%) translateY(0); }}

    /* ── Empty state ── */
    .empty-state {{
      text-align: center;
      padding: 60px 16px;
      color: var(--text-muted);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
    }}
    .empty-icon {{ font-size: 52px; animation: float 3s ease-in-out infinite; }}
    @keyframes float {{ 0%,100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-8px); }} }}
    .empty-title {{ font-family:'Outfit',sans-serif; font-size:18px; color:var(--text-main); font-weight:600; }}
    .empty-desc {{ font-size:13px; max-width:280px; line-height:1.6; }}
  </style>
</head>
<body>

<header>
  <div class="header-inner">
    <div class="logo-container">
      <span class="logo-icon">📋</span>
      <h1>QuickClip</h1>
    </div>
    <div class="badges">
      <span class="badge" id="clip-count">{len(clips)} clips</span>
      <span class="badge green" id="shot-count">{len(shots)} screenshots</span>
    </div>
  </div>
</header>

<div class="panels">

  <!-- LEFT PANEL: Text clips -->
  <div class="panel" id="clips-panel">
    <div class="panel-title">📝 Copied Text</div>
    <div class="search-wrapper">
      <span class="search-icon">🔍</span>
      <input type="text" id="search" class="search-input"
             placeholder="Search clips..." oninput="filterClips()">
    </div>
    <div id="clips-list">
      {clip_rows if clips else empty_clips}
    </div>
  </div>

  <!-- RIGHT PANEL: Screenshots -->
  <div class="panel" id="shots-panel">
    <div class="panel-title">📸 Screenshots</div>
    <div class="shots-grid" id="shots-grid">
      {shot_rows if shots else empty_shots}
    </div>
  </div>

</div>

<!-- Lightbox for full-size screenshot -->
<div id="lightbox" onclick="closeLightbox()">
  <span id="lightbox-close" onclick="closeLightbox()">✕</span>
  <img id="lightbox-img" src="" alt="Screenshot">
</div>

<div class="toast" id="toast">✅ Copied to Clipboard!</div>

<script>
  // ── Copy clip to clipboard ─────────────────────────────────────────────────
  function copyClip(el) {{
    const text = el.getAttribute('data-text')
      .replace(/&quot;/g,'"').replace(/&#39;/g,"'")
      .replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
    navigator.clipboard.writeText(text).then(() => {{
      el.classList.add('copied');
      showToast('✅ Copied!');
      setTimeout(() => el.classList.remove('copied'), 1600);
    }}).catch(console.error);
  }}

  function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 1800);
  }}

  // ── Search / filter text clips ─────────────────────────────────────────────
  function filterClips() {{
    const q = document.getElementById('search').value.toLowerCase();
    document.querySelectorAll('.clip-card').forEach(c => {{
      c.style.display = c.getAttribute('data-text').toLowerCase().includes(q) ? '' : 'none';
    }});
  }}

  // ── Lightbox for screenshots ───────────────────────────────────────────────
  function openShot(src) {{
    document.getElementById('lightbox-img').src = src;
    document.getElementById('lightbox').classList.add('open');
  }}
  function closeLightbox() {{
    document.getElementById('lightbox').classList.remove('open');
    document.getElementById('lightbox-img').src = '';
  }}
  document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeLightbox(); }});

  // ── Persist scroll & search across reloads ─────────────────────────────────
  window.addEventListener('beforeunload', () => {{
    localStorage.setItem('clipScroll', document.getElementById('clips-panel').scrollTop);
    localStorage.setItem('shotScroll', document.getElementById('shots-panel').scrollTop);
    localStorage.setItem('searchQ', document.getElementById('search').value);
  }});
  window.addEventListener('DOMContentLoaded', () => {{
    const q = localStorage.getItem('searchQ');
    if (q) {{ document.getElementById('search').value = q; filterClips(); }}
    const cs = localStorage.getItem('clipScroll');
    const ss = localStorage.getItem('shotScroll');
    if (cs) document.getElementById('clips-panel').scrollTop = parseInt(cs);
    if (ss) document.getElementById('shots-panel').scrollTop = parseInt(ss);
  }});

  // ── Auto-reload when not focused or on a second monitor ───────────────────
  window.addEventListener('focus', () => location.reload());
  setInterval(() => {{
    if (!document.hasFocus() && document.visibilityState === 'visible')
      location.reload();
  }}, 5000);
</script>
</body>
</html>"""

    p = SAVE_DIR / "viewer.html"
    p.write_text(html, encoding="utf-8")
    return str(p)

# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def start_listener():
    """Start all background monitors and the optional keyboard shortcut listener."""

    # 1. Clipboard text monitor
    threading.Thread(target=clipboard_monitor, daemon=True).start()

    # 2. Screenshot monitor (watchdog or polling + optional clipboard-image poll)
    screenshot_monitor()

    # 3. Keyboard shortcut listener (Ctrl+Alt+Q)
    try:
        from pynput import keyboard
        pressed = set()
        kb = keyboard.Controller()

        def trigger_copy():
            try:
                kb.press(keyboard.Key.ctrl)
                kb.press('c')
                kb.release('c')
                kb.release(keyboard.Key.ctrl)
            except Exception:
                pass

        def on_press(key):
            pressed.add(key)
            ctrl = keyboard.Key.ctrl_l in pressed or keyboard.Key.ctrl_r in pressed
            alt  = keyboard.Key.alt_l  in pressed or keyboard.Key.alt_r  in pressed or keyboard.Key.alt in pressed
            try:
                q_key = key.char in ('q', 'Q')
            except AttributeError:
                q_key = False
            if ctrl and alt and q_key:
                trigger_copy()
                time.sleep(0.2)
                text = get_clipboard_text()
                if text.strip():
                    if add_clip(text):
                        generate_viewer()
                        print(f"  ✅ Saved (hotkey): {text[:60].replace(chr(10),' ')}...")
                    else:
                        print("  ⚠️ Duplicate — skip kiya.")
                else:
                    print("  ⚠️ Clipboard empty! Pehle text select karo.")

        def on_release(key):
            pressed.discard(key)

        _print_banner()
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()

    except Exception:
        _print_banner(no_hotkey=True)
        while True:
            time.sleep(1)

def _print_banner(no_hotkey: bool = False):
    print("=" * 56)
    print("   📋 QuickClip chal raha hai!")
    print("   ✅ Clipboard text: auto-monitor active")
    if SCREENSHOT_WATCH_DIRS:
        print(f"   📸 Screenshots: watching {len(SCREENSHOT_WATCH_DIRS)} folder(s)")
    else:
        print("   ⚠️  No screenshot watch folders found")
    if no_hotkey:
        print("   ⚠️  Keyboard shortcut disabled (pynput not available)")
    else:
        print("   ⌨️  Shortcut: Ctrl + Alt + Q")
    print(f"   📁 Save dir : {SAVE_DIR}")
    print(f"   🌐 Viewer  : {SAVE_DIR}/viewer.html")
    print("   Rokne ke liye: Ctrl+C")
    print("=" * 56)

if __name__ == "__main__":
    generate_viewer()
    try:
        start_listener()
    except KeyboardInterrupt:
        print("\nBand ho gaya. Alvida! 👋")
    except ImportError:
        print("ERROR: pip3 install pynput pyperclip pillow watchdog --break-system-packages")
