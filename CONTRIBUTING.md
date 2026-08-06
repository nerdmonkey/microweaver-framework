# Contributing to Microweaver

Thanks for your interest in improving Microweaver. This guide covers how to
get set up, the conventions the codebase follows, and how to submit a change.

## Project overview

Microweaver is a MicroPython framework for ESP32/microcontroller IoT
projects. Application code (`app/`, `config/`, `boot.py`, `main.py`) runs
**on-device** under MicroPython. The test suite runs on regular CPython via
pytest — MicroPython-only modules (`network`, `umqtt.simple`, `machine`, …)
are stubbed in `tests/conftest.py`. See `README.md` for project structure and
`tinker.py` build/deploy instructions.

## Getting set up

```shell
git clone https://github.com/nerdmonkey/microweaver-framework.git
cd microweaver-framework
pip install -r requirements.txt   # pytest, pytest-mock, pytest-cov, black, flake8, isort
```

## Service pattern

New hardware/network functionality belongs in `app/services/` as a small
plain class, following the shape of `app/services/wifi.py`,
`app/services/mqtt.py`, and `app/services/watchdog.py`:

- Constructor takes explicit named args (not `**kwargs`), with sane defaults.
- Wraps exactly one MicroPython module and exposes a small, intention-revealing
  method surface (`connect()`, `feed()`, `is_connected()` — not a passthrough).
- No error swallowing beyond what's needed to keep a long-running device loop
  alive — failures get printed and either retried or re-raised.

Do not introduce dataclasses, a dependency-injection framework, or `**kwargs`
bags — match the existing style.

## Config

Runtime-tunable values go through `config/app.py`'s `Setting` class, backed
by `device_config.json` (gitignored) with `device_config.json.example` as the
documented template:

1. Add the key to `device_config.json.example` (snake_case).
2. Read it in `Setting.__init__` via `self._value(...)`, `self._int(...)`, or
   `self._bool(...)`, assigned to an `UPPER_SNAKE_CASE` attribute, defaulting
   to what the consuming class would use standalone.
3. Never require the key — the device must still boot with a blank config.

## Testing

Framework: pytest + `pytest-mock` (`mocker` fixture) + `pytest-cov`. Look at
`tests/unit/test_mqtt_connection.py` and `tests/unit/test_wifi_service.py`
before writing new tests.

- Plain `test_<behavior>` functions, no test classes.
- Mock the MicroPython-backed dependency at the point it's imported into the
  module under test, e.g. `mocker.patch("app.services.mqtt.MQTTClient")` —
  not the stdlib/umqtt source.
- Small `make_<thing>_service()` helper factories beat a shared fixture when
  only 1-2 tests need the object.
- Control timing deterministically: `mocker.patch("time.sleep")`,
  `mocker.patch("time.time", side_effect=[...])`. Never let a test sleep.
- New MicroPython-only imports need a stub added to the
  `sys.modules.setdefault(...)` loop in `tests/conftest.py`.
- Target 100% branch coverage on files you touch:
  `pytest --cov=app --cov=config --cov-report=term-missing`.

## Before opening a PR

```shell
pytest -q
black --check <changed files>
flake8 <changed files>
isort --check-only <changed files>
```

`black`/`isort` are safe to auto-fix (`black <files>`, `isort <files>`) —
re-run tests after, since import-order changes touch the top of files you
may have open.

## Submitting a change

**Never commit directly to `main`.**

```shell
git checkout main && git pull --ff-only
git checkout -b <type>/<short-desc>          # feat/, fix/, test/, docs/, chore/
# ... commit ...
git push -u origin <branch>
gh pr create --title "..." --body "..."       # Summary + Test plan sections; "Closes #N" if fixing an issue
```

- Commit subjects follow Conventional Commits scoped to the area touched,
  e.g. `feat(runtime): add hardware watchdog service`.
- Open PRs against `main` and fill in the pull request template.

## Reporting bugs / requesting features

Open an issue at
https://github.com/nerdmonkey/microweaver-framework/issues. For security
vulnerabilities, see `SECURITY.md` instead of filing a public issue.
