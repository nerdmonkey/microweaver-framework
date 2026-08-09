# Versioning and stability

Microweaver follows [Semantic Versioning](https://semver.org/). The project is
currently in the `0.x` series, where minor releases may include incompatible
changes. Those changes are called out in the [changelog](../CHANGELOG.md).

The guarantees below take effect with v1.0.0. After that release:

- patch releases fix bugs without intentionally changing documented behavior;
- minor releases may add backward-compatible features; and
- major releases may make incompatible changes after the deprecation process
  below.

## Stable surfaces

The following documented, non-experimental surfaces are stable within a major
release:

- **Device configuration:** keys listed in
  [`device_config.json.example`](../device_config.json.example), including their
  types, meanings, accepted values, and defaults. A minor release may add an
  optional key with a safe default, but cannot rename or remove a key or change
  the behavior of an existing default.
- **Python APIs:** documented public classes, functions, methods, and properties
  in `app/` and `config/`. Constructor parameter names, positional order, and
  defaults are part of the contract. Adding an optional parameter at the end of
  a signature is backward compatible; reordering parameters or making an
  optional parameter required is not.
- **Command-line interface:** documented `tinker.py` commands and options,
  including machine-readable output explicitly documented as such. New optional
  commands or flags may be added in a minor release. Human-readable wording,
  spacing, progress output, and log messages are not stable interfaces.
- **MQTT interface:** documented topic defaults and payload fields, including
  field types and meanings. A minor release may add a new topic or an optional
  payload field. Removing or renaming a topic or field, changing a field's type
  or meaning, or making an optional field required is a breaking change.

Private names (those beginning with `_`), undocumented implementation details,
tests, examples, and features explicitly marked experimental are outside this
guarantee.

## Deprecation process

An incompatible stable-surface change is introduced as a deprecation in a minor
release before it can be removed in the next major release. The release that
introduces the deprecation will:

1. keep the old behavior working for the remainder of the current major series;
2. document the replacement and migration steps in the changelog and relevant
   reference documentation; and
3. emit a warning when doing so is practical on-device and does not expose
   credentials or other sensitive values.

For example, a renamed configuration key remains accepted throughout the current
major series. If both names are present, the replacement key takes precedence and
Microweaver warns that the old key is deprecated. A renamed Python parameter or
MQTT field follows the same compatibility window: existing callers and deployed
consumers continue to work until the next major release.

Deprecations are removed only in a major release. Its release notes list every
removal and link to migration instructions so fleet operators can update device
configuration, application code, and MQTT consumers before deploying it.
