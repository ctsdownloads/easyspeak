# Core API

The `core` package holds the voice-control engine: wake-word detection,
transcription, command routing, speech output, the panel indicator, and the
GNOME Shell extension lifecycle. Plugins receive an [`EasySpeak`][core.main.EasySpeak]
instance and use its small public API (`speak`, `host_run`, `transcribe`,
`wait_for_speech`, `record_until_silence`, `deactivate`, ...) to act on commands.

## core.main

::: core.main

## core.cli

::: core.cli

## core.config

::: core.config

## core.log

::: core.log

## core.speech

::: core.speech

## core.tray

::: core.tray

## core.mediakeys

::: core.mediakeys

## core.gnome_extension

::: core.gnome_extension
