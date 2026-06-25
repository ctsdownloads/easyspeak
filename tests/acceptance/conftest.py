"""Setup for the voice-feedback acceptance scenarios (pytest-bdd).

Spoken feedback can't be checked by listening in an automated run, so
these scenarios drive the real EasySpeak object with the subprocess boundary
stubbed. They assert the *observable contract* of speak()/drain — model
loaded once, blank ignored, flushed on shutdown, recovery after a break —
rather than audio leaving a speaker.

**Note:** See integration tests for test-driving external binaries for real.
"""

import sys
from unittest.mock import MagicMock

# easyspeak.core imports pyaudio/pyopen_wakeword/faster_whisper at load time; stub
# them so importing EasySpeak doesn't require the ML/audio stack.
sys.modules["pyaudio"] = MagicMock()
sys.modules["pyopen_wakeword"] = MagicMock()
sys.modules["faster_whisper"] = MagicMock()
