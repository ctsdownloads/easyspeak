"""
Apps Plugin - Launch and close applications
"""

NAME = "apps"
DESCRIPTION = "Launch and close applications"

COMMANDS = [
    "open/launch [app] - open an application",
    "close [app] - close an application",
    "Apps: browser, steam, spotify, files, calculator, settings, terminal",
]

# Flatpak apps
FLATPAK_APPS = {
    "firefox": "org.mozilla.firefox",
    "steam": "com.valvesoftware.Steam",
    "spotify": "com.spotify.Client",
    "calculator": "org.gnome.Calculator",
    "settings": "org.gnome.Settings",
}

# Local binary apps
LOCAL_APPS = {
    "files": "nautilus",
    "terminal": "gnome-terminal",
    "browser": "qutebrowser",
}

core = None


def setup(c):
    global core
    core = c


def find_app(name, core):
    """Find app - returns (type, id)"""
    if name in FLATPAK_APPS:
        result = core.host_run(["flatpak", "info", FLATPAK_APPS[name]])
        if result.returncode == 0:
            return ("flatpak", FLATPAK_APPS[name])

    if name in LOCAL_APPS:
        return ("local", LOCAL_APPS[name])

    result = core.host_run(["which", name])
    if result.returncode == 0:
        return ("local", name)

    return (None, None)


def launch_app(name, core):
    app_type, app_id = find_app(name, core)
    if app_type == "flatpak":
        core.host_run(["flatpak", "run", app_id], background=True)
        return True
    elif app_type == "local":
        core.host_run([app_id], background=True)
        return True
    return False


def close_app(name, core):
    app_type, app_id = find_app(name, core)
    if app_type == "flatpak":
        core.host_run(["flatpak", "kill", app_id])
        return True
    elif app_type == "local":
        core.host_run(["pkill", "-f", app_id])
        return True
    return False


def handle(cmd, core):
    all_apps = list(FLATPAK_APPS.keys()) + list(LOCAL_APPS.keys())

    for app in all_apps:
        if ("open" in cmd or "launch" in cmd) and app in cmd:
            if launch_app(app, core):
                core.speak(f"Opening {app}.")
            else:
                core.speak(f"{app} not installed.")
            return True

        if "close" in cmd and app in cmd:
            close_app(app, core)
            core.speak(f"Closing {app}.")
            return True

    return None  # Not handled
