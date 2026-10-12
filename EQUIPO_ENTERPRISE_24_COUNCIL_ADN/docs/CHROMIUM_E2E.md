# Chromium acceptance suite: prepared, not executed

Status at this delivery: **Chromium NOT_RUN**. No Playwright dependency was installed, no browser was downloaded or launched, and no screenshots, traces, visual pass or real-provider success is claimed. The preceding cloud-browser localhost navigation was denied with `ERR_BLOCKED_BY_CLIENT`; this suite was authored without trying another browser, hostname, shell browser or headless path around that denial. A browser run requires a separately supported, permitted execution environment.

## What is executable

`tests/e2e/` contains **92 authored cases**, enumerated in `authored-cases.json`:

- Nine real navigation/page reload cases, one per page.
- Twenty-seven responsive cases: all nine pages at 390, 768 and 1440 CSS pixels. They check document overflow and capture screenshots; visual inspection of those screenshots is still required.
- Keyboard dialog, tab navigation, browser history, graph controls and basic accessibility assertions. This is not a WCAG or screen-reader conformance audit.
- Generation through actual application buttons, fields, HTTP routes and the real asynchronous generation pipeline, with an explicitly inert provider. Success, exactly N profiles, one bound consent, partial evidence, double clicks, changed options, invalid ranges, failure, fresh retry consent, cancellation, late provider completion, reload, stale polling, recovery and draft resumption are covered by authored assertions.
- Native recipe and definitions browser downloads are actually saved and parsed when run. Their versions, formats, IDs, bytes, SHA-256 and filenames must match the server's export manifest. Restoring the retained design must recover byte-identical native output.
- Targeted local workflows: multi-version project save/load/copy, profile editing and dirty dismissal, proposed tool allow/deny persistence and overlap rejection, subteams, manual Council minutes, capability creation/search and separate reviewed assign/activate/deactivate/unassign operations, synthetic model catalog/assignment, synthetic inventory and receipts.
- Evaluation range/approval guards are checked without executing commands. DSH coverage checks disabled mutation controls and a synthetic read-only status observation. It does not pair, connect, restart, inspect user paths, back up DSH, import, reload or activate a runtime.
- Added local cases cover independent governance review, exact weighted score and corrected-review history, duplicate/stale drafts, one-sample promotion/succession rejection, five-sample promotion proposals, manual supervisor/Owner decisions, lease acquire/renew/release/overlap/writer limits/traversal guards, model priority bounds, versioned skill feedback, remediation cancellation/order, exact per-profile/subteam capability recipients and immutable local capability copies. These do not authenticate reviewers or exercise live integrations.
- Every case records console/JavaScript errors and rejects unexpected external browser traffic. Expected server rejections must assert the exact HTTP 400 action, error body and visible notice; only that action’s matching Chromium failed-resource console event is separately recorded. All unexpected console errors still fail. Browser requests, including a popup’s first request, are restricted at context level to its own newly created fixture origin.

These are assertions to run, not assertions already proven. Browser behavior, locator usability, rendered layout and timing may still reveal failures and must be fixed and rerun before acceptance.

## Control-by-control matrix and remaining gaps

`tests/e2e/control-matrix.json` now inventories **403 control rows**: all 381 original HTML controls and 22 explicit JavaScript-created families. The prior inventory had 397 rows. Six newly identified dynamic families were added, and three incorrect/broad dynamic selectors were corrected; inventory repair is not increased behavioral coverage. Static summary selectors now use their source labels rather than misleading descendant indices; six previous rows selected the wrong disclosure. Name-less static buttons are scoped by exact source text so later dynamic cards cannot shift their indices.

