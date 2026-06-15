#!/usr/bin/env python3
# run: python3 ~/Downloads/QuickClip/quickclip.py

import json, os, sys, subprocess, platform, threading, time
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 encoding for console output to support emojis on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

SAVE_DIR   = Path.home() / "QuickClip_Notes" #we want a dir that can be sync eith c;loud ios cloud ya phir ms360 ]
CLIPS_FILE = SAVE_DIR / "clips.json"
SAVE_DIR.mkdir(exist_ok=True)
OS = platform.system()

def load_clips():
    if CLIPS_FILE.exists():
        try: return json.loads(CLIPS_FILE.read_text(encoding="utf-8"))
        except: return []
    return []

def save_clips(clips):
    CLIPS_FILE.write_text(json.dumps(clips, ensure_ascii=False, indent=2), encoding="utf-8")

def add_clip(text: str):
    text = text.strip()
    if not text: return False
    clips = load_clips()
    if clips and clips[0]["text"] == text: return False
    clips.insert(0, {"text": text, "time": datetime.now().strftime("%d %b %Y, %I:%M %p")})
    save_clips(clips[:500])
    return True

def get_clipboard():
    # Windows native or fallback using pyperclip
    if OS == "Windows":
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except:
            pass

    # Linux (handling Wayland and X11 natively before falling back)
    if OS == "Linux":
        # 1. Try Wayland (wl-paste)
        try:
            res = subprocess.run(["wl-paste", "-n"], capture_output=True, text=True, check=True)
            return res.stdout or ""
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # 2. Try X11 (xclip)
        try:
            res = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, check=True)
            return res.stdout or ""
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # 3. Try X11 (xsel)
        try:
            res = subprocess.run(["xsel", "--clipboard", "--output"], capture_output=True, text=True, check=True)
            return res.stdout or ""
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    # Generic fallback
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception as e:
        print(f"⚠️ Clipboard read error: {e}")
        if OS == "Linux":
            print("💡 Tip: Install xclip or wl-clipboard to enable clipboard integration:")
            print("   Debian/Ubuntu: sudo apt install xclip wl-clipboard")
            print("   Fedora: sudo dnf install xclip wl-clipboard")
            print("   Arch: sudo pacman -S xclip wl-clipboard")
        return ""

def clipboard_monitor():
    try:
        last_text = get_clipboard()
    except:
        last_text = ""
        
    while True:
        try:
            time.sleep(0.5)
            current_text = get_clipboard()
            if current_text and current_text.strip() and current_text != last_text:
                last_text = current_text
                ok = add_clip(current_text)
                if ok:
                    generate_viewer()
                    print(f"  ✅ Auto-Saved from clipboard: {current_text[:60].replace(chr(10),' ')}...")
        except Exception:
            pass

def is_code(text):
    # Quick heuristics to check if text is likely code
    code_indicators = ["def ", "import ", "class ", "const ", "let ", "function", "<html>", "css", "void ", "#include", "public class", "fn ", "impl "]
    if any(ind in text for ind in code_indicators):
        return True
    if len(text.splitlines()) > 3 and any(char in text for char in ['{', '}', ';', '=', ':', '(', ')']):
        return True
    return False

