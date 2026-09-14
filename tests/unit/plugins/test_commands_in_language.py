"""The simple plugins take their commands in the active language, English too."""

import importlib
from unittest.mock import Mock, patch

import pytest
from easyspeak.core.vocabulary import Vocabulary
from easyspeak.plugins import apps, base, files, media, sleep, system


@pytest.fixture
def german(monkeypatch):
    """Give every plugin under test its German vocabulary, English still accepted."""
    for plugin in (apps, base, files, media, sleep, system):
        monkeypatch.setattr(plugin, "vocab", Vocabulary(plugin.__file__, language="de"))


@pytest.mark.usefixtures("german")
@pytest.mark.parametrize("command", ["hilfe", "was kannst du", "help"])
@patch.object(base, "show_help")
def test_base_help(mock_show_help, command, mock_core):
    """ "Hilfe" shows the help, and so does "help"."""
    assert base.handle(command, mock_core) is True
    mock_show_help.assert_called_once()


@pytest.mark.usefixtures("german")
@pytest.mark.parametrize("command", ["beenden", "jarvis beenden", "quit"])
def test_base_exit(command, mock_core):
    """ "Beenden" at the end of a command exits; "quit tracking" would not."""
    assert base.handle(command, mock_core) is False


@pytest.mark.usefixtures("german")
def test_base_exit_word_inside_a_command_is_not_an_exit(mock_core):
    """ "beenden" followed by more words belongs to whatever those words mean."""
    assert base.handle("beenden verfolgung", mock_core) is None


@pytest.mark.usefixtures("german")
@patch.object(apps, "launch_app", return_value=True)
def test_apps_open_in_german(mock_launch, mock_core):
    """ "Öffne den Taschenrechner" launches the calculator, by its English key."""
    assert apps.handle("öffne den taschenrechner", mock_core) is True
    mock_launch.assert_called_once_with("calculator", mock_core)


@pytest.mark.usefixtures("german")
@patch.object(apps, "close_app")
def test_apps_close_in_german(mock_close, mock_core):
    """ "Schließe die Einstellungen" closes settings."""
    assert apps.handle("schließe die einstellungen", mock_core) is True
    mock_close.assert_called_once_with("settings", mock_core)


@pytest.mark.usefixtures("german")
@patch.object(apps, "launch_app", return_value=True)
def test_apps_english_still_works_with_german_active(mock_launch, mock_core):
    """An app with no German name is still opened by its English one."""
    assert apps.handle("öffne gimp", mock_core) is True
    mock_launch.assert_called_once_with("gimp", mock_core)


@pytest.mark.usefixtures("german")
@patch.object(files, "open_folder", return_value=True)
def test_files_folder_in_german(mock_open, mock_core):
    """ "Zeige die Bilder" opens the pictures folder."""
    assert files.handle("zeige die bilder", mock_core) is True
    mock_open.assert_called_once_with("~/Pictures", mock_core)


@pytest.mark.usefixtures("german")
@patch.object(files, "open_folder", return_value=True)
def test_files_manager_in_german(mock_open, mock_core):
    """ "Öffne den Dateimanager" opens the home folder in it."""
    assert files.handle("öffne den dateimanager", mock_core) is True
    mock_open.assert_called_once_with("~", mock_core)


@pytest.mark.usefixtures("german")
@pytest.mark.parametrize(
    ("command", "action"),
    [
        ("pause", "pause"),
        ("musik abspielen", "play"),
        ("nächster titel", "next"),
        ("stopp die musik", "pause"),
        ("next", "next"),
    ],
)
def test_media_actions_in_german(command, action):
    """German playback verbs map to the same MPRIS actions."""
    assert media._action_for(command) == action


@pytest.fixture
def italian(monkeypatch):
    """Give the media plugin its Italian vocabulary."""
    monkeypatch.setattr(media, "vocab", Vocabulary(media.__file__, language="it"))