- 179 rows map to authored local behavior assertions, all **NOT_RUN** (previously 91).
- 224 rows remain **MANUAL** (previously 306). They are not 224 independent business workflows: 92 are fields/options, 35 disclosures, 3 hidden identity fields, 22 links, 64 actions and 8 repeated dynamic families. These roles overlap workflow families and must not be summed as distinct missing scenarios.
- 95 of those manual rows belong to explicitly unverified external/integration families. Other gaps remain local.
- Every row records a behavior family, control role, coverage scope, remaining work and source constraints. Mapped rows list authored case titles as workflow/suite traceability; this is not a claim that every listed case asserts every field or variant. There are 47 organizational families, not a claim of 47 independently verified workflows.
- Options inside a select are not separate inventory rows. A happy-path field assignment is not proof of every option, boundary or invalid input. All browser statuses remain NOT_RUN.

Important remaining local cases include lease expiration and simultaneous version conflicts, additional tool-policy recommendation/inheritance/validation branches, hierarchy and supervisor editing, complete Council session switching and coverage, further governance adversarial/reviewer cases, full remediation reviewer/closure transitions, capability pagination and action×target combinations, resource-workflow per-agent recommendations, additional native/Cordis artifact downloads and disclosure/link reachability. External catalog comparison/install-report workflows, public-reference ingestion and evaluation execution/cancellation require isolated synthetic adapters or explicitly authorized integration environments. The new scope reduces authored gaps; it does not complete all UI acceptance.

For a concise distinction between repeated controls and genuinely distinct scenarios, see `docs/CHROMIUM_COVERAGE_AUDIT.md`.

External or consequential paths remain separately unverified: live paid LLM/provider behavior, external GitHub/static-website reading, real plugin catalogs, actual DSH pairing/readbacks/import/restart/reload, operating-system clipboard permissions, Windows credential persistence, and Excel/COM. The harness intentionally blocks relevant actions rather than touching user accounts or installations. Testing those paths requires their own authorization, environment and evidence; this suite does not grant it.

## Isolation and provenance

The runner starts `fixture_server.py`, which imports the actual packaged application, serves its actual HTML/JS/CSS and binds **127.0.0.1 with port 0**. The OS chooses a fresh port. There is no configurable base URL and no fallback to port 8765 or an existing process.

A temporary directory contains synthetic projects, capability SQLite storage and local records. Each test resets to a separate synthetic state. The user's project directory, credential store, configured DSH and Excel files are never selected. The fixture uses `MemoryOnlyStore` and a conspicuous noncredential sentinel; persistent key storage and any other key value are refused. Do not enter real credentials into the fixture.

Provider repository/design responses come solely from bundled `synthetic_data.py`. The response records `mock_only`/fixture provenance, and `/api/state` reports `NOT_RUN_E2E_FIXTURE_ONLY` for live-provider verification. Real pipeline validation still runs. Browser success with these responses proves local orchestration/UI behavior only, not model quality or actual provider compatibility.

The server process denies outbound socket connections and subprocess launches. A fixture action allowlist prevents DSH pairing/launch/backup, workbook access, arbitrary evaluations, external catalog reads and unimplemented provider actions. DSH status is an isolated observation with no connection; no runtime source is modified. The temporary fixture controller requires the same session cookie, origin and CSRF token as the app and exists only in the test server subclass.

## Requirements and supported setup

Use a permitted machine/environment, Python **3.11+**, Node.js **22 LTS** and the exact pinned package **@playwright/test 1.56.1** in this suite's package.json. Its matching Playwright Chromium must be installed on that machine. The suite does not use a system Chrome profile, saved cookies or extensions. The Node major is pinned by the Windows runner; Python is otherwise standard-library only for this fixture.

Version 1.56.1 is a deliberate reproducible baseline, not a claim that it is the latest release. Official references:

- Release: https://github.com/microsoft/playwright/releases/tag/v1.56.1
- Installation and platform prerequisites: https://playwright.dev/docs/intro
- Browser installation: https://playwright.dev/docs/browsers
- Downloads: https://playwright.dev/docs/downloads
- Traces: https://playwright.dev/docs/trace-viewer

