# Suite → DSH harness

`DSHHarness(launcher, connection)` coordinates the existing launcher and ephemeral
read-only bridge. It does not install software, create credentials, kill a process,
change a profile or launch a second team. `engine.launcher` independently handles
safe startup/reuse of the suite; reaching the suite API proves that side is active.

## API workflow

1. `dsh-harness-prepare`: same path/port/backup inputs as `dsh-launch-inspect`,
   optional `bridge_port`, `wait_seconds` (1–120), and `expected_definition_sha256`.
   Only `operation: reuse` is accepted. Inspection and health are read-only.
2. Review `plan.launcher_plan` (EXE, arguments, hashes, ports, profile/config and
   backup destinations) and the separate harness `plan.plan_sha256`.
3. If an existing listener is found, no launcher call or backup is made. A TCP
   listener has unknown identity until explicit native pairing succeeds.
4. If DSH is absent, `dsh-harness-start` requires the harness `plan_sha256`,
   `start_confirmed`, `backup_confirmed`, `execute_confirmed`,
   `interruption_acknowledged`, and `preservation_unverified_acknowledged`.
   The existing launcher verifies its exact plan and backup again. Its original
   EXE is invoked once with `--headless --no-open --reuse`. It is not rewritten.
5. `dsh-harness-check` polls readiness within the approved deadline, without
   sleeping the HTTP handler or launching again. Timeout/failure leaves processes
   alone. Repeated or uncertain start responses never replay the same plan.
6. Native DSH activation/pairing is a separate explicit owner step. Submit the
   native addon screen's ephemeral code using `dsh-harness-pair`, harness
   `plan_sha256`, `bridge_port`, `pairing_code`, and `pair_confirmed: true`.
   The code/token never appears in public harness state or its plan and is not
   read from logs, browser storage, cookies, or configuration.
7. Pairing executes authenticated handshake then `diagnose` and two profile
   readbacks. `dsh-harness-verify` repeats verification without new pairing.
   `READ_ONLY_VERIFIED` means matching roster hashes and authenticated bridge
   possession, not runtime session identity, task dispatch, model availability,
   native wakeup, full plugin compatibility or permission to execute actions.
   An optional expected roster hash must match. No expected hash means stable
   observed roster only, not proof it equals the suite's chosen organization.
8. `dsh-harness-clear` clears the plan; it never kills DSH or disconnects the
   separately approved bridge. It refuses to hide a pending startup.

State is session-local. UI rendering calls `public()` without network I/O and
invalidates cached readback on pairing expiry/disconnect. A refreshed handshake
alone is `READBACK_RECHECK_REQUIRED` until roster verification is repeated.

## Honest activation boundary

The reviewed original 1.1.1 launcher cannot preserve a previous `--patch` at fresh
startup. There is no invented install command, `extraArgs` configuration, silent
launcher derivation, global config rewrite, or automatic plugin authorization.
The distribution's existing `preflight.mjs` and `prepare-overlay.mjs` are preparation
artifacts; package metadata alone does not prove runtime overlay support. Loading
an additive namespace overlay requires an installed/runtime-specific supported
route and explicit native PluginManager prerequisites/approval. Until those are
verified locally, activate/pair through the supported native flow and report the
missing prerequisite. A user-approved original launcher start can succeed while
the addon remains absent, which is correctly reported as pairing required.

## Verification

`python -m unittest discover -s tests -p 'test_dsh_harness.py' -v`

Tests use an inert launcher double and the real addon transport with mock official
services on a new loopback port. They never execute the supplied EXE, inspect the
user's installation, or contact DSH/private network services. Windows startup and
preservation of actual profiles/sessions remain unverified until an authorized
local test.
