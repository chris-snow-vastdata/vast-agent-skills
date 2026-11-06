# Changelog

Each release is a git tag `vX.Y.Z` whose version matches `version` in both plugin manifests.
Claude Code plugin installs update only when that version changes, so every release bumps it.
How to cut one: [AUTHORING.md](AUTHORING.md#releasing).

## [0.2.1] - 2026-11-06

### Changed

- The quick install now fetches the latest release, not the tip of `main`. It asks GitHub for the
  newest release tag, removes any previous copy so no stale files are left behind, and prints the
  version it installed. The command that follows `main` is still in the README as an option.
- Pinning a quick install is now one change: set `TAG` to the release instead of looking it up.

## [0.2.0] - 2026-11-06

### Added

- Keeping the VMS password out of the conversation: the user stores it in a 0600 file without
  echo, and the agent loads it for each run without reading it. Generated secret keys are
  handled the same way.
- A list filter VMS doesn't support is ignored and returns every row, so re-check rows
  client-side before acting on one, above all before a delete.
- VIP pool pitfalls: the `QUERY_ENGINE_CNODE_GROUP` role for the Query Engine pool (5.4.6), and
  the rejection of a pool bound to fewer than two CNodes.
- Identity pitfall: `POST /users/` returns 400 without `local_provider_id` on `/api/latest` (5.4.6).
- Tagged releases, this changelog, and a validator check that both manifests carry the same
  version and that it has a changelog entry.

## [0.1.0] - 2026-11-02

### Added

- The `vast` skill: connecting and API discovery, plus area guides for tenants and networking,
  views and protocols, identity and access, data protection, monitoring, VAST Database, the
  Event Broker and DataEngine.
- `scripts/vast_api.py` (discovery and safe calls) and `scripts/vast_monitor.py` (read-only
  health and metrics).
- Install paths: `install.sh`, the Claude Code plugin marketplace, and the Cursor plugin manifest.
