# Plugins API

Every plugin is a Python package (or a plain module) that follows a small
contract rather than subclassing a base class. It is loaded if it exposes a
`NAME` string and a `handle(cmd, core)` function; the optional `setup(core)` hook
runs once at startup, `COMMANDS`/`DESCRIPTION` feed the help screen, and
`PRIORITY` (default 50, lower first) sets its place in the routing order. A
package's `locale/<language>/` holds what it says, a gettext catalog, and what it
listens for, a `vocabulary.toml` table; a plugin that has them binds `_`, its
translator, and `vocab`, its vocabulary, at import (see
[Writing Plugins](../plugins.md#translations)), and a plain module has neither.
Click the diagram to enlarge it.

```mermaid
classDiagram
    class PluginContract {
        <<protocol>>
        +str NAME
        +str DESCRIPTION
        +int PRIORITY
        +list COMMANDS
        +translator _
        +Vocabulary vocab
        +setup(core)
        +handle(cmd, core)
    }
    class base {
        PRIORITY = 100
    }
    class mousegrid {
        PRIORITY = 1
    }
    class headtrack {
        PRIORITY = 0
    }
    class sleep
    class system
    class media
    class files
    class apps
    class browser
    class dictation

    PluginContract <|.. headtrack
    PluginContract <|.. mousegrid
    PluginContract <|.. apps
    PluginContract <|.. browser
    PluginContract <|.. dictation
    PluginContract <|.. files
    PluginContract <|.. media
    PluginContract <|.. sleep
    PluginContract <|.. system
    PluginContract <|.. base

    class Locale["locale/‹language›/"] {
        <<directory>>
        LC_MESSAGES/‹name›.po
        vocabulary.toml
    }
    Locale "1..*" --* "1" PluginContract
    style Locale fill:#80808026
    style headtrack stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style mousegrid stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style apps stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style browser stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style dictation stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style files stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style media stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style sleep stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style system stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
    style base stroke:var(--md-mermaid-node-fg-color),stroke-dasharray:5
```

`handle` returns `True` when it consumed the command, `False` to signal the
daemon to exit, or `None` to pass the command to the next plugin, in order of
`PRIORITY`: the modes first, the base plugin last as the catch-all for help and
exit.

## base

::: plugins.base

## sleep

::: plugins.sleep

## system

::: plugins.system

## media

::: plugins.media

## files

::: plugins.files

## apps

::: plugins.apps

## browser

::: plugins.browser

## dictation

::: plugins.dictation

## mousegrid

::: plugins.mousegrid

## headtrack

::: plugins.headtrack