The manifest pins the direct package. No fabricated lockfile is included: the package was not installed here. Installation on the chosen machine will create `package-lock.json`; retain it with that run's provenance. If platform prerequisites or policies block the browser, stop and report the precise blocker. Do not change hostname, switch to a shell/headless browser, or attach to a user process to evade a denied action.

### Windows: explicit user-run route

Extract the complete package to a new folder. In a terminal in `tests\e2e`, after reviewing the dependency installation:

```bat
npm install --ignore-scripts
node_modules\.bin\playwright.cmd install chromium
run_chromium.cmd
```

The CMD runner never installs or downloads anything automatically. It verifies basic tools, runs the pure-Python fixture selfchecks, and then starts a headed Chromium run. `run_chromium.cmd --headless` is an optional user-selected mode only in an environment where browser access is permitted; it is not a workaround for a browser denial.

If `python` is not the selected interpreter, set `ORGDNA_E2E_PYTHON` to the full path to Python 3.11+ before running. No server address, DSH path or credential should be supplied.

### Other permitted environments

In `tests/e2e`, install the pinned dependency and its matching Chromium as above using the platform's local Playwright binary. Then run `npm test` or `npm run test:headed`. Linux may require administrator-managed browser system packages; follow the official requirements and obtain any required authorization instead of having this runner install system packages.

## Results and acceptance

The default uses one worker and no retries, so a flaky failure is not hidden. Playwright writes only locally under `tests/e2e/artifacts/`:

- `results.json`: case outcomes and failure details.
- `html/`: human-readable report; `npm run report` opens it.
- `test-results/`: screenshots, traces, retained failure videos and downloaded files.
- Each case attaches fixture counters and captured console errors.

Review every failure, actual downloads, all 27 responsive screenshots and the relevant traces. Record OS, Python/Node/Playwright/Chromium versions, package lock, tested source hashes and date. Fix problems and rerun affected cases plus the full suite after final edits. Keep real-provider/DSH/Excel and unscripted matrix rows explicitly unverified. A successful run of these 92 cases alone is not “everything tested” or release acceptance.

## Checks performed without a browser

On 2026-10-08 the author ran:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests/e2e -p "test_*fixture.py"
node --check tests/e2e/fixtures.cjs
node --check tests/e2e/playwright.config.cjs
node --check tests/e2e/navigation.spec.cjs
node --check tests/e2e/generation.spec.cjs
node --check tests/e2e/workflows.spec.cjs
node --check tests/e2e/governance.spec.cjs
node --check tests/e2e/coordination.spec.cjs
node --check tests/e2e/learning.spec.cjs
PYTHONDONTWRITEBYTECODE=1 python tests/e2e/build_matrix.py
node --check tests/e2e/list_authored.cjs
node tests/e2e/list_authored.cjs --write
```

Result: 18 pure fixture selfchecks passed (12 base + 6 learning/capability); JavaScript syntax checks passed; 92 authored declarations were enumerated without importing Playwright or executing test bodies. The selfchecks exercised synthetic state/storage, action/credential guards, inert pipeline/export schemas, DSH observation, actual governance/lease/model and feedback/capability data semantics, exact source inventory preservation and matrix honesty. **No HTTP fixture server or browser was started for these checks.**


## Separate test-only extension, original candidate preserved

The 92-case revision is a separate source patch. It is **not** included in the frozen candidate ZIP with SHA-256 `e7c8cfd409a8394e4f5cd225e2b42773e5e59f6c4fa75accfafd85e969519eda`. The original 73-case ZIP was not rebuilt or replaced. Only `tests/e2e/` and these documentation files were changed; application, engine, DSH and launcher files must match the candidate’s hashes before any future run. A source-hash record and the patch’s SHA-256 accompany this extension. An eventual Chromium report must identify whether it tested the original candidate or the patched test source against the unchanged runtime.
