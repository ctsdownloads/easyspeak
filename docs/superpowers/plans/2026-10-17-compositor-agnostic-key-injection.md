# Compositor-Agnostic Key Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all of EasySpeak's keystroke injection (dictation paste chord + keystroke commands, browser-mode press-key, media-key replay) through one capability-gated backend — Mutter RemoteDesktop on GNOME (unchanged behavior), ydotool/uinput elsewhere — per the approved spec `docs/superpowers/specs/2026-10-17-compositor-agnostic-typing-for-easyspeak-design.md`.

**Architecture:** `core/ydotool.py` holds the extracted run seam (dialects, sockets, bounded runs, probes — moved verbatim from `src/plugins/mousegrid/_ydotool.py`, which re-imports them) plus new key-verb synthesis. `core/mediakeys.py` becomes the gated injector: sticky three-arm backend selection, raise-only `tap_key`/`tap_chord`, total outcome→exception mapping. Consumers keep their call sites.

**Tech Stack:** Python 3.10–3.14, jeepney (D-Bus), pytest + pytest-bdd; `just` recipes as the only gate entry points; the `easyspeak-cosmic` libvirt VM (runbook in OB thought `4d2c2ce1`) for acceptance.

**Branch/stack:** work `~/src/easyspeak.WT.compositor-agnostic-typing-for-easyspeak`, branch `compositor-agnostic-typing-for-easyspeak`, stacked on PR #233's head (`origin/69-prototype-…`). Rebase onto it before starting if it moved (Task 0).

---

### Task 0: Rebase onto PR #233's current head and capture the dialect fixtures

**Goal:** The branch sits on #233's latest head, and the per-dialect `key` argv grammars are captured from the clients themselves (spec §10.2) before any synthesis is written.

**Files:**
- Create: `tests/unit/core/fixtures/ydotool_key_usage_legacy.txt`
- Create: `tests/unit/core/fixtures/ydotool_key_usage_modern.txt`

**Acceptance Criteria:**
- [ ] `hug ll -1` shows the branch's tip directly on `origin/69-prototype-compositor-agnostic-easyspeak-backend-layer-shell-overlay-ydotool` (currently `eb2a003`)
- [ ] Both fixture files exist and contain a `key` verb usage/section captured from a real client's `--help` output
- [ ] The legacy fixture comes from the `easyspeak-cosmic` VM (Pop 24.04, ydotool 0.1.8); the modern fixture from a 1.0.x client (Ubuntu 26.04 VM) or, failing that, from the ydotool 1.0.x source tree with the source URL recorded in the file header

**Verify:** `hug -C ~/src/easyspeak.WT.compositor-agnostic-typing-for-easyspeak ll -3` shows only our docs commits on top of `eb2a003`; `head -3 tests/unit/core/fixtures/ydotool_key_usage_*.txt` names the client version each was captured from.

**Steps:**

- [ ] **Step 1: Rebase.** `hug -C ~/src/easyspeak.WT.compositor-agnostic-typing-for-easyspeak fetch`, then `hug -C … rb origin/69-prototype-compositor-agnostic-easyspeak-backend-layer-shell-overlay-ydotool -y`. If #233 gained code commits since `eb2a003`, re-read `_ydotool.py` and reconcile line references in Tasks 1–3 before proceeding (the spec's §10 reconciliation checklist).
- [ ] **Step 2: Capture legacy grammar (VM).** From the host:
  ```sh
  ssh -i ~/.ssh/id_ed25519 pop-os@$(virsh --connect qemu:///system domifaddr easyspeak-cosmic | awk '/ipv4/{print $4; exit}' | cut -d/ -f1) 'ydotool key --help 2>&1; ydotool --help 2>&1 | grep -A1 key'
  ```
  Save the output (plus a header naming `ydotool --version` from the same session) to `tests/unit/core/fixtures/ydotool_key_usage_legacy.txt`.
- [ ] **Step 3: Capture modern grammar.** From the Ubuntu 26.04 VM (same pattern), or from https://github.com/AdrianEddy/ydotool/tree/master (1.0.x `ydotool.c` key verb section) with the commit URL in the header. Save to `tests/unit/core/fixtures/ydotool_key_usage_modern.txt`.
- [ ] **Step 4: Commit.**
  ```sh
  hug a tests/unit/core/fixtures && hug c -m "test: capture per-dialect ydotool key usage as argv fixtures"
  ```

---

### Task 1: Extract the plumbing into `core/ydotool.py` (verbatim move + parameterized dry-run)

**Goal:** The run seam and its support plumbing live in core; the grid imports them back, its namespace and its 3,273-line test file unchanged; the `EASYSPEAK_GRID_DRY_RUN` bypass is no longer read by core code (spec §4.3, §10.1).

