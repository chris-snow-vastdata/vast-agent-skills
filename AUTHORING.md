# Authoring standard for VAST skills

These skills are for **VAST customers**: people with a VAST cluster, its Web UI and REST API,
the public knowledge base, and public tools; never VAST source code or internal systems.
They must work in any agent that reads the open Agent Skills format (Claude Code, Cursor,
OpenAI Codex and others) and on any VAST release the skill claims to cover.

## Format (Agent Skills, agentskills.io)

One skill, so the agent has a single entry point and the foundation always loads first:

```
skills/vast/
  SKILL.md                    front matter (name, description) + the foundation + the area table
  references/<area>.md        one guide per area, read only when a task needs it
  references/<area>/*.md      detail an area guide points to
  scripts/*.py                Python 3.8+, standard library only
```

- Front matter: only `name` (`vast`) and `description` (at most 1024 chars, quoted, says what
  and when with the words users type). No agent-specific fields.
- `SKILL.md` stays short (under ~400 lines); each area guide under ~400 lines, with long
  tables moved to `references/<area>/`.
- Adding an area: write `references/<area>.md`, add a row to the table in `SKILL.md`, the README
  and `AGENTS.md`.
- Tool-neutral wording: "run", "read", "ask the user", never one agent's tool names.
- Paths are written relative to `skills/vast/` (`scripts/vast_api.py`, `references/views-protocols.md`);
  markdown links are relative to the file they're in.

## The rule that makes skills work across versions

**Never state an endpoint, field or allowed value as fact without telling the agent how to
check it on the user's cluster.** VAST's API changes between releases. Every skill teaches:

1. **Find the version**: `vast_api.py version`.
2. **Read the docs for that version**: `vast_api.py kb search '<topic>' --version X.Y`, then
   `vast_api.py kb get <url>`. The KB (kb.vastdata.com) is the authoritative how-to.
3. **Check the exact API on this cluster**: `vast_api.py spec search|show|model ...` reads the
   specs the cluster itself serves. Field names, required fields and enums come from here.
4. **Read before you change**: list what exists; plan; ask the user; then create, checking each
   object before the next.

Concrete values in a skill (field names, enums, error messages) are examples, each tagged
with where they were checked, e.g. *(5.5 API)*, *(seen on 5.5.3)*. Prefer "the field that
controls X (on 5.5: `allowed_delegations`)" over a bare field name.

## Safety

- Reads (GET) are always fine. Anything that creates, changes or deletes: show the user the
  exact request first and get a yes (the helper's `call` is a dry run without `--yes`).
- Destructive or disruptive operations (deleting views/tenants/snapshots, changing
  protocols on a live view, rotating keys, upgrades, failover) need an explicit warning of
  the impact, in the skill, next to the operation.
- Never print or store secrets beyond what the user asked for; never put credentials in files
  that would be committed.

## Content

- Lead with the mental model: which objects exist, how they relate, what order they are made in.
- Then workflows (numbered steps with the checks), then pitfalls: **symptom or exact error →
  cause → fix**, tagged with the version where it was seen.
- Point to the KB page for each workflow (by title and URL) rather than restating long procedures.
- Name the public tools where they fit: `vastpy` / `vastpy-cli` (VMS REST, any version),
  `vastdb` (VAST Database SDK), `vastde` (DataEngine CLI), Terraform provider `vast-data/vastdata`,
  `vast-admin-mcp`, `vast-csi`. Don't invent commands for them: tell the agent to check `--help`.
- Nothing internal: no source-code paths, internal hostnames, test environments, or default
  lab passwords.

## Verification status

Each area guide (and `SKILL.md`) ends with a short "Verified" line: which release(s) its examples were checked
against and how (spec read, KB read, live read-only calls, live end-to-end run).

## Checking before you publish

`python3 scripts/validate.py` checks the front matter, sizes and links, and fails on anything
that looks sensitive: IP addresses, email addresses, keys, tokens, local paths. Put strings
specific to your own environment (lab hostnames, logins) in `.validate-local`, one regex per
line; that file is gitignored so it is never published. It also checks the release version (below).

## Releasing

A release is a version bump plus an annotated tag. **Bump the version on every release that
should reach users**: Claude Code keeps a plugin install on its cached copy until the `version`
string changes, so commits pushed without a bump never reach plugin users.

1. Pick the version (semver): PATCH for corrections, MINOR for new guidance or helper features,
   MAJOR for a change that breaks how people install or call the helpers.
2. Set it in **both** `.claude-plugin/plugin.json` and `.cursor-plugin/plugin.json`. Don't add a
   `version` to `.claude-plugin/marketplace.json`: Claude Code silently prefers `plugin.json`'s.
3. Add `## [X.Y.Z] - YYYY-MM-DD` at the top of `CHANGELOG.md`, saying what changed for users.
4. Check, commit, tag and push:

   ```bash
   python3 scripts/validate.py --tag vX.Y.Z
   git commit -am "Release vX.Y.Z"
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main vX.Y.Z
   ```

5. Publish the release notes from the changelog entry, with `gh release create vX.Y.Z --notes-file <entry>`
   or the GitHub web UI.

Never move or delete a published tag: people pin to it.