@pytest.fixture
def french(monkeypatch):
    """Give the media plugin its French vocabulary."""
    monkeypatch.setattr(media, "vocab", Vocabulary(media.__file__, language="fr"))


@pytest.mark.usefixtures("french")
@pytest.mark.parametrize(
    ("command", "action"),
    [("lance la lecture", "play"), ("arrête la lecture", "pause"), ("lis", "play")],
)
def test_media_lecture_is_the_noun_in_french(command, action):
    """ "lecture" names the playback, so it can neither hide nor be the verb."""
    assert media._action_for(command) == action


@pytest.mark.usefixtures("italian")
def test_media_strips_filler_phrases():
    """ "per favore" is filler even though it is two words."""
    assert media._action_for("riproduci la musica per favore") == "play"


@pytest.mark.usefixtures("german")
@patch.object(apps, "launch_app", return_value=True)
def test_apps_terminal_opens_once_registered(mock_launch, mock_core, monkeypatch):
    """ "Öffne die Konsole" opens the terminal setup found; none found, no match."""
    assert apps.handle("öffne die konsole", mock_core) is None
    monkeypatch.setitem(apps.LOCAL_APPS, "terminal", "kgx")
    assert apps.handle("öffne die konsole", mock_core) is True
    mock_launch.assert_called_once_with("terminal", mock_core)


@pytest.mark.usefixtures("german")
def test_media_stop_alone_is_not_ours():
    """A bare "stopp" needs a media noun, like the English "stop"."""
    assert media._action_for("stopp") is None


@pytest.mark.usefixtures("german")
@pytest.mark.parametrize(
    "command", ["geh schlafen", "hör auf zuzuhören", "stop listening"]
)
def test_sleep_in_german(command, mock_core):
    """The German sleep phrases deactivate, and the English one still does."""
    assert sleep.handle(command, mock_core) is True
    mock_core.deactivate.assert_called_once()


@pytest.mark.parametrize(
    ("language", "command"),
    [
        ("de", "hör auf zuzuhören"),
        ("it", "smetti di ascoltare"),
        ("fr", "arrête d'écouter"),
        ("es", "deja de escuchar"),
    ],
)
def test_stop_listening_in_every_language(language, command, mock_core, monkeypatch):
    """ "Stop listening" in each shipped language confirms out loud and deactivates."""
    monkeypatch.setattr(sleep, "vocab", Vocabulary(sleep.__file__, language=language))

    assert sleep.handle(command, mock_core) is True
    mock_core.speak.assert_called_once()
    mock_core.deactivate.assert_called_once()


@pytest.mark.usefixtures("german")
@pytest.mark.parametrize(
    ("command", "action"),
    [
        ("lauter", "volume_up"),
        ("lautstärke runter", "volume_down"),
        ("sehr leise", "volume_min"),
        ("stumm", "volume_mute"),
        ("bildschirm heller", "brightness_up"),
        ("nicht stören an", "dnd_on"),
        ("benachrichtigungen an", "dnd_off"),
        ("volume up", "volume_up"),
    ],
)
def test_system_in_german(command, action, mock_core, monkeypatch):
    """German volume, brightness and do-not-disturb words reach their actions."""
    called = Mock()
    for name in (
        "volume_up",
        "volume_down",
        "volume_max",
        "volume_min",
        "volume_mute",
        "brightness_up",
        "brightness_down",
        "dnd_on",
        "dnd_off",
    ):
        monkeypatch.setattr(system, name, getattr(called, name))

    assert system.handle(command, mock_core) is True
    assert [c[0] for c in called.method_calls] == [action]


def test_apps_named_without_a_verb_is_not_ours(mock_core):
    """An app name alone, no open or close, is left for another plugin."""
    assert apps.handle("gimp", mock_core) is None
    mock_core.speak.assert_not_called()


