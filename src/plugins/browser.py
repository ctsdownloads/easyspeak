"""
Browser Plugin - Qutebrowser voice control via IPC
"""

import re
import sys
import time
from pathlib import Path

NAME = "browser"
DESCRIPTION = "Qutebrowser voice control"

COMMANDS = [
    "numbers - show click hints",
    "[number] - click hint (e.g. 'one' = 1, 'zero two' = 02)",
    "back - go back",
    "forward - go forward",
    "scroll up/down - scroll page",
    "top / bottom - jump to top/bottom",
    "reload - refresh page",
    "new tab - open new tab",
    "close tab - close current tab",
    "next tab / last tab - switch tabs",
    "find [text] - search on page",
    "go to [site] - open bookmarked site",
    "search [query] - search the web",
]

core = None

# Number words for hint selection
HINT_NUMBERS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "won": "1",
    "wan": "1",
    "two": "2",
    "to": "2",
    "too": "2",
    "tu": "2",
    "three": "3",
    "tree": "3",
    "free": "3",
    "four": "4",
    "for": "4",
    "fore": "4",
    "five": "5",
    "six": "6",
    "sex": "6",
    "seven": "7",
    "eight": "8",
    "ate": "8",
    "nine": "9",
    "nein": "9",
    "0": "0",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "7": "7",
    "8": "8",
    "9": "9",
}

BOOKMARKS = {
    "youtube": "https://youtube.com",
    "google": "https://google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "reddit": "https://reddit.com",
    "twitter": "https://twitter.com",
    "facebook": "https://facebook.com",
    "amazon": "https://amazon.com",
    "netflix": "https://netflix.com",
    "duckduckgo": "https://duckduckgo.com",
    "duck": "https://duckduckgo.com",
}

# Smart scroll JS - finds the actual scrollable element (works on split-pane layouts)
SCROLL_DOWN_JS = "(function(){var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);while(el){if(el.scrollHeight>el.clientHeight&&getComputedStyle(el).overflowY!=='visible'){el.scrollBy(0,300);return}el=el.parentElement}window.scrollBy(0,300)})()"

SCROLL_UP_JS = "(function(){var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);while(el){if(el.scrollHeight>el.clientHeight&&getComputedStyle(el).overflowY!=='visible'){el.scrollBy(0,-300);return}el=el.parentElement}window.scrollBy(0,-300)})()"

PAGE_DOWN_JS = "(function(){var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);while(el){if(el.scrollHeight>el.clientHeight&&getComputedStyle(el).overflowY!=='visible'){el.scrollBy(0,el.clientHeight*0.9);return}el=el.parentElement}window.scrollBy(0,window.innerHeight*0.9)})()"

PAGE_UP_JS = "(function(){var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);while(el){if(el.scrollHeight>el.clientHeight&&getComputedStyle(el).overflowY!=='visible'){el.scrollBy(0,-el.clientHeight*0.9);return}el=el.parentElement}window.scrollBy(0,-window.innerHeight*0.9)})()"

SCROLL_TOP_JS = "(function(){var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);while(el){if(el.scrollHeight>el.clientHeight&&getComputedStyle(el).overflowY!=='visible'){el.scrollTo(0,0);return}el=el.parentElement}window.scrollTo(0,0)})()"

SCROLL_BOTTOM_JS = "(function(){var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);while(el){if(el.scrollHeight>el.clientHeight&&getComputedStyle(el).overflowY!=='visible'){el.scrollTo(0,el.scrollHeight);return}el=el.parentElement}window.scrollTo(0,document.body.scrollHeight)})()"


# Lines this plugin requires in ~/.config/qutebrowser/config.py. Each is
# checked grep-style (substring on the file as a whole) and appended
# individually if absent — the user's other settings are left intact.
REQUIRED_QUTEBROWSER_LINES = [
    "config.load_autoconfig(False)",
    "c.hints.chars = '0123456789'",
]