**Files:**
- Create: `src/core/ydotool.py`
- Modify: `src/plugins/mousegrid/_ydotool.py` (delete moved definitions, add re-imports, pass `dry_run=` at call sites)
- Test: `tests/unit/core/test_ydotool_plumbing.py` (new, small)

**Moved verbatim** (from `_ydotool.py`, current layout): constants `PROBE_TIMEOUT`, `INJECT_TIMEOUT`, `REAP_GRACE`, `PRESENT_TIMEOUT`, `PROBE_TIMEOUT_PER_USE`, `YDTOOL_SOCKET`, `YDTOOL_SOCKET_NAME`, `YDTOOL_SOCKET_TYPES`, `ERROR_SIGNATURES`, `FALLBACK_NOTICE`, `YDTOOL_DIALECT_*`, `YDTOOL_ABSOLUTE_FLAG`, `YDTOOL_NOOP_LEGACY`, `YDTOOL_NOOP_MODERN` (`:64-126`); functions `_probe_dialect`, `dialect`, `ydotool_socket_candidates`, `_socket_owned`, `_socket_env_key`, `injector_socket`, `_client_env`, `_spawn`, `_run_bounded`, `run_ydotool` (`:136-404`), `_socket_accepts`, `parse_tool_list`, `_probe_tools` (`:609-685`). NOT moved: `YDTOOL_VERBS`, `BUTTONS`/`MODERN_BUTTONS`, `legacy_delay_args`, pointer verbs, helper plumbing, gate policy, conversation — those are grid-owned.

**Acceptance Criteria:**
- [ ] `core/ydotool.py` contains no `os.environ.get("EASYSPEAK_GRID_` read; `_run_bounded` takes `dry_run=None` as a parameter
- [ ] `_ydotool.py` exposes the moved names via `from easyspeak.core.ydotool import …` re-exports and passes `dry_run=bool(os.environ.get("EASYSPEAK_GRID_DRY_RUN"))` where it called `_run_bounded`
- [ ] `just pytest tests/unit/plugins/test_mousegrid_ydotool.py -q` passes unchanged
- [ ] New plumbing test passes

**Verify:** `just pytest tests/unit/core/test_ydotool_plumbing.py tests/unit/plugins/test_mousegrid_ydotool.py -q` → all pass.

**Steps:**

- [ ] **Step 1: Create `src/core/ydotool.py`.** Module docstring: "The ydotool run seam: dialects, sockets, bounded runs, and capability probes. Compositor-agnostic — knows the client, not any caller. Extracted verbatim from the mouse grid's backend; dry-run is a parameter, never an env read (key injection must not inherit a grid-debug silent-ran switch)." Then the moved code. The single edit to moved code is `_run_bounded`'s opening:
  ```python
  def _run_bounded(args, timeout=INJECT_TIMEOUT, dry_run=None):
      """Run one ydotool invocation under `timeout`; return ran/errored/unknown.

      `dry_run` short-circuits to "ran" without spawning the client. It is a
      parameter, deliberately not an env read: the grid passes its own debug
      flag here, and no other consumer can inherit a silent no-op by accident.
      """
      if dry_run:
          logger.info("dry run: %s", " ".join(args))
          return "ran"
      try:
          result = _spawn(args, timeout)
      except subprocess.TimeoutExpired:
          logger.warning("ydotool timed out after %ss: %s", timeout, " ".join(args))
          return "unknown"
      # … remainder verbatim from _ydotool.py:360-395
  ```
- [ ] **Step 2: Rewire `_ydotool.py`.** Delete the moved definitions; at the top add:
  ```python
  from easyspeak.core.ydotool import (  # noqa: F401 — re-exported for the grid
      ERROR_SIGNATURES,
      INJECT_TIMEOUT,
      PROBE_TIMEOUT,
      REAP_GRACE,
      YDTOOL_ABSOLUTE_FLAG,
      YDTOOL_DIALECT_LEGACY,
      YDTOOL_DIALECT_MODERN,
      YDTOOL_NOOP_LEGACY,
      YDTOOL_NOOP_MODERN,
      YDTOOL_SOCKET,
      YDTOOL_SOCKET_NAME,
      _client_env,
      _probe_dialect,
      _probe_tools,
      _run_bounded,
      _socket_accepts,
      _socket_env_key,
      _socket_owned,
      _spawn,
      dialect,
      injector_socket,
      noop_argv,
      parse_tool_list,
      run_ydotool,
      ydotool_socket_candidates,
  )
  ```
  At each former `_run_bounded(args…)` call site in the grid (the injector probe and the verb runners), pass `dry_run=bool(os.environ.get("EASYSPEAK_GRID_DRY_RUN"))` — keep exactly one definition of that env read, grid-side.
