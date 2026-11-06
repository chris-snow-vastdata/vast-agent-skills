# VAST Agent Skills

Skills that let an AI coding agent (Claude Code, Cursor, OpenAI Codex, and any other
[Agent Skills](https://agentskills.io) client) configure, operate and build on a
**VAST Data** cluster: views and protocols, tenants and networking, users and access,
data protection, monitoring, VAST Database, the VAST Event Broker and VAST DataEngine.

They are written for VAST customers: everything they use is public. That means the cluster's
own REST API and the API specs it serves, the [VAST knowledge base](https://kb.vastdata.com),
and public tools such as `vastpy`, `vastdb`, `vastde` and the Terraform provider.

**They work across VAST releases** because they don't hardcode the API. For every task the
agent:

1. reads the cluster's version (`vast_api.py version`);
2. reads the knowledge-base pages for that release (`vast_api.py kb search ... --version 5.5`);
3. checks exact endpoints, fields and allowed values in the specs the cluster itself serves
   (`vast_api.py spec search|show|model`);
4. lists what already exists, shows you the plan, and asks before changing anything.

## What's inside

One skill, [`vast`](skills/vast/SKILL.md). Its `SKILL.md` covers connecting, logging in, API
versions, finding endpoints and fields, the knowledge base and safe changes, and points the
agent to one guide per area, which it reads only when a task needs it:

| Area | Covers |
|---|---|
| [tenants-network](skills/vast/references/tenants-network.md) | Tenants, tenant admins, VIP pools, DNS, VLANs, BGP. |
| [views-protocols](skills/vast/references/views-protocols.md) | Views, view policies and security flavors, NFSv3/NFSv4, SMB, S3 buckets, quotas, QoS, block storage (NVMe/TCP), the Kubernetes CSI driver. |
| [identity-access](skills/vast/references/identity-access.md) | Local users and groups, AD/LDAP/NIS, S3 keys, identity and bucket policies, managers, roles and realms, encryption, certificates, auditing. |
| [data-protection](skills/vast/references/data-protection.md) | Snapshots, protection policies, replication and failover, clones, S3 versioning and object lock. |
| [monitoring](skills/vast/references/monitoring.md) | Health, capacity, performance metrics, alarms and events, notifications, support bundles, tasks. |
| [database](skills/vast/references/database.md) | VAST Database: prerequisites, schemas and tables, the `vastdb` SDK, Trino/Spark. |
| [event-broker](skills/vast/references/event-broker.md) | The Kafka-compatible VAST Event Broker: broker views, topics, clients. |
| [dataengine](skills/vast/references/dataengine.md) | VAST DataEngine: enabling it on a tenant, compute clusters, registries, event brokers, element and schedule triggers, functions, pipelines, secrets, logs and troubleshooting. |

Two helper scripts come with it: `scripts/vast_api.py` (discovery and safe API calls) and
`scripts/vast_monitor.py` (read-only health and metrics).

For writing DataEngine function code with the `vastde` CLI, VAST also publishes
[vast-data/data-engine-skills](https://github.com/vast-data/data-engine-skills); these skills
cover the cluster side and point to it.

## Requirements

- A VAST cluster you can reach over HTTPS, and a VMS login (a cluster or tenant admin, or an
  API token). The agent asks for these; it doesn't guess them.
- Python 3.8 or later for the helper script (standard library only, nothing to `pip install`).
- Optional, used where they fit: `vastpy` (`pip install vastpy`), `vastdb` (`pip install vastdb`),
  [`vastde`](https://github.com/vast-data/dataengine-cli/releases) (DataEngine CLI), `kubectl`.

## Installation

### Quick install without cloning

Download just the skill into the cross-agent folder (read by Codex, Cursor and others):

```bash
mkdir -p ~/.agents/skills && curl -fsSL https://github.com/chris-snow-vastdata/vast-agent-skills/archive/refs/heads/main.tar.gz \
  | tar -xz -C ~/.agents/skills --strip-components=2 vast-agent-skills-main/skills/vast
```

For Claude Code, run the same command with `~/.claude/skills` in place of `~/.agents/skills` (or
run it for both). To update, delete the `vast` folder and run it again.

Alternatively, the [`skills` CLI](https://github.com/vercel-labs/skills) installs into many agents at
once (it asks which; `-g` installs for your user rather than the current project):

```bash
npx skills add chris-snow-vastdata/vast-agent-skills -g
```

### From a clone (recommended if you want `git pull` updates)

```bash
git clone https://github.com/chris-snow-vastdata/vast-agent-skills.git
cd vast-agent-skills
```

### Every agent at once (macOS, Linux, WSL)

```bash
./install.sh
```

This links the skill into `~/.agents/skills/`, which Codex, Cursor and other clients read, and
into `~/.claude/skills/`, which Claude Code reads. Because they are symlinks, `git pull` updates
every agent. (It also removes links left by the earlier multi-skill layout.) Options:

| Command | Does |
|---|---|
| `./install.sh --project /path/to/repo` | Installs for one project only: `<repo>/.agents/skills` and `<repo>/.claude/skills`. Commit these to share the skills with your team. |
| `./install.sh --copy` | Copies instead of linking (Windows, or to pin a version). |
| `./install.sh --uninstall` | Removes what the script installed. Add `--project DIR` to remove a project install. |

### Claude Code

Either run `./install.sh` (above), or install the skills as a plugin from this repository:

```
/plugin marketplace add chris-snow-vastdata/vast-agent-skills
/plugin install vast-agent-skills@vast-agent-skills
```

Claude Code reads personal skills from `~/.claude/skills/` and project skills from `.claude/skills/`.
Skills are picked up in new sessions. To check, ask "what VAST skills do you have?"

A plugin install updates only when a new release changes the version: run
`/plugin marketplace update vast-agent-skills`, or turn on auto-update for the marketplace under
**Marketplaces** in `/plugin`.

### Pin a release

Releases are git tags (`v0.2.0`, ...); [CHANGELOG.md](CHANGELOG.md) says what each one changed.
To stay on one release instead of following `main`:

| Install path | Pinned form |
|---|---|
| Claude Code plugin | `/plugin marketplace add chris-snow-vastdata/vast-agent-skills#v0.2.0` |
| Quick install | use `archive/refs/tags/v0.2.0.tar.gz` and `vast-agent-skills-0.2.0/skills/vast` in the `curl` command above |
| From a clone | `git checkout v0.2.0 && ./install.sh --copy` (copies, so a later `git pull` doesn't move you) |

### Cursor

Run `./install.sh`. Cursor reads `~/.agents/skills/` and `~/.cursor/skills/` (user) and
`.agents/skills/`, `.cursor/skills/` and `.claude/skills/` (project). To install by hand, copy or link
`skills/vast` into any of those. The repository also includes a `.cursor-plugin/plugin.json`
manifest for Cursor's plugin system.

### OpenAI Codex

Run `./install.sh`. Codex reads `~/.agents/skills/` (user) and `.agents/skills/` in the
directory you start it from or the repository root (project). By hand:

```bash
mkdir -p ~/.agents/skills && cp -R skills/vast ~/.agents/skills/
```

Codex usually notices new skills without a restart; restart it if one doesn't appear.

### Other agents

Any client that supports the [Agent Skills](https://agentskills.io) format can use the
`skills/vast` folder as it is. Copy it into that client's skills directory; `~/.agents/skills/`
is the cross-client convention. For an agent without skills support, add `AGENTS.md` (in this
repository) to its instructions: it tells the agent where the skill is and when to read each part.

## Using them

Tell the agent which cluster to use. Keep the password out of the chat: export it in the
shell the agent runs commands in:

```bash
export VMS_ADDRESS=vms.example.com
export VMS_USER=admin VMS_PASSWORD='...'    # or: export VMS_TOKEN=<api token>
export VMS_CERT_FILE=/path/to/ca.pem        # or VMS_INSECURE=1 for a self-signed lab certificate
export VMS_TENANT_NAME=my-tenant            # for tenant admins and DataEngine work
```

Then just ask, for example:

- "Create an NFS export at /projects/ml for our build servers' subnet."
- "Which views are using the most capacity, and which clients are busiest right now?"
- "Schedule hourly snapshots of /prod with 7-day retention."
- "Give the analytics team their own tenant, VIP pool and tenant admin."
- "Set up DataEngine on our tenant and deploy a pipeline that runs my function when files land in /ingest."

Before every change the agent shows you the exact API requests and waits for your yes. The
helper's `call` command is a dry run unless it gets `--yes`.

You can also use the helper directly:

```bash
python3 skills/vast/scripts/vast_api.py --help
python3 skills/vast/scripts/vast_api.py version
python3 skills/vast/scripts/vast_api.py kb search 'snapshot' --version 5.5
python3 skills/vast/scripts/vast_api.py spec show /views/ post
```

## Versions

The skills find out the API from each cluster, so they are written to work on any release whose
VMS serves `/api/swagger.json` (and, for DataEngine, `/api/<version>/dataengine/openapi.json`).
Concrete examples are labelled with the release they were checked on, and each area guide
ends with a **Verified** line saying how it was tested. At present everything has been
checked against **VAST 5.5.3**: live calls that only read, the cluster's own specs, and the 5.5
knowledge base.
Reports from other releases are welcome.

## Contributing

See [AUTHORING.md](AUTHORING.md) for the format and the rules every guide follows.

## License

Apache License 2.0: see [LICENSE](LICENSE).