def ensure_qutebrowser_config():
    """Append any missing required lines to qutebrowser's config.py.

    Preserves everything else the user has written. Tolerates read-only
    configs (e.g. Nix Home-Manager symlinks into /nix/store): on a write
    failure we emit a polite note telling the user which lines to add
    themselves, rather than crashing startup.
    """
    cfg = Path.home() / ".config" / "qutebrowser" / "config.py"

    try:
        cfg.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _note_missing_qb_lines(
            cfg,
            REQUIRED_QUTEBROWSER_LINES,
            reason=f"could not create {cfg.parent} ({e})",
        )
        return

    try:
        existing = cfg.read_text() if cfg.exists() else ""
    except OSError as e:
        _note_missing_qb_lines(
            cfg, REQUIRED_QUTEBROWSER_LINES, reason=f"could not read it ({e})"
        )
        return

    missing = [line for line in REQUIRED_QUTEBROWSER_LINES if line not in existing]
    if not missing:
        return

    separator = "" if not existing or existing.endswith("\n") else "\n"
    updated = existing + separator + "\n".join(missing) + "\n"

    try:
        cfg.write_text(updated)
    except OSError as e:
        _note_missing_qb_lines(cfg, missing, reason=f"is read-only ({e})")
        return

    verb = "wrote" if not existing else "updated"
    added = "; ".join(missing)
    print(f"browser: {verb} {cfg} (added: {added})", file=sys.stderr)


def _note_missing_qb_lines(cfg, lines, reason):
    """Politely tell the user to add missing qutebrowser config lines."""
    body = "\n".join(f"  {line}" for line in lines)
    print(
        f"browser: note: {cfg} {reason}. "
        f"Please make sure your qutebrowser config includes:\n{body}",
        file=sys.stderr,
    )


def setup(c):
    global core
    core = c
    ensure_qutebrowser_config()


def qb(command):
    """Send command to qutebrowser via IPC"""
    print(f"  🌐 qutebrowser :{command}")
    core.host_run(["qutebrowser", f":{command}"])


def qb_open(url):
    """Open URL in qutebrowser"""
    core.host_run(["qutebrowser", url])


def parse_hint_numbers(cmd):
    """Extract hint numbers from spoken words"""
    clean = re.sub(r"[.,!?\-]", " ", cmd.lower())
    words = clean.split()
    digits = []
    for word in words:
        if word in HINT_NUMBERS:
            digits.append(HINT_NUMBERS[word])
    return "".join(digits)


def looks_like_hint(cmd):
    """Check if command looks like a hint number (short, mostly digits/number words)"""
    clean = re.sub(r"[.,!?\-\s]", "", cmd.lower())
    # Must be short
    if len(clean) > 6:
        return False
    # Direct digits like "02", "92"
    if clean.replace("o", "0").isdigit():
        return True
    # Check if all words are number words
    words = cmd.lower().split()
    if len(words) <= 3 and all(w.strip(".,!?") in HINT_NUMBERS for w in words):
        return True
    return False


def parse_hint_number(cmd):
    """Parse spoken numbers into hint string. 'zero two' -> '02', 'ninety three' -> '93'"""
    # Number word mappings
    NUM_WORDS = {
        "zero": "0",
        "oh": "0",
        "o": "0",
        "one": "1",
        "won": "1",
        "wan": "1",
        "two": "2",
        "to": "2",
        "too": "2",
        "tu": "2",
        "three": "3",
        "tree": "3",
        "free": "3",
        "four": "4",
        "for": "4",
        "fore": "4",
        "five": "5",
        "six": "6",
        "sex": "6",
        "seven": "7",
        "eight": "8",
        "ate": "8",
        "nine": "9",
        "nein": "9",
        # Tens
        "ten": "10",
        "eleven": "11",
        "twelve": "12",
        "thirteen": "13",
        "fourteen": "14",
        "fifteen": "15",
        "sixteen": "16",
        "seventeen": "17",
        "eighteen": "18",
        "nineteen": "19",
        "twenty": "2",
        "thirty": "3",
        "forty": "4",
        "fifty": "5",
        "sixty": "6",
        "seventy": "7",
        "eighty": "8",
        "ninety": "9",
    }

    result = []
    words = re.sub(r"[.,!?\-]", " ", cmd.lower()).split()

    for word in words:
        # Direct digit
        if word.isdigit():
            result.append(word)
        # Word to digit
        elif word in NUM_WORDS:
            result.append(NUM_WORDS[word])

    return "".join(result)


