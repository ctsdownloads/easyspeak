"""Browser Plugin - Qutebrowser voice control via IPC."""

import logging
import re
import subprocess
import time
from pathlib import Path

from easyspeak.core import mediakeys

logger = logging.getLogger(__name__)

# down, up, tab and escape already mean something in this mode, so every key but
# enter needs the "press" prefix.
BARE_KEYS = frozenset({"enter"})

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
    "next tab / switch tab - go to the next tab",
    "last tab - go to the previous tab",
    "tab [number] - switch to a tab by number",
    "close tab [number] - close a tab (or 'close tab' for this one)",
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
SCROLL_DOWN_JS = (
    "(function(){"
    "var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);"
    "while(el){"
    "var oy=getComputedStyle(el).overflowY;"
    "if(el.scrollHeight>el.clientHeight&&(oy==='auto'||oy==='scroll')){"
    "var was=el.scrollTop;el.scrollBy(0,300);"
    "if(el.scrollTop!==was)return}"
    "el=el.parentElement}"
    "window.scrollBy(0,300)"
    "})()"
)

SCROLL_UP_JS = (
    "(function(){"
    "var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);"
    "while(el){"
    "var oy=getComputedStyle(el).overflowY;"
    "if(el.scrollHeight>el.clientHeight&&(oy==='auto'||oy==='scroll')){"
    "var was=el.scrollTop;el.scrollBy(0,-300);"
    "if(el.scrollTop!==was)return}"
    "el=el.parentElement}"
    "window.scrollBy(0,-300)"
    "})()"
)

PAGE_DOWN_JS = (
    "(function(){"
    "var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);"
    "while(el){"
    "var oy=getComputedStyle(el).overflowY;"
    "if(el.scrollHeight>el.clientHeight&&(oy==='auto'||oy==='scroll')){"
    "var was=el.scrollTop;el.scrollBy(0,el.clientHeight*0.9);"
    "if(el.scrollTop!==was)return}"
    "el=el.parentElement}"
    "window.scrollBy(0,window.innerHeight*0.9)"
    "})()"
)

PAGE_UP_JS = (
    "(function(){"
    "var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);"
    "while(el){"
    "var oy=getComputedStyle(el).overflowY;"
    "if(el.scrollHeight>el.clientHeight&&(oy==='auto'||oy==='scroll')){"
    "var was=el.scrollTop;el.scrollBy(0,-el.clientHeight*0.9);"
    "if(el.scrollTop!==was)return}"
    "el=el.parentElement}"
    "window.scrollBy(0,-window.innerHeight*0.9)"
    "})()"
)

SCROLL_TOP_JS = (
    "(function(){"
    "var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);"
    "while(el){"
    "var oy=getComputedStyle(el).overflowY;"
    "if(el.scrollHeight>el.clientHeight&&(oy==='auto'||oy==='scroll')){"
    "el.scrollTo(0,0);return}"
    "el=el.parentElement}"
    "window.scrollTo(0,0)"
    "})()"
)

SCROLL_BOTTOM_JS = (
    "(function(){"
    "var el=document.elementFromPoint(window.innerWidth/2,window.innerHeight/2);"
    "while(el){"
    "var oy=getComputedStyle(el).overflowY;"
    "if(el.scrollHeight>el.clientHeight&&(oy==='auto'||oy==='scroll')){"
    "el.scrollTo(0,el.scrollHeight);return}"
    "el=el.parentElement}"
    "window.scrollTo(0,document.body.scrollHeight)"
    "})()"
)


REQUIRED_QUTEBROWSER_LINES = [
    "config.load_autoconfig(False)",
    "c.hints.chars = '0123456789'",
    "c.content.tls.certificate_errors = 'ask-block-thirdparty'",
    "c.content.notifications.enabled = False",
    "c.content.geolocation = False",
    # Autoplaying video ads talk over the wake word and hold the microphone's
    # attention, which makes every command less likely to be heard.
    "c.content.autoplay = False",
]


