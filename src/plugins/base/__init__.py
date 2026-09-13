"""Base Plugin - Help and Exit."""

from easyspeak.core.i18n import translator
from easyspeak.core.vocabulary import Vocabulary

_ = translator(__file__)
vocab = Vocabulary(__file__)

NAME = "base"
PRIORITY = 100  # the catch-all for help and exit routes last
DESCRIPTION = "Help and exit commands"

COMMANDS = [
    _("help - list all commands"),
    _("require wake word - modes wait for the wake word each command"),
    _("free listening - modes accept bare commands again"),
    _("quit/exit/goodbye - exit EasySpeak"),
]

core = None


def setup(c):
    """Store the core reference for use by the plugin's handlers."""
    global core
    core = c


def handle(cmd, core):
    """Handle the help and exit commands; return None to pass others through.

    Returns False to signal the daemon to exit, True if help was shown, or None when the
    command is for another plugin.
    """
    cmd_lower = cmd.lower().strip()

    if vocab.says(cmd_lower, "require_wake_word"):
        core.require_wake_word = True
        core.speak(_("Modes now wait for the wake word."))
        return True

    if vocab.says(cmd_lower, "free_listening"):
        core.require_wake_word = False
        core.speak(_("Modes now take commands on their own."))
        return True

    # The exit word must end the command ("jarvis quit"), so "quit tracking"
    # is left to head tracking.
    if vocab.ends(cmd_lower, "exit"):
        core.speak(_("Goodbye."))
        return False  # Signal to exit

    if vocab.says(cmd_lower, "help"):
        show_help(core)
        return True

    return None  # Not handled


def show_help(core):
    """List every plugin's commands on the terminal.

    Printed rather than logged: it is the direct reply to an explicit "help"
    request (the spoken reply tells the user to read the terminal), so it must
    appear regardless of the configured log verbosity.
    """
    print("\n=== " + _("Available Commands") + " ===")  # noqa: T201
    for plugin in core.plugins:
        if hasattr(plugin, "COMMANDS"):
            print(f"\n{plugin.NAME}:")  # noqa: T201
            for cmd in plugin.COMMANDS:
                print(f"  • {cmd}")  # noqa: T201
    print()  # noqa: T201
    core.speak(_("Check the terminal for available commands."))