def parse_spoken_url(spoken):
    """Convert spoken URL to actual URL. 'claude dot ai' -> 'https://claude.ai'"""
    url = spoken.lower().strip()

    # Replace spoken elements
    url = url.replace(" dot ", ".")
    url = url.replace(" slash ", "/")
    url = url.replace(" colon ", ":")
    url = url.replace(" dash ", "-")
    url = url.replace(" hyphen ", "-")
    url = url.replace(" underscore ", "_")

    # Remove remaining spaces
    url = url.replace(" ", "")

    # Add https:// if no protocol
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    return url


def listen_for_hint(core):
    """Listen for hint number after showing hints"""
    print("  🔢 Say hint number (e.g. 'zero two'), 'exit links' to cancel")

    # Small delay to let hints render
    time.sleep(0.3)

    # Clear audio buffer
    try:
        core.stream.read(core.stream.get_read_available(), exception_on_overflow=False)
    except:
        pass

    # Wait for speech
    first = core.wait_for_speech(timeout=10)
    if not first:
        print("  ⏱ Timeout - hints cancelled")
        qb("mode-leave")
        print("  [listen_for_hint returning - timeout]")
        return

    audio = first + core.record_until_silence()
    cmd = core.transcribe(
        audio, prompt="zero one two three four five six seven eight nine"
    )

    if not cmd:
        print("  [listen_for_hint - no transcription, waiting again]")
        # Try one more time
        first = core.wait_for_speech(timeout=5)
        if first:
            audio = first + core.record_until_silence()
            cmd = core.transcribe(
                audio, prompt="zero one two three four five six seven eight nine"
            )
        if not cmd:
            qb("mode-leave")
            print("  [listen_for_hint returning - no transcription]")
            return

    cmd_lower = cmd.lower().strip(".,!? ")
    print(f"  ← {cmd_lower}")

    # Cancel
    if cmd_lower in [
        "exit links",
        "exit link",
        "cancel",
        "nevermind",
        "stop",
        "close",
        "exit",
    ]:
        qb("mode-leave")
        print("  ✗ Hints cancelled")
        print("  [listen_for_hint returning - cancelled]")
        return

    # Parse hint number
    hint = parse_hint_number(cmd_lower)

    if hint:
        print(f"  🔤 Hint: '{cmd_lower}' → '{hint}'")
        qb(f"hint-follow {hint}")
        # Wait for page to load, then clear any stuck state
        time.sleep(1.0)
        qb("fake-key <Escape>")
    else:
        # Try phonetic fallback
        hint = parse_hint_numbers(cmd_lower)
        if hint:
            print(f"  🔤 Phonetic: '{cmd_lower}' → '{hint}'")
            qb(f"hint-follow {hint}")
            # Wait for page to load, then clear any stuck state
            time.sleep(1.0)
            qb("fake-key <Escape>")
        else:
            # Not a hint - might be a browser command, pass it through
            print(f"  ↪ Not a hint, trying as command: '{cmd_lower}'")
            qb("mode-leave")
            handle_browser_command(cmd_lower, core)

    print("  [listen_for_hint returning - complete]")


# Global control phrases owned by the sleep and base plugins. This plugin is
# routed before them (filename order), and qb() would spawn a fresh qutebrowser
# window for each — e.g. "stop" -> :stop, "go to sleep" -> :quickmark-load
# sleep. Decline them so they fall through to the plugin that actually owns
# them (deactivate / quit). Exact-matched quit words mirror zz_base; the sleep
# phrases are substring-matched to match sleep.py.
RESERVED_GLOBAL_EXACT = ("stop", "exit", "quit", "goodbye", "bye")
RESERVED_GLOBAL_SUBSTR = ("go to sleep", "goto sleep", "stop listening")