def adblock_method():
    """Return the strongest ad-blocking method qutebrowser can actually run.

    Ad overlays and newsletter interstitials are numbered like anything else, so
    they take hint numbers away from the page underneath and a spoken hint lands
    on a popup instead of the link the user meant. "both" adds Brave's ABP engine,
    which is what catches those overlays -- but it needs the `adblock` module, and
    without it qutebrowser complains on every single page load, which is worse
    than the ads. Host blocking is built in and needs nothing.

    The module has to be importable by the interpreter that *runs* qutebrowser,
    which is often not the `python3` on `PATH`: a virtualenv, a distro package, a
    Flatpak or a Nix build each ship their own. So this asks qutebrowser itself
    rather than probing a stray interpreter, which answered correctly only when
    the two happened to coincide. `--version` lists each optional module as
    `adblock: <version>` when present and `adblock: no` when not, so a leading
    digit means "both"; installing the module later is still picked up on the
    next start. That call imports Qt and so is slow rather than instant, so the
    15-second timeout is a ceiling for a wedged process, not an expected wait --
    past it, host blocking (which always works) is assumed.
    """
    try:
        version = subprocess.run(
            ["qutebrowser", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,  # seconds
        )
    except (OSError, subprocess.TimeoutExpired):
        return "hosts"  # no qutebrowser, or it hung: host blocking always works
    available = re.search(r"^\s*adblock:\s*\d", version.stdout, re.MULTILINE)
    return "both" if available else "hosts"


def required_qutebrowser_lines():
    """The config lines EasySpeak needs, suited to what's installed."""
    return [
        *REQUIRED_QUTEBROWSER_LINES,
        f"c.content.blocking.method = '{adblock_method()}'",
    ]


def _setting_name(line):
    """The `c.…` setting a config line assigns, or None if it isn't an assignment.

    Matched with a pattern rather than a literal `" = "` so a user's own spacing --
    `c.foo='bar'` or `c.foo  =  'bar'` -- is still recognised. Missing it would
    append a second assignment for the same setting on every start.
    """
    match = re.match(r"^\s*(c\.[^=\s]+)\s*=\s*\S", line)
    return match.group(1) if match else None


SOFTWARE_RENDERING_LINE = 'c.qt.args = ["disable-gpu-compositing"]'

ADBLOCK_OFF_LINE = "c.content.blocking.enabled = False"


def set_config_line(line, *, wanted):
    """Add or remove one line in qutebrowser's config.py, keyed on its setting.

    Returns None when the config can't be written, so the caller can say why.
    """
    cfg = Path.home() / ".config" / "qutebrowser" / "config.py"
    try:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        existing = cfg.read_text() if cfg.exists() else ""
        kept = [
            text
            for text in existing.splitlines()
            if _setting_name(text) != _setting_name(line)
        ]
        if wanted:
            kept.append(line)
        cfg.write_text("\n".join(kept) + "\n")
    except OSError as exc:
        logger.warning("Could not write %s: %s", cfg, exc)
        return None
    return wanted


def _apply_config_line(core, line, spoken, *, wanted):
    """Write a config toggle and restart qutebrowser so it takes effect."""
    if set_config_line(line, wanted=wanted) is None:
        core.speak("Could not write the browser config.")
        return True
    core.speak(f"{spoken}. Restarting the browser.")
    qb("restart")
    return True


def ensure_qutebrowser_config():
    """Bring qutebrowser's config.py in line with what EasySpeak needs.

    Preserves everything else the user has written. Tolerates read-only configs (e.g.
    Nix Home-Manager symlinks into /nix/store): on a write failure we emit a polite note
    telling the user which lines to add themselves, rather than crashing startup.
    """
    cfg = Path.home() / ".config" / "qutebrowser" / "config.py"

    try:
        cfg.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _note_missing_qb_lines(
            cfg,
            required_qutebrowser_lines(),
            reason=f"could not create {cfg.parent} ({e})",
        )
        return

    try:
        existing = cfg.read_text() if cfg.exists() else ""
    except OSError as e:
        _note_missing_qb_lines(
            cfg, required_qutebrowser_lines(), reason=f"could not read it ({e})"
        )
        return

    wanted = required_qutebrowser_lines()
    lines = existing.splitlines()
    changed = []

    for line in wanted:
        if line in lines:
            continue
        setting = _setting_name(line)
        index = next(
            (
                i
                for i, existing_line in enumerate(lines)
                if _setting_name(existing_line.strip()) == setting
            ),
            None,
        )
        if setting and index is not None:
            lines[index] = line
        else:
            lines.append(line)
        changed.append(line)

    if not changed:
        return

    try:
        cfg.write_text("\n".join(lines) + "\n")
    except OSError as e:
        _note_missing_qb_lines(cfg, changed, reason=f"is read-only ({e})")
        return

    verb = "wrote" if not existing else "updated"
    logger.debug("%s %s (%s)", verb, cfg, "; ".join(changed))


def _note_missing_qb_lines(cfg, lines, reason):
    """Politely tell the user to add missing qutebrowser config lines."""
    body = "\n".join(f"  {line}" for line in lines)
    logger.warning(
        "%s %s. Please make sure your qutebrowser config includes:\n%s",
        cfg,
        reason,
        body,
    )


def setup(c):
    """Store the core reference and write the required qutebrowser config."""
    global core
    core = c
    c.browser_page_js_stale = False
    c.in_browser_mode = False
    ensure_qutebrowser_config()


def qb(command):
    """Send command to qutebrowser via IPC."""
    logger.debug("  🌐 qutebrowser :%s", command)
    core.host_run(["qutebrowser", f":{command}"])


def qb_open(url):
    """Open URL in qutebrowser."""
    core.host_run(["qutebrowser", url])


def parse_hint_numbers(cmd):
    """Extract hint numbers from spoken words."""
    clean = re.sub(r"[.,!?\-]", " ", cmd.lower())
    words = clean.split()
    digits = [HINT_NUMBERS[word] for word in words if word in HINT_NUMBERS]
    return "".join(digits)


def looks_like_hint(cmd):
    """Check if command looks like a hint number (short, mostly digits/number words)."""
    clean = re.sub(r"[.,!?\-\s]", "", cmd.lower())
    # Must be short
    if len(clean) > 6:
        return False
    # Direct digits like "02", "92"
    if clean.replace("o", "0").isdigit():
        return True
    # Check if all words are number words
    words = cmd.lower().split()
    return len(words) <= 3 and all(w.strip(".,!?") in HINT_NUMBERS for w in words)


def parse_hint_number(cmd):
    """Parse spoken numbers into a hint string ('zero two' -> '02')."""
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
        "third": "3",
        "thee": "3",
        "four": "4",
        "for": "4",
        "fore": "4",
        "ford": "4",
        "forth": "4",
        "fourth": "4",
        "far": "4",
        "five": "5",
        "six": "6",
        "sex": "6",
        "seven": "7",
        "eight": "8",
        "ate": "8",
        "eighth": "8",
        "hate": "8",
        "nine": "9",
        "nein": "9",
        "ninth": "9",
        "mine": "9",
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


# Ways of naming a tab by number, spoken. Anchored so "go to tab 2" is a tab
# switch rather than a bookmark called "tab 2", which is what it used to do.
TAB_PREFIXES = (
    "close tab",
    "switch to tab",
    "switch tab",
    "change to tab",
    "change tab",
    "go to tab",
    "open tab",
    "tab",
)


def parse_tab_number(cmd_lower):
    """The tab number a command names, or None if it doesn't name one."""
    for prefix in TAB_PREFIXES:
        if not cmd_lower.startswith(prefix + " "):
            continue
        number = parse_hint_number(cmd_lower[len(prefix) :].strip())
        if number and number.isdigit():
            return number
    return None


def parse_spoken_url(spoken):
    """Convert spoken URL to actual URL.

    'claude dot ai' -> 'https://claude.ai'.
    """
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


# Phrases that ask for hints. Kept here so the hint listener can recognise one
# arriving while hints are already showing, instead of tearing the mode down.
HINT_TRIGGERS = ("numbers", "number", "links", "link", "hints", "hint")

# fails the same way.
HINT_RETRY_DELAY = 0.6


def _reload_if_page_js_is_stale(core):
    """Reload the page if a history navigation left its scripts unusable.

    `core.browser_page_js_stale` is set by back and forward and cleared here.
    """
    if not core.browser_page_js_stale:
        return
    core.browser_page_js_stale = False
    logger.debug("  ↻ Reloading: page scripts don't survive a history navigation")
    core.speak("Reloading")
    qb("reload")
    time.sleep(RELOAD_SETTLE)


# Time for a reloaded page to become hintable.
RELOAD_SETTLE = 0.8


def show_hints(core):
    """Show the numbered hints, reloading first if history navigation broke them."""
    _reload_if_page_js_is_stale(core)
    qb("hint")


def scroll_page(js, core):
    """Scroll the page, reloading first if history navigation broke its scripts."""
    _reload_if_page_js_is_stale(core)
    qb(f"jseval -q {js}")


def listen_for_hint(core, retries_left=3):
    """Listen for a hint number after showing hints.

    `retries_left` bounds how many times a repeated "numbers" can keep the
    listener open, so a run of mishearings can't recurse without end.
    """
    logger.info("  🔢 Say hint number (e.g. 'zero two'), 'exit links' to cancel")
    core.speak("Ready")

    # Small delay to let hints render
    time.sleep(0.3)

    core.speech.drain()
    core.flush_stream()

    # Wait for speech
    first = core.wait_for_speech(timeout=10)
    if not first:
        if retries_left > 0:
            logger.debug("  ↻ No hints appeared; asking again")
            time.sleep(HINT_RETRY_DELAY)
            qb("fake-key <Escape>")
            show_hints(core)
            listen_for_hint(core, retries_left - 1)
            return
        logger.info("  ⏱ Timeout - hints cancelled")
        core.speak("Hints closed")
        qb("fake-key <Escape>")
        logger.debug("  [listen_for_hint returning - timeout]")
        return

    audio = first + core.record_until_silence()
    cmd = core.transcribe(
        audio, prompt="zero one two three four five six seven eight nine"
    )

    if not cmd:
        logger.debug("  [listen_for_hint - no transcription, waiting again]")
        # Try one more time
        first = core.wait_for_speech(timeout=5)
        if first:
            audio = first + core.record_until_silence()
            cmd = core.transcribe(
                audio, prompt="zero one two three four five six seven eight nine"
            )
        if not cmd:
            qb("fake-key <Escape>")
            logger.debug("  [listen_for_hint returning - no transcription]")
            return

    cmd_lower = cmd.lower().strip(".,!? ")
    logger.debug("  ← %s", cmd_lower)

    if cmd_lower in HINT_TRIGGERS:
        if retries_left <= 0:
            logger.info("  ✗ Hints aren't appearing on this page")
            core.speak("No hints on this page")
            qb("fake-key <Escape>")
            return
        logger.debug("  ↻ Showing hints again")
        qb("fake-key <Escape>")
        show_hints(core)
        listen_for_hint(core, retries_left - 1)
        return

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
        qb("fake-key <Escape>")
        logger.info("  ✗ Hints cancelled")
        core.speak("Hints closed")
        logger.debug("  [listen_for_hint returning - cancelled]")
        return

    # Parse hint number
    hint = parse_hint_number(cmd_lower)

    if hint:
        logger.debug("  🔤 Hint: '%s' → '%s'", cmd_lower, hint)
        qb(f"hint-follow {hint}")
        # Wait for page to load, then clear any stuck state
        time.sleep(1.0)
        qb("fake-key <Escape>")
    else:
        # Try phonetic fallback
        hint = parse_hint_numbers(cmd_lower)
        if hint:
            logger.debug("  🔤 Phonetic: '%s' → '%s'", cmd_lower, hint)
            qb(f"hint-follow {hint}")
            # Wait for page to load, then clear any stuck state
            time.sleep(1.0)
            qb("fake-key <Escape>")
        else:
            logger.info("  ? Heard '%s', which isn't a hint number", cmd_lower)
            logger.debug("  ↪ Not a hint, trying as command: '%s'", cmd_lower)
            qb("fake-key <Escape>")
            handle_browser_command(cmd_lower, core)

    logger.debug("  [listen_for_hint returning - complete]")


LEAVE_BROWSER_MODE = (
    "exit browser",
    "leave browser",
    "stop browser",
    "browser off",
)
CLOSE_BROWSER = (
    "close browser",
    "quit browser",
    "close the browser",
    "quit the browser",
    "close qutebrowser",
)

RESERVED_GLOBAL_EXACT = ("stop", "exit", "quit", "goodbye", "bye")
RESERVED_GLOBAL_SUBSTR = ("go to sleep", "goto sleep", "stop listening")


def _is_reserved_global(cmd_lower):
    return cmd_lower in RESERVED_GLOBAL_EXACT or any(
        phrase in cmd_lower for phrase in RESERVED_GLOBAL_SUBSTR
    )


def _qutebrowser_running(core):
    """Whether a qutebrowser instance is already running.

    Used by [`handle`][plugins.browser.handle] to gate ambiguous navigation commands: we
    only act on them when there is actually a browser to receive them. `pgrep -f`
    (rather than `-x`) matches however the binary is wrapped — e.g. a Nix
    `.qutebrowser-wrapped` launcher — so an open browser isn't missed.
    """
    result = core.host_run(["pgrep", "-f", "qutebrowser"])
    return getattr(result, "returncode", 1) == 0


def handle(cmd, core):
    """Enter browser mode on a browser command; return None otherwise.

    A matching command launches qutebrowser (if needed) and runs the continuous
    browser-mode loop; reserved global commands (sleep/quit) are passed through. Outside
    the explicit "open browser", navigation commands are only acted on when a browser is
    already running, so ambiguous words can't open one.
    """
    cmd_lower = cmd.lower().strip(".,!? ")

    # Global sleep/quit commands belong to other plugins; if we matched them as
    # browser commands we would open qutebrowser instead. Let them through.
    if _is_reserved_global(cmd_lower):
        return None

    # Closing the application works from anywhere, and must not then step into
    # browser mode -- there would be no browser left to drive.
    if cmd_lower in CLOSE_BROWSER:
        if not _qutebrowser_running(core):
            core.speak("The browser isn't running.")
            return True
        qb("quit")
        core.speak("Closing browser.")
        return True

    # Already outside browser mode: acknowledge rather than fall through to the
    # "I didn't understand" path, which is what saying it twice used to get.
    if cmd_lower in LEAVE_BROWSER_MODE:
        return True

    # --- Enter browser mode (explicit) ---
    if cmd_lower in ["browser", "browser mode", "open browser", "launch browser"]:
        if core.in_browser_mode:
            return True  # already there; don't stack a second one
        if not _qutebrowser_running(core):
            core.host_run(["qutebrowser"], background=True, clean_env=True)
        browser_mode(core)
        return True

    if not _qutebrowser_running(core):
        return None

    # --- Single browser commands → enters browser mode ---
    try:
        result = handle_browser_command(cmd_lower, core)
        if result:
            logger.info("  → Entering browser mode...")
            browser_mode(core)
            return True
    except Exception:
        logger.exception("  ! Browser error")
        return True

    return None


def browser_mode(core):
    """Handle browser commands until the user leaves or the mode ends.

    Core owns the listening loop (see
    [`listen_modal`][core.main.EasySpeak.listen_modal]) so the tray keeps working while
    browser mode holds the microphone, and an
    unattended session ends on its own instead of leaving the wake word unreachable.
    """
    core.speak("Browser")
    logger.info("=== BROWSER MODE ACTIVE ===")
    logger.info("Say commands directly. 'exit browser' to leave.")

    core.in_browser_mode = True
    try:
        _run_browser_mode(core)
    finally:
        core.in_browser_mode = False


def _run_browser_mode(core):
    """Dispatch one browser command per utterance until the mode ends."""
    for cmd_lower in core.listen_modal("browser", timeout=30, idle_timeout=180):
        logger.debug("  [browser] %s", cmd_lower)

        # Leave the mode, browser left running
        if cmd_lower in LEAVE_BROWSER_MODE:
            logger.info("=== BROWSER MODE EXIT ===")
            core.speak("Left the browser")
            return

        # Close the application, which leaves the mode too
        if cmd_lower in CLOSE_BROWSER:
            logger.info("=== BROWSER MODE EXIT (closing browser) ===")
            qb("quit")
            core.speak("Closing browser.")
            return

        # Grid triggers - escape to grid mode
        grid_triggers = {"grid", "grit", "grip", "mouse", "pointer", "cursor"}
        if any(w in cmd_lower for w in grid_triggers):
            logger.info("=== BROWSER MODE EXIT → GRID ===")
            core.route_command(cmd_lower)
            return

        if handle_browser_command(cmd_lower, core):
            continue

        logger.debug("  ↪ Not a browser command, routing: %s", cmd_lower)
        if not core.route_command(cmd_lower):
            # A quit command ("goodbye"); take the daemon down with us.
            core.exit_requested = True
            return


FILLER_PREFIXES = ("and ", "so ", "then ", "okay ", "ok ", "um ", "uh ", "now ")


def strip_filler(cmd_lower):
    """Remove a leading filler word Whisper added to the front of a command."""
    for filler in FILLER_PREFIXES:
        if cmd_lower.startswith(filler):
            return cmd_lower[len(filler) :].strip()
    return cmd_lower


def handle_browser_command(cmd_lower, core):
    """Execute a single in-browser command; None if it isn't recognised."""
    cmd_lower = strip_filler(cmd_lower)

    # Said a beat after hint mode already closed; absorbing it beats answering
    # "I didn't understand" to a phrase this plugin owns.
    if cmd_lower in ("exit links", "exit link"):
        return True
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
        show_hints(core)
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
        core.browser_page_js_stale = True
        return True

    if cmd_lower in ["forward", "go forward", "next page"]:
        qb("forward")
        core.browser_page_js_stale = True
        return True

    if cmd_lower in ["reload", "refresh", "reload page"]:
        qb("reload")
        return True

    if cmd_lower in ["stop", "stop loading"]:
        qb("stop")
        return True

    # --- Scrolling ---
    if cmd_lower in ["scroll down", "down"]:
        scroll_page(SCROLL_DOWN_JS, core)
        return True

    if cmd_lower in ["scroll up", "up"]:
        scroll_page(SCROLL_UP_JS, core)
        return True

    if "page" in cmd_lower and "down" in cmd_lower:
        qb(f"jseval -q {PAGE_DOWN_JS}")
        return True

    if "page" in cmd_lower and "up" in cmd_lower:
        qb(f"jseval -q {PAGE_UP_JS}")
        return True

    if cmd_lower in ["top", "go to top", "scroll to top"]:
        scroll_page(SCROLL_TOP_JS, core)
        return True

    if cmd_lower in ["bottom", "go to bottom", "scroll to bottom"]:
        scroll_page(SCROLL_BOTTOM_JS, core)
        return True

    # --- Tabs ---
    if cmd_lower in ["new tab", "open tab"]:
        qb("open -t about:blank")
        return True

    if cmd_lower in ["close tab", "close this tab"]:
        qb("tab-close")
        return True

    if cmd_lower in ["next tab", "tab right", "switch tab", "change tab"]:
        qb("tab-next")
        return True

    if cmd_lower in ["last tab", "previous tab", "tab left"]:
        qb("tab-prev")
        return True

    tab_num = parse_tab_number(cmd_lower)
    if tab_num is not None:
        if cmd_lower.startswith("close"):
            qb(f"tab-focus {tab_num}")
            qb("tab-close")
        else:
            qb(f"tab-focus {tab_num}")
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
        qb("fake-key <Escape>")
        return True

    # --- Browser config toggles ---
    if cmd_lower in ["software rendering", "fix rendering", "fix the display"]:
        return _apply_config_line(
            core, SOFTWARE_RENDERING_LINE, "Software rendering on", wanted=True
        )

    if cmd_lower in ["hardware rendering", "restore rendering"]:
        return _apply_config_line(
            core, SOFTWARE_RENDERING_LINE, "Hardware rendering on", wanted=False
        )

    if cmd_lower in ["allow ads", "stop blocking ads", "disable ad blocking"]:
        return _apply_config_line(
            core, ADBLOCK_OFF_LINE, "Ad blocking off", wanted=True
        )

    if cmd_lower in ["block ads", "enable ad blocking"]:
        return _apply_config_line(
            core, ADBLOCK_OFF_LINE, "Ad blocking on", wanted=False
        )

    # --- Keystrokes ---
    request = mediakeys.parse_key_request(cmd_lower.split(), BARE_KEYS)
    if request is not None:
        if not mediakeys.press_key(*request):
            core.speak("Keystrokes need GNOME.")
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
    if cmd_lower.startswith(("go to ", "open ")):
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
    if cmd_lower.startswith(("search ", "search for ")):
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
            logger.debug("  🔤 Direct digits: '%s' → '%s'", cmd_lower, hint)
            qb(f"hint-follow {hint}")
            return True

        # Try phonetic parsing
        hint = parse_hint_numbers(cmd_lower)
        if hint and hint.isdigit():
            logger.debug("  🔤 Phonetic parsed: '%s' → '%s'", cmd_lower, hint)
            qb(f"hint-follow {hint}")
            return True

    return None