def generate_viewer():
    clips = load_clips()
    rows = ""
    for c in clips:
        text = c["text"]
        preview = text[:600].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        
        # Check if code-like to style it
        code_class = " clip-code" if is_code(text) else ""
        
        # Escape quotes for data-text attribute so it won't break the HTML
        escaped_text = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"','&quot;').replace("'","&#39;")
        
        rows += f"""<div class="clip-card" onclick="copyClip(this)" data-text="{escaped_text}">
          <div class="clip-content{code_class}">{preview}</div>
          <div class="clip-footer">
            <div class="clip-time">
              <span>🕒</span>
              <span>{c['time']}</span>
            </div>
            <div class="clip-action-hint">Click to Copy ✨</div>
          </div>
        </div>\n"""

    empty_html = """<div class="empty-state">
      <div class="empty-icon">📭</div>
      <div class="empty-title">Abhi koi clip nahi hai</div>
      <p class="empty-desc">Koi text copy karo ya select karke <strong>Ctrl + Alt + Q</strong> dabao, aur vo turant yahan save ho jayega!</p>
    </div>"""

    # We will build the full premium HTML structure
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
      --success-bg: rgba(16, 185, 129, 0.15);
      --radius-lg: 16px;
      --radius-md: 12px;
      --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background: var(--bg-gradient);
      color: var(--text-main);
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding-bottom: 60px;
      overflow-y: scroll;
    }}

    header {{
      width: 100%;
      background: rgba(10, 15, 30, 0.75);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border-color);
      position: sticky;
      top: 0;
      z-index: 10;
      padding: 18px 24px;
    }}

    .header-container {{
      max-width: 800px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
    }}

    .logo-container {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    .logo-icon {{
      font-size: 28px;
      filter: drop-shadow(0 2px 8px rgba(99, 102, 241, 0.3));
    }}

    h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: 24px;
      font-weight: 700;
      background: var(--accent-gradient);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}

    .badge {{
      background: var(--accent-gradient);
      color: #ffffff;
      font-size: 13px;
      font-weight: 600;
      padding: 6px 14px;
      border-radius: 20px;
      box-shadow: 0 4px 12px rgba(99, 102, 241, 0.25);
    }}

    .container {{
      width: 100%;
      max-width: 800px;
      padding: 24px;
    }}

    .info-card {{
      background: var(--panel-bg);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-lg);
      padding: 16px 20px;
      margin-bottom: 24px;
      display: flex;
      align-items: center;
      gap: 14px;
      font-size: 14px;
      color: var(--text-muted);
      line-height: 1.5;
    }}

    .info-card-icon {{
      font-size: 22px;
    }}

    kbd {{
      background: rgba(255, 255, 255, 0.1);
      border: 1px solid rgba(255, 255, 255, 0.15);
      color: var(--text-main);
      padding: 3px 8px;
      border-radius: 6px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }}

    .search-wrapper {{
      position: relative;
      margin-bottom: 24px;
    }}

    .search-input {{
      width: 100%;
      background: var(--panel-bg);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      color: var(--text-main);
      font-size: 16px;
      padding: 14px 16px 14px 48px;
      outline: none;
      transition: var(--transition);
    }}

    .search-input:focus {{
      border-color: var(--accent-color);
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15), 0 4px 20px rgba(0, 0, 0, 0.35);
    }}

    .search-icon {{
      position: absolute;
      left: 16px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 18px;
      pointer-events: none;
    }}

    .clips-list {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}

    .clip-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 18px;
      cursor: pointer;
      transition: var(--transition);
      position: relative;
      overflow: hidden;
      animation: fadeIn 0.4s ease-out;
    }}

    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(10px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .clip-card::before {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      width: 4px;
      height: 100%;
      background: var(--accent-gradient);
      opacity: 0;
      transition: var(--transition);
    }}

    .clip-card:hover {{
      background: var(--card-hover);
      border-color: var(--border-hover);
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
    }}

    .clip-card:hover::before {{
      opacity: 1;
    }}

    .clip-card.copied {{
      border-color: var(--success);
      background: var(--success-bg);
    }}

    .clip-content {{
      font-size: 15px;
      line-height: 1.6;
      color: var(--text-main);
      word-break: break-word;
      white-space: pre-wrap;
      max-height: 220px;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 10;
      -webkit-box-orient: vertical;
    }}

    .clip-card.copied .clip-content {{
      color: #ffffff;
    }}

    /* Monospace formatting for code blocks */
    .clip-content.clip-code {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 13.5px;
      background: rgba(0, 0, 0, 0.25);
      padding: 12px 16px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.03);
    }}

    .clip-footer {{
      margin-top: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      border-top: 1px solid rgba(255, 255, 255, 0.04);
      padding-top: 10px;
    }}

    .clip-time {{
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .clip-action-hint {{
      color: var(--accent-light);
      font-weight: 500;
      opacity: 0;
      transform: translateX(5px);
      transition: var(--transition);
    }}

    .clip-card:hover .clip-action-hint {{
      opacity: 1;
      transform: translateX(0);
    }}

    .toast {{
      position: fixed;
      bottom: 28px;
      background: var(--accent-gradient);
      color: #ffffff;
      font-weight: 600;
      font-size: 14px;
      padding: 12px 24px;
      border-radius: 30px;
      box-shadow: 0 10px 25px rgba(99, 102, 241, 0.35);
      opacity: 0;
      transform: translateY(20px);
      transition: var(--transition);
      z-index: 100;
      pointer-events: none;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .toast.show {{
      opacity: 1;
      transform: translateY(0);
    }}

    .empty-state {{
      text-align: center;
      padding: 80px 24px;
      color: var(--text-muted);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 16px;
    }}

    .empty-icon {{
      font-size: 64px;
      animation: float 3s ease-in-out infinite;
    }}

    @keyframes float {{
      0%, 100% {{ transform: translateY(0); }}
      50% {{ transform: translateY(-10px); }}
    }}

    .empty-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 20px;
      color: var(--text-main);
      font-weight: 600;
    }}

    .empty-desc {{
      font-size: 14px;
      max-width: 360px;
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-container">
      <div class="logo-container">
        <span class="logo-icon">📋</span>
        <h1>Quick<span>Clip</span></h1>
      </div>
      <span class="badge" id="clip-count">{len(clips)} clips</span>
    </div>
  </header>

  <div class="container">
    <div class="info-card">
      <span class="info-card-icon">💡</span>
      <div>
        <strong>Auto-Save is ON!</strong> Select any text and press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>Q</kbd> to auto-copy & save, or just perform a standard copy (<kbd>Ctrl</kbd> + <kbd>C</kbd>).
      </div>
    </div>

    <div class="search-wrapper">
      <span class="search-icon">🔍</span>
      <input type="text" id="search" class="search-input" placeholder="Search saved clips..." oninput="filterClips()">
    </div>

    <div class="clips-list" id="clips-list">
      {rows if clips else empty_html}
    </div>
  </div>

  <div class="toast" id="toast">
    <span>✅</span> Copied to Clipboard!
  </div>

  <script>
    function copyClip(el) {{
      const text = el.getAttribute('data-text')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&');

      navigator.clipboard.writeText(text).then(() => {{
        el.classList.add('copied');
        const toast = document.getElementById('toast');
        toast.classList.add('show');
        setTimeout(() => {{
          toast.classList.remove('show');
          el.classList.remove('copied');
        }}, 1600);
      }}).catch(err => {{
        console.error('Failed to copy: ', err);
      }});
    }}

    function filterClips() {{
      const query = document.getElementById('search').value.toLowerCase();
      document.querySelectorAll('.clip-card').forEach(card => {{
        const text = card.getAttribute('data-text').toLowerCase();
        card.style.display = text.includes(query) ? 'block' : 'none';
      }});
    }}

    // Save scroll position and search text to localStorage before reload
    window.addEventListener('beforeunload', () => {{
      localStorage.setItem('scrollPos', window.scrollY);
      localStorage.setItem('searchQuery', document.getElementById('search').value);
    }});

    // Restore scroll position and search text on load
    window.addEventListener('DOMContentLoaded', () => {{
      const query = localStorage.getItem('searchQuery');
      if (query) {{
        document.getElementById('search').value = query;
        filterClips();
      }}
      const scrollPos = localStorage.getItem('scrollPos');
      if (scrollPos) {{
        window.scrollTo(0, parseInt(scrollPos, 10));
      }}
    }});

    // Reload immediately when the page gains focus or becomes visible
    window.addEventListener('focus', () => {{
      location.reload();
    }});

    // Auto-reload only when the window is NOT focused (e.g. on a second monitor)
    setInterval(() => {{
      if (!document.hasFocus() && document.visibilityState === 'visible') {{
        location.reload();
      }}
    }}, 5000);
  </script>
</body>
</html>"""

    p = SAVE_DIR / "viewer.html"
    p.write_text(html, encoding="utf-8")
    return str(p)

def start_listener():
    # Start the clipboard monitor thread
    monitor_thread = threading.Thread(target=clipboard_monitor, daemon=True)
    monitor_thread.start()

    # Try starting the keyboard hotkey listener
    try:
        from pynput import keyboard
        pressed = set()
        keyboard_controller = keyboard.Controller()

        def trigger_copy():
            try:
                # Simulate Ctrl + C (standard for Windows & Linux)
                keyboard_controller.press(keyboard.Key.ctrl)
                keyboard_controller.press('c')
                keyboard_controller.release('c')
                keyboard_controller.release(keyboard.Key.ctrl)
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
                # Simulate copy first to grab selected text
                trigger_copy()
                # Wait briefly for OS clipboard to update
                time.sleep(0.2)
                text = get_clipboard()
                if text.strip():
                    ok = add_clip(text)
                    if ok:
                        generate_viewer()
                        print(f"  ✅ Saved (hotkey): {text[:60].replace(chr(10),' ')}...")
                    else:
                        print("  ⚠️ Duplicate — skip kiya.")
                else:
                    print("  ⚠️ Clipboard empty! Select text and try again.")

        def on_release(key):
            pressed.discard(key)

        print("="*52)
        print("   📋 QuickClip chal raha hai!")
        print("   Auto-Copy: Background monitor active (copy text to auto-save)")
        print("   Shortcut: Ctrl + Alt + Q (auto-copy selected text)")
        print(f"   Clips: {CLIPS_FILE}")
        print(f"   Viewer: {SAVE_DIR}/viewer.html")
        print("   Rokne ke liye: Ctrl+C")
        print("="*52)

        with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
            l.join()

    except Exception as e:
        print("="*52)
        print("   📋 QuickClip chal raha hai (Clipboard Monitor Mode)!")
        print("   Auto-Copy: Background monitor active (copy text to auto-save)")
        print("   ⚠️ Note: Keyboard shortcut disabled due to environment limits.")
        print(f"   Clips: {CLIPS_FILE}")
        print(f"   Viewer: {SAVE_DIR}/viewer.html")
        print("   Rokne ke liye: Ctrl+C")
        print("="*52)

        # Keep main thread alive if keyboard listener couldn't start
        while True:
            time.sleep(1)

if __name__ == "__main__":
    generate_viewer()
    try:
        start_listener()
    except KeyboardInterrupt:
        print("\nBand ho gaya. Alvida!")
    except ImportError:
        print("ERROR: pip3 install pynput pyperclip --break-system-packages")