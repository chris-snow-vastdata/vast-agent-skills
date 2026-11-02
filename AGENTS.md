# VAST agent skills: index for agents

This repository holds skills for working with VAST Data clusters. If your agent loads
[Agent Skills](https://agentskills.io) itself, install them (see README.md) and ignore this file.
Otherwise: when a task involves a VAST cluster, read `skills/vast/SKILL.md` first, then the
area guide it points to under `skills/vast/references/`, and follow them. Paths inside the
skill are relative to `skills/vast/`.

The area guides (`skills/vast/references/`): `tenants-network.md`, `views-protocols.md`,
`identity-access.md`, `data-protection.md`, `monitoring.md`, `database.md`, `event-broker.md`,
`dataengine.md`. `skills/vast/SKILL.md` has the table of which to read when.

Rules that apply everywhere: find the cluster's version first; take endpoints, fields and
allowed values from the cluster's own spec (`skills/vast/scripts/vast_api.py spec ...`),
not from memory; read before changing; show the user every change and get a yes first.
