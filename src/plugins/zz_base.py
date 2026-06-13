"""
Base Plugin - Help and Exit
"""

NAME = "base"
DESCRIPTION = "Help and exit commands"

COMMANDS = [
    "help - list all commands",
    "quit/exit/goodbye - exit EasySpeak",
]

core = None


def setup(c):
    global core
    core = c


def handle(cmd, core):
    cmd_lower = cmd.lower().strip()

    # Exit - but NOT if it's "quit tracking" etc
    if "tracking" not in cmd_lower:
        if cmd_lower in ["exit", "quit", "goodbye", "bye"]:
            core.speak("Goodbye.")
            return False  # Signal to exit
        # Also match "jarvis quit" etc
        if any(cmd_lower.endswith(x) for x in [" exit", " quit"]):
            core.speak("Goodbye.")
            return False

    # Help
    if "help" in cmd_lower or "what can you do" in cmd_lower:
        show_help(core)
        return True

    return None  # Not handled


def show_help(core):
    """List every plugin's commands on the terminal.

    Printed rather than logged: it is the direct reply to an explicit "help"
    request (the spoken reply tells the user to read the terminal), so it must
    appear regardless of the configured log verbosity.
    """
    print("\n=== Available Commands ===")  # noqa: T201
    for plugin in core.plugins:
        if hasattr(plugin, "COMMANDS"):
            print(f"\n{plugin.NAME}:")  # noqa: T201
            for cmd in plugin.COMMANDS:
                print(f"  • {cmd}")  # noqa: T201
    print()  # noqa: T201
    core.speak("Check the terminal for available commands.")