- [ ] **Step 3: Write the plumbing test** `tests/unit/core/test_ydotool_plumbing.py`:
  ```python
  """The core run seam reads no grid env of its own."""
  import easyspeak.core.ydotool as yd


  def test_core_reads_no_grid_env(monkeypatch):
      monkeypatch.setenv("EASYSPEAK_GRID_DRY_RUN", "1")
      assert yd._run_bounded(("ydotool", "type", "x"), dry_run=None) != "ran" or True
      # the real assertion: dry_run=None never short-circuits, so the call
      # reaches _spawn — proven by the outcome NOT being the dry-run "ran"
      # with a guaranteed-refusing argv:
      assert yd._run_bounded(("nonexistent-ydotool-binary",), dry_run=None) in {
          "errored",
          "unknown",
      }


  def test_dry_run_is_a_parameter():
      assert yd._run_bounded(("anything",), dry_run=True) == "ran"
  ```
- [ ] **Step 4: Run** `just pytest tests/unit/core/test_ydotool_plumbing.py -q` → pass; then `just pytest tests/unit/plugins/test_mousegrid_ydotool.py -q` → pass.
- [ ] **Step 5: Commit.** `hug a src/core/ydotool.py src/plugins/mousegrid/_ydotool.py tests/unit/core/test_ydotool_plumbing.py && hug c -m "refactor(core): extract the ydotool run seam from the mouse grid

  Verbatim move of dialects, sockets, bounded runs and probes into
  core/ydotool.py; the grid re-imports them so its tests stay put. One
  edit to moved code: dry-run becomes a parameter, not an env read —
  key injection must not inherit a grid-debug silent-ran switch."`

---

### Task 2: Key-verb synthesis in `core/ydotool.py` (batched, dialect-pinned, scaled timeout)

**Goal:** `key_argv(chord, repeats=1)` and `key_timeout(repeats)` exist, with argv grammar asserted against the Task 0 fixtures (never against the synthesizer).

**Files:**
- Modify: `src/core/ydotool.py` (append)
- Test: `tests/unit/core/test_ydotool_key.py` (new)

**Acceptance Criteria:**
- [ ] `key_argv((29, 47))` returns the legacy-dialect argv for ctrl+v exactly as the legacy fixture's `key` section prescribes, and `key_argv((29, 47))` under a `modern` dialect override returns the modern argv — asserted from fixture content, per dialect
- [ ] `key_argv((14,), repeats=10)` emits one argv containing ten press/release pairs
- [ ] `key_timeout(1) >= INJECT_TIMEOUT` and `key_timeout(200) > key_timeout(10)`

**Verify:** `just pytest tests/unit/core/test_ydotool_key.py -q` → pass.

**Steps:**

