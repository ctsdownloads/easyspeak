"""A noise-suppressed copy of the microphone, made for EasySpeak alone.

A fan or an air filter can sit above the silence threshold, so silence is never
detected and every recording runs to its time cap. PipeWire's echo-cancel module
with WebRTC noise suppression removes that steady noise. `pw-cli` hosts the
filter for as long as it runs, so it exists only while EasySpeak has the
microphone open, and every other application keeps the plain one.
"""

import contextlib
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

NODE = "easyspeak_mic"

_MODULE_ARGS = (
    "{ library.name = aec/libspa-aec-webrtc monitor.mode = true"
    " aec.args = { webrtc.noise_suppression = true webrtc.gain_control = false"
    " webrtc.extended_filter = false webrtc.high_pass_filter = true }"
    f' capture.props = {{ node.name = "capture.{NODE}" }}'
    f' source.props = {{ node.name = "{NODE}"'
    ' node.description = "EasySpeak microphone" } }'
)

STARTUP_TIMEOUT = 3.0  # seconds
POLL_INTERVAL = 0.1  # seconds


def _node_exists():
    """Whether PipeWire lists the filter's source yet."""
    try:
        listing = subprocess.run(
            ["pw-cli", "ls", "Node"], capture_output=True, text=True, check=False
        )
    except OSError:
        return False
    return f'node.name = "{NODE}"' in listing.stdout


class NoiseFilter:
    """The filter's `pw-cli` process, started and stopped with the microphone."""

    def __init__(self):
        """Start with no filter running."""
        self._process = None

    def start(self):
        """Start the filter; False, leaving the plain microphone, if it won't run."""
        try:
            self._process = subprocess.Popen(
                [
                    "pw-cli",
                    "-m",
                    "load-module",
                    "libpipewire-module-echo-cancel",
                    _MODULE_ARGS,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.warning("Noise filter unavailable (%s); using the plain mic", exc)
            return False

        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline and self._process.poll() is None:
            if _node_exists():
                logger.info("Listening through the noise filter")
                return True
            time.sleep(POLL_INTERVAL)

        self.stop()
        logger.warning("Noise filter did not start; using the plain mic")
        return False

    def stop(self):
        """Stop the filter, which removes it from PipeWire."""
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None

    @contextlib.contextmanager
    def selected(self):
        """Point a microphone opened inside this block at the filter.

        PipeWire's ALSA plugin reads `PIPEWIRE_NODE` when a stream opens. Left set,
        it would follow every app EasySpeak launches, so it is set for the open only.
        """
        if self._process is None:
            yield
            return
        previous = os.environ.get("PIPEWIRE_NODE")
        os.environ["PIPEWIRE_NODE"] = NODE
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("PIPEWIRE_NODE", None)
            else:
                os.environ["PIPEWIRE_NODE"] = previous