def _is_reserved_global(cmd_lower):
    return cmd_lower in RESERVED_GLOBAL_EXACT or any(
        phrase in cmd_lower for phrase in RESERVED_GLOBAL_SUBSTR
    )


def handle(cmd, core):
    cmd_lower = cmd.lower().strip(".,!? ")

    # Global sleep/quit commands belong to other plugins; if we matched them as
    # browser commands we would open qutebrowser instead. Let them through.
    if _is_reserved_global(cmd_lower):
        return None

    # --- Enter browser mode (explicit) ---
    if cmd_lower in ["browser", "browser mode", "open browser", "launch browser"]:
        core.host_run(["qutebrowser"], background=True)
        browser_mode(core)
        return True

    # --- Single browser commands → enters browser mode ---
    try:
        result = handle_browser_command(cmd_lower, core)
        if result:
            print("  → Entering browser mode...")
            browser_mode(core)
            return True
    except Exception as e:
        print(f"  ! Browser error: {e}")
        return True

    return None


def browser_mode(core):
    """Continuous listening for browser commands"""
    core.speak("Browser")
    print("=== BROWSER MODE ACTIVE ===")
    print("Say commands directly. 'exit browser' to leave.")

    while True:
        try:
            core.stream.read(
                core.stream.get_read_available(), exception_on_overflow=False
            )
        except:
            pass

        first = core.wait_for_speech(timeout=30)
        if not first:
            continue

        audio = first + core.record_until_silence()
        cmd = core.transcribe(audio)

        if not cmd:
            continue

        cmd_lower = cmd.lower().strip(".,!? ")
        print(f"  [browser] {cmd_lower}")

        # Exit browser mode - require explicit phrase
        if cmd_lower in [
            "exit browser",
            "leave browser",
            "stop browser",
            "quit browser",
            "close browser",
        ]:
            print("=== BROWSER MODE EXIT ===")
            return

        # Grid triggers - escape to grid mode
        grid_triggers = {"grid", "grit", "grip", "mouse", "pointer", "cursor"}
        if any(w in cmd_lower for w in grid_triggers):
            print("=== BROWSER MODE EXIT → GRID ===")
            core.route_command(cmd_lower)
            return

        # Handle browser command
        if not handle_browser_command(cmd_lower, core):
            print(f"  ? Unknown: {cmd_lower}")