@pytest.fixture
def apps_in_german(monkeypatch):
    """The apps plugin as imported with German active; English again after."""
    from easyspeak.core import config

    monkeypatch.setattr(config, "LANGUAGE", "de")
    importlib.reload(apps)
    yield apps
    monkeypatch.setattr(config, "LANGUAGE", "en")
    importlib.reload(apps)


def test_help_lines_follow_the_active_language(apps_in_german):
    """The real command list names the German words, with the app names too."""
    assert apps_in_german.COMMANDS[0] == "öffne/öffnen [app] - open an application"
    assert apps_in_german.COMMANDS[2].endswith("rechner, einstellungen, terminal")


def test_help_lines_are_english_by_default():
    """With English active the list reads as it always did."""
    assert apps.COMMANDS[0] == "open/launch [app] - open an application"
    assert (
        files.COMMANDS[1] == "open files/file manager - open your default file manager"
    )
    assert sleep.COMMANDS[0].startswith("go to sleep/stop listening - ")


@pytest.mark.usefixtures("german")
@pytest.mark.parametrize("command", ["öffne den datei manager", "öffne dateimanager"])
@patch.object(files, "open_folder", return_value=True)
def test_files_hears_the_file_manager_as_whisper_writes_it(
    mock_open, command, mock_core
):
    """Whisper writes "Dateimanager" as "datei manager" as often as not."""
    assert files.handle(command, mock_core) is True
    mock_open.assert_called_once()


@pytest.fixture
def desktop_with(tmp_path, monkeypatch, mock_core):
    """Configure a default file manager: return a function taking its Exec line."""

    def configure(exec_line):
        apps_dir = tmp_path / "applications"
        apps_dir.mkdir(exist_ok=True)
        (apps_dir / "manager.desktop").write_text(
            f"[Desktop Entry]\nExec={exec_line}\n"
        )
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        def host_run(cmd, **_kwargs):
            if cmd[:2] == ["xdg-mime", "query"]:
                return Mock(returncode=0, stdout="manager.desktop\n")
            return Mock(returncode=0, stdout="")

        mock_core.host_run.side_effect = host_run
        return mock_core

    return configure


@pytest.mark.usefixtures("german")
def test_files_closes_the_configured_file_manager(desktop_with):
    """ "schließe den Datei Manager" closes whatever xdg-open would open, not Nautilus."""
    core = desktop_with("/usr/bin/nemo %U")

    assert files.handle("schließe den datei manager", core) is True

    assert ["pkill", "-f", "nemo"] in [c.args[0] for c in core.host_run.call_args_list]
    core.speak.assert_called_once_with("Closing the file manager.")


def test_files_closes_a_flatpak_file_manager_by_its_app_id(desktop_with):
    """A Flatpak's Exec runs flatpak; the app id is what the process list shows."""
    core = desktop_with(
        "/usr/bin/flatpak run --branch=stable --command=nautilus org.gnome.Nautilus %U"
    )

    assert files.handle("close file manager", core) is True

    assert ["pkill", "-f", "org.gnome.Nautilus"] in [
        c.args[0] for c in core.host_run.call_args_list
    ]


def test_files_close_says_when_no_manager_is_configured(mock_core):
    """Nothing configured: the user is told, nothing is killed."""
    mock_core.host_run.return_value = Mock(returncode=1, stdout="")

    assert files.handle("close file manager", mock_core) is True

    mock_core.speak.assert_called_once_with("No file manager found.")
    assert all(c.args[0][0] != "pkill" for c in mock_core.host_run.call_args_list)


@pytest.mark.usefixtures("german")
@patch.object(files, "open_folder", return_value=True)
def test_files_opens_the_pictures_as_photos(mock_open, mock_core):
    """ "Fotos" and "photos" name the Pictures folder as well."""
    assert files.handle("zeige die fotos", mock_core) is True
    assert files.handle("open photos", mock_core) is True
    assert [c.args[0] for c in mock_open.call_args_list] == ["~/Pictures", "~/Pictures"]