- [ ] **Step 1: Write failing tests** (fixture = oracle):
  ```python
  """Key-verb synthesis: the argv oracle is the client's own usage line."""
  from pathlib import Path

  import pytest

  from easyspeak.core import ydotool

  FIXTURES = Path(__file__).parent / "fixtures"


  def grammar_tokens(dialect):
      """The `key` section tokens extracted from a captured usage fixture."""
      text = (FIXTURES / f"ydotool_key_usage_{dialect}.txt").read_text()
      # The fixtures carry the client's usage line; this helper parses the
      # documented key-argument shape out of it (e.g. "<CODE>:<PRESSED>").
      # Kept tiny and mirror-checked against the fixture by eye at review.
      return yd.key_usage_grammar(text)


  def test_chord_order_down_then_up_reverse():
      argv = yd.key_argv((29, 47))
      codes = [tok for tok in argv if ":" in str(tok)]
      assert codes == ["29:1", "47:1", "47:0", "29:0"]


  def test_repeats_batch_into_one_argv():
      argv = yd.key_argv((14,), repeats=10)
      pairs = [tok for tok in argv if ":" in str(tok)]
      assert pairs == ["14:1", "14:0"] * 10


  def test_key_timeout_scales_with_repeats():
      assert yd.key_timeout(1) >= yd.INJECT_TIMEOUT
      assert yd.key_timeout(200) > yd.key_timeout(10)


  @pytest.mark.parametrize("dialect", ["legacy", "modern"])
  def test_argv_matches_captured_fixture(dialect, monkeypatch):
      monkeypatch.setattr(yd, "dialect", lambda: dialect)
      argv = yd.key_argv((29, 47))
      assert all(str(tok) in grammar_tokens(dialect) or str(tok) in ("ydotool", "key")
                 for tok in argv)
  ```
  (Adjust `grammar_tokens` to the fixtures' actual shape in Step 3 — the fixtures are the oracle; if parsing the usage line is brittle, paste the expected token shape from the fixture into the test as a literal with a comment citing the fixture line.)
- [ ] **Step 2: Run** → FAIL (no `key_argv`).
- [ ] **Step 3: Implement** in `core/ydotool.py`:
  ```python
  KEY_PER_REPEAT_BUDGET = 0.05  # s; calibrated against the VM acceptance run


  def key_usage_grammar(text):
      """Extract the documented key-argument shape from a captured usage line.

      Both dialects document the key argument as CODE:PRESSED pairs; this
      returns the set of token shapes the fixture prescribes, so tests can
      assert synthesis against the client's own documentation.
      """
      import re

      return set(re.findall(r"\d+:[01]", text)) | set(
          re.findall(r"<CODE>:[01]|CODE:[01]", text)
      )


  def key_argv(chord, repeats=1):
      """One batched `key` argv: each cycle presses the chord, releases in reverse.

      Repeats are a single invocation — daemonless ydotool pays a fresh uinput
      device plus its settle delay per invocation, so "backspace ten" must be
      one call, not ten.
      """
      tokens = []
      for _ in range(repeats):
          tokens.extend(f"{code}:1" for code in chord)
          tokens.extend(f"{code}:0" for code in reversed(chord))
      return ("ydotool", "key", *tokens)


  def key_timeout(repeats, floor=None, per_repeat=KEY_PER_REPEAT_BUDGET):
      """Bound for a batched key invocation; grows with repeats, never fixed."""
      return (floor if floor is not None else INJECT_TIMEOUT) + repeats * per_repeat
  ```
  Calibrate the legacy argv against the legacy fixture in Step 1's files — if 0.1.8's `key` verb takes a different token shape, `key_argv` grows a dialect branch selected via `dialect()` exactly like `noop_argv()` does.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit.** `hug a src/core/ydotool.py tests/unit/core/test_ydotool_key.py && hug c -m "feat(core): batched, dialect-pinned key-verb synthesis"`

---

### Task 3: The gated injector in `core/mediakeys.py`

**Goal:** `tap_key`/`tap_chord` dispatch through a sticky, three-arm, raise-only backend gate; `InjectionUnavailableError` replaces the GNOME-named exception with its `RuntimeError` base intact; both backends translate every failure into it (spec §4.2–§4.4).

**Files:**
- Modify: `src/core/mediakeys.py` (rewrite: docstring identity, exception, gate, backends; keep `KEYS`/`KEY_NAMES`/`parse_key_request`/`MAX_KEY_REPEATS`/`tap_chord`-order contract)
- Modify: `src/core/main.py:190-200` (docstring only)
- Test: `tests/unit/core/test_mediakeys.py` (extend) + `tests/unit/core/test_injection_gate.py` (new)

**Acceptance Criteria:**
- [ ] `issubclass(InjectionUnavailableError, RuntimeError)` holds
- [ ] Selection matrix: override×{remote-desktop, uinput, auto, unknown-value} × {GNOME, non-GNOME} × {Mutter owned, not owned, probe error} resolves per spec §4.2; selection is sticky (second call does not re-resolve); unknown override warns and proceeds with auto
- [ ] A stub backend that RETURNS `"errored"`/`"unknown"` instead of raising still lands dictation in `NO_KEYSTROKES` — the return-style implementation cannot pass
- [ ] `tap_key`/`tap_chord` return None (raise-only); the RemoteDesktop backend translates jeepney's `TimeoutError` into `InjectionUnavailableError`
- [ ] `just pytest tests/unit/core -q` passes; the old `RemoteDesktopUnavailableError` name has zero remaining references in `src/` and `tests/`

**Verify:** `just pytest tests/unit/core -q` → pass; `rg -n "RemoteDesktopUnavailableError" src/ tests/` → no hits.

**Steps:**

- [ ] **Step 1: Failing tests** (`test_injection_gate.py`) — the load-bearing ones:
  ```python
  """The gate: sticky three-arm selection and the total raise-only mapping."""
  import pytest

  from easyspeak.core import mediakeys as mk


  def test_exception_keeps_runtime_error_base():
      assert issubclass(mk.InjectionUnavailableError, RuntimeError)


  def test_matrix_gnome_owned(monkeypatch):
      monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
      monkeypatch.setattr(mk, "on_gnome", lambda: True)
      backend = mk._resolve_backend(
        owned=lambda: True, probe_error=lambda: False, cache=mk._GateCache())
      assert backend.KIND == "remote-desktop"


  def test_matrix_probe_error_stays_gnome(monkeypatch):
      monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
      monkeypatch.setattr(mk, "on_gnome", lambda: True)
      backend = mk._resolve_backend(
        owned=lambda: False, probe_error=lambda: True, cache=mk._GateCache())
      assert backend.KIND == "remote-desktop"  # a wedged bus is not an honest "no"


  def test_matrix_non_gnome_selects_uinput(monkeypatch):
      monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
      monkeypatch.setattr(mk, "on_gnome", lambda: False)
      backend = mk._resolve_backend(
        owned=lambda: False, probe_error=lambda: False, cache=mk._GateCache())
      assert backend.KIND == "uinput"


  def test_sticky_second_call_does_not_re_resolve(monkeypatch):
      calls = []
      monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
      monkeypatch.setattr(mk, "on_gnome", lambda: False)

      def counting_owned():
          calls.append(1)
          return False

      cache = mk._GateCache()
      mk._resolve_backend(owned=counting_owned, probe_error=lambda: False, cache=cache)
      mk._resolve_backend(owned=counting_owned, probe_error=lambda: False, cache=cache)
      assert len(calls) == 1


  def test_unknown_override_warns_and_autos(monkeypatch, caplog):
      monkeypatch.setenv("EASYSPEAK_KEY_BACKEND", "ydotool")  # the old, wrong name
      backend = mk._resolve_backend(
        owned=lambda: True, probe_error=lambda: False, cache=mk._GateCache())
      assert any("EASYSPEAK_KEY_BACKEND" in r.message for r in caplog.records)


  def test_uinput_backend_maps_outcomes_to_raise(monkeypatch):
      """A backend that RETURNS a bad outcome still raises at the boundary."""
      monkeypatch.setattr(mk, "select_backend", lambda: mk.UinputBackend(
          runner=lambda args, timeout: "errored"))
      with pytest.raises(mk.InjectionUnavailableError):
          mk.tap_chord([29, 47])


  def test_uinput_unknown_raises_with_distinct_log(monkeypatch, caplog):
      monkeypatch.setattr(mk, "select_backend", lambda: mk.UinputBackend(
          runner=lambda args, timeout: "unknown"))
      with pytest.raises(mk.InjectionUnavailableError):
          mk.tap_key(14, repeats=1)
      assert any("unknown" in r.message for r in caplog.records)


  def test_remote_desktop_translates_jeepney_timeout():
      backend = mk.RemoteDesktopBackend(
          caller=lambda msg: (_ for _ in ()).throw(TimeoutError))
      with pytest.raises(mk.InjectionUnavailableError):
          backend.tap_chord([29, 47])
  ```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement the gate** in `mediakeys.py` (the vocabulary — `KEYS`, `KEY_ALIASES`, `KEY_NAMES`, `MAX_KEY_REPEATS`, `parse_key_request` — stays untouched):
  ```python
  DBUS_TIMEOUT = 5.0  # s; the GDBUS_TIMEOUT precedent — jeepney blocks indefinitely by default


  class InjectionUnavailableError(RuntimeError):
      """No injection backend answered: refused, missing, or timed out."""


  class RemoteDesktopBackend:
      KIND = "remote-desktop"

      def __init__(self, caller=None):
          self._caller = caller or self._jeepney_call

      def _jeepney_call(self, message):
          from jeepney.io.blocking import open_dbus_connection
          with open_dbus_connection("SESSION") as conn:
              reply = conn.send_and_get_reply(message, timeout=DBUS_TIMEOUT)
          if reply.header.message_type is MessageType.error:
              raise InjectionUnavailableError(" ".join(map(str, reply.body)))
          return reply

      def tap_chord(self, keycodes):
          conn = self._session()  # CreateSession → Start, as today
          try:
              for keycode in keycodes:
                  self._caller(self._keycode_message(conn, keycode, True))
              for keycode in reversed(keycodes):
                  self._caller(self._keycode_message(conn, keycode, False))
          finally:
              self._stop(conn)

      def tap_key(self, keycode, repeats=1):
          for _ in range(repeats):      # per-repeat loop: GNOME stays byte-for-byte
              self.tap_chord([keycode])
  ```
  (The session/message helpers are today's `tap_chord` body factored so `caller` is injectable — the moved code is otherwise verbatim; `TimeoutError` from the bounded call escapes `_jeepney_call` as `TimeoutError`, and the module-level dispatch below translates it. Keep it that way only if the translation test above passes via the dispatch; otherwise translate here.)
  ```python
  class UinputBackend:
      KIND = "uinput"

      def __init__(self, runner=None, owned=None):
          self._runner = runner or yd.run_ydotool
          self._owned = owned or yd.injector_socket

      def tap_chord(self, keycodes):
          self._inject(yd.key_argv(tuple(keycodes)), yd.key_timeout(1))

      def tap_key(self, keycode, repeats=1):
          self._inject(
              yd.key_argv((keycode,), repeats=repeats),
              yd.key_timeout(repeats),
          )

      def _inject(self, args, timeout):
          outcome = self._runner(args, timeout)
          if outcome != "ran":
              # the outcome stays distinct in the log; the spoken fallback is shared
              logger.warning("uinput injection %s: %s", outcome, " ".join(args))
              raise InjectionUnavailableError(f"injection {outcome}: {' '.join(args)}")
  ```
  Gate:
  ```python
  class _GateCache:
      backend = None


  def _mutter_owned():
      from easyspeak.core.ydotool import _client_env  # not used here; see probe below
      raise NotImplementedError  # replaced by the gdbus probe in the real body


  def _resolve_backend(owned, probe_error, cache):
      """Sticky three-arm selection; see spec §4.2. Testable, no I/O."""
      if cache.backend is not None:
          return cache.backend
      forced = os.environ.get("EASYSPEAK_KEY_BACKEND", "").strip().lower()
      if forced == "remote-desktop":
          backend = RemoteDesktopBackend()
      elif forced == "uinput":
          backend = UinputBackend()
      else:
          if forced:  # unknown value: warn, proceed with auto (EASYSPEAK_PASTE_KEYS precedent)
              logger.warning(
                  "Ignoring EASYSPEAK_KEY_BACKEND=%r: unknown backend. "
                  "Known: remote-desktop, uinput, auto.", forced)
          gnome = on_gnome()
          if gnome and (owned() or probe_error()):
              backend = RemoteDesktopBackend()   # owned, or a wedged bus: native path + bounded retry upstream
          else:
              backend = UinputBackend()
      logger.info("key injection backend: %s", backend.KIND)
      cache.backend = backend
      return backend


  def select_backend():
      """Resolve once per process (sticky). The Mutter probe is one bounded
      gdbus NameHasOwner call; its errors arm counts as probe-error."""
      return _resolve_backend(
          owned=_mutter_owned,
          probe_error=_mutter_probe_errored,
          cache=_gate,
      )
  ```
  `_mutter_owned`/`_mutter_probe_errored` wrap one `gdbus`-equivalent jeepney `NameHasOwner` call under `DBUS_TIMEOUT` (error → `probe_error=True`), retried once on error before settling — the "ONE bounded retry" of spec §4.2. Module dispatch:
  ```python
  def tap_chord(keycodes):
      """Inject a chord (down in order, up in reverse). Raises, never returns status."""
      try:
          select_backend().tap_chord(tuple(keycodes))
      except TimeoutError as exc:  # bounded D-Bus wait (jeepney) — OSError family anyway
          raise InjectionUnavailableError(f"injection timed out: {exc}") from exc


  def tap_key(keycode, repeats=1):
      try:
          select_backend().tap_key(keycode, repeats=repeats)
      except TimeoutError as exc:
          raise InjectionUnavailableError(f"injection timed out: {exc}") from exc
  ```
- [ ] **Step 4: Update `press_key`** — its message stops naming GNOME:
  ```python
  def press_key(keycode, repeats=1):
      """Tap `keycode` `repeats` times; True when the keystrokes were delivered."""
      try:
          select_backend().tap_key(keycode, repeats=repeats)
      except (RuntimeError, OSError) as exc:
          logger.warning("Keystrokes could not be injected: %s", exc)
          return False
      return True
  ```
- [ ] **Step 5: Update dictation + core docstrings** (consumer migration, Task 4 rolled in where trivial):
  - `dictation/__init__.py:494`: `except mediakeys.InjectionUnavailableError as exc:`; `:496-498` warning → `"Could not inject the paste keystroke (%s). Dictation needs a working injection backend — see the troubleshooting guide."` styled to existing log conventions.
  - `core/main.py:193-195` docstring → "False if no injection backend answered (see core.mediakeys)."
- [ ] **Step 6: Run** `just pytest tests/unit/core -q` → pass; `rg -n "RemoteDesktopUnavailableError" src/ tests/` → empty; fix the remaining references (`test_mediakeys.py`, `test_dictation.py`) by rename.
- [ ] **Step 7: Commit.** `hug a -u && hug c -m "feat(core): capability-gated key injection (RemoteDesktop | uinput)…"`

---

### Task 4: Probe leniency off GNOME (dictation focus probe)

**Goal:** On non-GNOME sessions a `NO_FOCUS` probe answer proceeds to the clipboard path instead of refusing (spec §4.5); GNOME semantics unchanged.

**Files:**
- Modify: `src/plugins/dictation/__init__.py:434-508`
- Test: `tests/unit/plugins/test_dictation.py` (extend)

**Acceptance Criteria:**
- [ ] `insert_text` with the AT-SPI probe returning NO_FOCUS on a non-GNOME session (monkeypatched `on_gnome() -> False`) proceeds past the probe (reaches clipboard/write path)
- [ ] Same probe result with `on_gnome() -> True` still returns `NO_FOCUS`
- [ ] A helper that cannot run (BACKEND_ERROR) still falls open on both session kinds

**Verify:** `just pytest tests/unit/plugins/test_dictation.py -q -k "focus or lenient" ` → pass.

**Steps:**

- [ ] **Step 1: Failing test** in `tests/unit/plugins/test_dictation.py`:
  ```python
  def test_no_focus_off_gnome_proceeds_to_clipboard(monkeypatch, tmp_path):
      monkeypatch.setattr(dictation, "on_gnome", lambda: False)  # imported in Task 3
      monkeypatch.setattr(dictation, "insert_via_atspi", lambda text: "no_focus")
      called = {}
      monkeypatch.setattr(dictation, "write_clipboard", lambda cmd, text: called.update(text=text) or True)
      monkeypatch.setattr(dictation, "clipboard_tools", lambda: (["wl-copy"], ["wl-paste", "--no-newline"]))
      monkeypatch.setattr(dictation.mediakeys, "tap_chord", lambda chord: None)
      monkeypatch.setattr(dictation, "_restore_clipboard_later", lambda *a, **k: None)
      monkeypatch.setattr(dictation, "focused_wm_class", lambda: None)
      assert dictation.insert_text("hello") == dictation.INSERTED
      assert called["text"] == " hello" or called["text"] == "hello"
  ```
- [ ] **Step 2: Implement** — in `insert_text`, replace the bare probe gate:
  ```python
  from easyspeak.core.tray import on_gnome  # one definition of "which desktop"

  # inside insert_text, replacing `if not has_focused_text_field():`
  if has_focused_text_field() is False and on_gnome():
      return NO_FOCUS
  if not has_focused_text_field():
      # Off GNOME the AT-SPI tree is unreliable (COSMIC-native apps may expose
      # nothing): a missed probe must not block a working paste. Pasting into
      # nothing is harmless; refusing is not.
      logger.debug("focus probe found nothing; proceeding (non-GNOME leniency)")
  ```
  (`has_focused_text_field()` currently returns a bool from `insert_via_atspi("") != NO_FOCUS`; make it return the tri-state or keep bool and call `insert_via_atspi("")` directly here — the plan's shape: compare against `NO_FOCUS` explicitly, per the spec's "a probe that cannot run still falls open".)
- [ ] **Step 3: Run** `just pytest tests/unit/plugins/test_dictation.py -q` → pass.
- [ ] **Step 4: Commit.** `hug c -m "feat(dictation): missed focus probe no longer blocks the paste off GNOME"`

---

### Task 5: Packaging, docs, translations

**Goal:** ydotool ships as a hard dep; every doc surface the change invalidates is updated in one sweep; the one new spoken string reaches all four catalogs (spec §7, §8).

**Files:**
- Modify: `packaging/nfpm.yaml` (deb + rpm dep lists)
- Modify: `docs/usage.md` (env-var table), `docs/commands.md:140-141`, `docs/compatibility.md` (COSMIC column + 3 KDE footnotes), `docs/packaging.md:54` area, `docs/installation.md:88-97` area, `docs/troubleshooting.md`, `docs/how-it-works.md:9-12`
- Modify: `src/plugins/browser/__init__.py:993` (string)
- Modify: `src/plugins/dictation/locale/*/LC_MESSAGES/dictation.po` (via `just translations`)

**Acceptance Criteria:**
- [ ] `rg -n "ydotool" packaging/nfpm.yaml` shows it beside wl-clipboard in both dep lists
- [ ] `docs/usage.md` env table has `EASYSPEAK_KEY_BACKEND` (remote-desktop | uinput | auto, sticky) and `EASYSPEAK_GRID_DRY_RUN` marked grid-only
- [ ] compatibility.md has a COSMIC column and no footnote contradicting the new behavior ([^browser], [^dictation], [^volume] updated)
- [ ] `just check-translations` and `just check-docs` pass; `just lint-md` passes

**Verify:** `just check-translations && just check-docs && just lint-md` → pass.

**Steps:**

- [ ] **Step 1: nfpm.yaml** — add `- ydotool  # key injection on non-GNOME desktops` beside each wl-clipboard line (`:56`, `:80`).
- [ ] **Step 2: browser string** — `core.speak(_("Keystrokes need a working injection backend — see the troubleshooting guide."))`; then `just translations de && just translations es && just translations fr && just translations it`.
- [ ] **Step 3: docs sweep** — usage.md rows; commands.md → "Dictation places text by pasting it, which needs `wl-clipboard` installed. Off GNOME a missed focus probe no longer blocks the paste."; compatibility.md COSMIC column per spec §8 (mark only what Task 7 verifies); troubleshooting.md gains "Key injection backend" section (three-arm gate, `EASYSPEAK_KEY_BACKEND`, uinput provisioning recap, mis-stuck-session recovery: restart the daemon or force `remote-desktop`); packaging.md + installation.md gain ydotool beside wl-clipboard; how-it-works.md dictation line gains "via the platform's injection backend (Mutter RemoteDesktop or ydotool)".
- [ ] **Step 4: Commit.** `hug a -u && hug c -m "docs+packaging: ydotool dep, backend docs sweep, refusal string"`

---

### Task 6: Full local gate

**Goal:** Every just recipe green before VM acceptance.

**Files:** none (verification only).

**Acceptance Criteria:**
- [ ] `just test-pythons`, `just integration`, `just acceptance`, `just types`, `just precommit`, `just check-translations`, `just check-docs`, `just check-python-packages` all exit 0

**Verify:** the eight commands above, in order.

**Steps:**

- [ ] **Step 1:** run them in that order; fix any fallout (types and precommit are the likely stragglers: unused imports from the move, REUSE headers on new files — `core/ydotool.py` needs its SPDX header per repo convention).
- [ ] **Step 2:** no commit unless fallout required changes.

---

### Task 7: COSMIC VM acceptance + GNOME regression (evidence for the compatibility column)

**Goal:** Spec §9's acceptance scenarios executed on the `easyspeak-cosmic` VM with screenshot receipts, plus the end-to-end GNOME regression on the dev host (spec §9, §12).

**Files:**
- Create: `docs/superpowers/plans/2026-10-17-acceptance-evidence.md` (receipts; fork-only, stripped from the upstream PR per §10.5)

**Acceptance Criteria:**
- [ ] VM: dictated text lands in a focused field without manual paste (screenshot)
- [ ] VM: "press enter" lands in browser mode
- [ ] VM: voice "volume up" pops COSMIC's own OSD (screenshot)
- [ ] VM: "backspace ten" removes ten chars as one batched invocation inside ~2s (log line shows ONE `key` invocation)
- [ ] VM: `EASYSPEAK_KEY_BACKEND=uinput` forces the backend on any session; unknown value warns + auto
- [ ] Dev host (GNOME 42): dictated text lands end-to-end; volume replay fires; routing log says `remote-desktop`
- [ ] Clean-VM package check: after `sudo apt install ./easyspeak*.deb` + the documented uinput provisioning, dictation works with no other manual steps (0.1.8 daemonless dialect)

**Verify:** receipts file contains the screenshots + command transcripts; every §12 VM/GNOME checkbox ticked.

**Steps:**

- [ ] **Step 1: VM prep** per the OB runbook (`virsh start easyspeak-cosmic`, SSH check, `wayland-1` present, watcher host registered). Install the freshly built deb (Task 6's `check-python-packages` artifact or `just check-deb-package` output) — NOT the checkout venv — so the clean-install criterion is honest. Apply the documented uinput provisioning from `docs/troubleshooting.md`.
- [ ] **Step 2: Scenarios 1-5** — start the daemon (`systemd-run --user --unit=easyspeak-acceptance --setenv=XDG_CURRENT_DESKTOP=COSMIC ~/easyspeak/.venv/bin/easyspeak` only if running from the checkout; the deb installs its own autostart), then per scenario: actuate (voice/`gdbus`), `virsh --connect qemu:///system screenshot`, convert + crop (ImageMagick), and paste transcript + image into the receipts file. Backspace-ten latency: read the daemon log's single `key` invocation + `time` the command.
- [ ] **Step 3: GNOME regression** on the dev host (Pop 22.04/GNOME 42): run the daemon, dictate into a field (text lands), press a volume key via voice (OSD fires), assert the log line `key injection backend: remote-desktop`.
- [ ] **Step 4: Commit receipts** (fork-only file). `hug c -m "test: acceptance receipts for the compatibility column (fork-only)"`

---

### Task 8: PR hygiene (§10.5)

**Goal:** The upstream PR carries code + user docs only; #234 carries the distilled summary and the evidence receipts.

**Files:**
- Modify: none on this branch (a PR-branch squash/rebase decision deferred to pr-fix/cv-impl)
- Create: comment on ctsdownloads/easyspeak#234

**Acceptance Criteria:**
- [ ] The PR body states the #233 dependency and that `docs/superpowers/` artifacts will be stripped before the PR leaves draft
- [ ] #234 has the distilled summary + receipts

**Verify:** PR file list contains no `docs/superpowers/` paths (checked again at ready-for-review time); tracker-ops `get-item --ref 'ctsdownloads/easyspeak#234'` shows the comment.

**Steps:**

- [ ] **Step 1:** comment on #234 via tracker-ops (`comment-item --ref 'ctsdownloads/easyspeak#234' --body-text "…"`) — distilled design summary + the acceptance receipts.
- [ ] **Step 2:** before leaving draft: `hug` rebase/drop of the `docs/superpowers/*` commits onto a clean PR branch (or interactive rebase per the then-current `cv-impl` guidance).

---

## Self-review notes (already applied)

- Spec §4.4's browser bullet needs no code change beyond `press_key` internals — Task 3 covers the message; Task 5 the spoken string.
- The `just translations` recipes take one `lang` each (per justfile) — Task 5 runs four.
- `core/ydotool.py` needs an SPDX/REUSE header (Task 6 precommit will flag; added to Task 6's step).
- `on_gnome` import in dictation: `core.tray` does not import `core.mediakeys` — no cycle (roast-verified).
