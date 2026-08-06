## Summary

<!-- What does this PR change, and why? -->

## Related issue

<!-- Closes #N, if applicable -->

## Test plan

- [ ] `pytest -q` passes
- [ ] `black --check <changed files>` passes
- [ ] `flake8 <changed files>` passes
- [ ] `isort --check-only <changed files>` passes
- [ ] 100% branch coverage on touched files (`pytest --cov=app --cov=config --cov-report=term-missing`)

## Checklist

- [ ] New/changed services follow the pattern in `CONTRIBUTING.md`
- [ ] New config keys added to `device_config.json.example` and `config/app.py`
- [ ] New MicroPython-only imports stubbed in `tests/conftest.py`
