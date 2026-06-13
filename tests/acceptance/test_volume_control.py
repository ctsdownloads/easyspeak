"""Step definitions binding volume_control.feature to the system plugin.

These drive the real EasySpeak.route_command with the system plugin loaded and
the host boundary (tap_key / host_run) stubbed, then count how the volume was
driven — repeated nudges fire every time, and the extremes set it directly.
"""

from unittest.mock import Mock

import pytest
from easyspeak.core.main import EasySpeak
from easyspeak.plugins import system
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/volume_control.feature")


@pytest.fixture
def ctx():
    return {}


@given("a fresh EasySpeak with the system plugin")
def fresh_easyspeak(ctx):
    easy = EasySpeak()
    easy.tap_key = Mock(return_value=True)
    easy.host_run = Mock(return_value=Mock(returncode=0))
    easy.plugins = [system]
    system.setup(easy)
    ctx["easy"] = easy


@when(parsers.parse('I say "{phrase}"'))
def say_phrase(ctx, phrase):
    ctx["easy"].route_command(phrase)


def _key_presses(ctx, keycode):
    return [c for c in ctx["easy"].tap_key.call_args_list if c.args[0] == keycode]


@then(parsers.parse("the volume was raised {count:d} times"))
def volume_raised(ctx, count):
    assert len(_key_presses(ctx, system.KEY_VOLUME_UP)) == count


@then(parsers.parse("the volume was lowered {count:d} times"))
def volume_lowered(ctx, count):
    assert len(_key_presses(ctx, system.KEY_VOLUME_DOWN)) == count


@then("the volume is set to maximum")
def volume_maxed(ctx):
    ctx["easy"].host_run.assert_any_call(
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "85%"]
    )


@then("the volume is set to minimum")
def volume_minned(ctx):
    ctx["easy"].host_run.assert_any_call(
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "15%"]
    )
