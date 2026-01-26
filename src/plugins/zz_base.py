"""
Base Plugin - Help and Exit
"""

NAME = "base"
DESCRIPTION = "Help and exit commands"

COMMANDS = [
    "help - list all commands",
    "stop/exit/quit - exit EasySpeak",
]

core = None


def setup(c):
    global core
    core = c


def handle(cmd, core):
    cmd_lower = cmd.lower().strip()

    # Exit - but NOT if it's "stop tracking" etc
    if "tracking" not in cmd_lower:
        if cmd_lower in ["stop", "exit", "quit", "goodbye", "bye"]:
            core.speak("Goodbye.")
            return False  # Signal to exit
        # Also match "jarvis stop" etc
        if any(cmd_lower.endswith(x) for x in [" stop", " exit", " quit"]):
            core.speak("Goodbye.")
            return False

    # Help
    if "help" in cmd_lower or "what can you do" in cmd_lower:
        show_help(core)
        return True

    return None  # Not handled


def show_help(core):
    print("\n=== Available Commands ===")
    for plugin in core.plugins:
        if hasattr(plugin, "COMMANDS"):
            print(f"\n{plugin.NAME}:")
            for cmd in plugin.COMMANDS:
                print(f"  • {cmd}")
    print()
    core.speak("Check the terminal for available commands.")