def handle_browser_command(cmd_lower, core):
    # --- Hints ---
    if cmd_lower in [
        "numbers",
        "number",
        "hints",
        "hint",
        "show numbers",
        "show hints",
        "links",
        "link",
        "blanks",
        "blinks",
        "lynx",
        "lings",
        "lanes",
        "licks",
        "clicks",
    ]:
        qb("hint")
        listen_for_hint(core)
        return True

    if cmd_lower in [
        "numbers new",
        "number new",
        "hints new",
        "new numbers",
        "links new",
        "link new",
        "blanks new",
        "blinks new",
        "lynx new",
    ]:
        qb("hint links tab")
        listen_for_hint(core)
        return True

    # --- Navigation ---
    if cmd_lower in ["back", "go back", "previous page"]:
        qb("back")
        return True

    if cmd_lower in ["forward", "go forward", "next page"]:
        qb("forward")
        return True

    if cmd_lower in ["reload", "refresh", "reload page"]:
        qb("reload")
        return True

    if cmd_lower in ["stop", "stop loading"]:
        qb("stop")
        return True

    # --- Scrolling ---
    if cmd_lower in ["scroll down", "down"]:
        qb(f"jseval -q {SCROLL_DOWN_JS}")
        return True

    if cmd_lower in ["scroll up", "up"]:
        qb(f"jseval -q {SCROLL_UP_JS}")
        return True

    if "page" in cmd_lower and "down" in cmd_lower:
        qb(f"jseval -q {PAGE_DOWN_JS}")
        return True

    if "page" in cmd_lower and "up" in cmd_lower:
        qb(f"jseval -q {PAGE_UP_JS}")
        return True

    if cmd_lower in ["top", "go to top", "scroll to top"]:
        qb(f"jseval -q {SCROLL_TOP_JS}")
        return True

    if cmd_lower in ["bottom", "go to bottom", "scroll to bottom"]:
        qb(f"jseval -q {SCROLL_BOTTOM_JS}")
        return True

    # --- Tabs ---
    # Switch to specific tab by number
    if cmd_lower.startswith("tab "):
        tab_part = cmd_lower.replace("tab ", "").strip()
        tab_num = parse_hint_number(tab_part)
        if tab_num and tab_num.isdigit():
            qb(f"tab-focus {tab_num}")
            return True

    if cmd_lower in ["new tab", "open tab"]:
        qb("open -t about:blank")
        return True

    if cmd_lower in ["close tab", "close this tab"]:
        qb("tab-close")
        return True

    if cmd_lower in ["next tab", "tab right"]:
        qb("tab-next")
        return True

    if cmd_lower in ["last tab", "previous tab", "tab left"]:
        qb("tab-prev")
        return True

    if cmd_lower in ["undo tab", "restore tab", "reopen tab"]:
        qb("undo")
        return True

    # --- Find ---
    if cmd_lower.startswith("find "):
        query = cmd_lower.replace("find ", "", 1).strip()
        if query:
            qb(f"search {query}")
            return True

    if cmd_lower in ["find next", "next match"]:
        qb("search-next")
        return True

    if cmd_lower in ["find previous", "previous match"]:
        qb("search-prev")
        return True

    # --- Escape ---
    if cmd_lower in ["escape", "cancel", "nevermind"]:
        qb("mode-leave")
        return True

    # --- Bookmarks ---
    # Save current page as quickmark
    if (
        "bookmark this" in cmd_lower or "save this" in cmd_lower
    ) and " as " in cmd_lower:
        name = cmd_lower.split(" as ")[-1].strip()
        if name:
            core.speak(f"Saved as {name}.")
            qb(f"quickmark-save {name}")
            return True

    # Load quickmark (user-saved)
    if cmd_lower.startswith("go to ") or cmd_lower.startswith("open "):
        target = cmd_lower.replace("go to ", "").replace("open ", "").strip()

        # Check predefined bookmarks first
        for site, url in BOOKMARKS.items():
            if site == target:
                core.speak(f"Opening {site}.")
                qb_open(url)
                return True

        # Try as spoken URL (contains "dot")
        if "dot" in target or "." in target:
            url = parse_spoken_url(target)
            core.speak(f"Opening {url}.")
            qb_open(url)
            return True

        # Don't catch generic "open X" - let other plugins handle it
        # Only use quickmark for explicit "go to X"
        if cmd_lower.startswith("go to "):
            qb(f"quickmark-load {target}")
            return True

        return None  # Let another plugin handle "open X"

    # --- Search ---
    if cmd_lower.startswith("search ") or cmd_lower.startswith("search for "):
        query = cmd_lower.replace("search for ", "").replace("search ", "").strip()
        if query:
            url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
            core.speak(f"Searching for {query}.")
            qb_open(url)
            return True

    # --- Phonetic hint selection (LAST - only if nothing else matched) ---
    # Only try hint parsing if it actually looks like a hint
    if looks_like_hint(cmd_lower):
        # Direct digit input (e.g., "02", "92", "0-2")
        stripped = re.sub(r"[^0-9a-z]", "", cmd_lower)
        if stripped.replace("o", "0").isdigit():
            hint = stripped.replace("o", "0")
            print(f"  🔤 Direct digits: '{cmd_lower}' → '{hint}'")
            qb(f"hint-follow {hint}")
            return True

        # Try phonetic parsing
        hint = parse_hint_numbers(cmd_lower)
        if hint and hint.isdigit():
            print(f"  🔤 Phonetic parsed: '{cmd_lower}' → '{hint}'")
            qb(f"hint-follow {hint}")
            return True

    return None
