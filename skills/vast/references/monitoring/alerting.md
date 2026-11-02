# Events, alarms and notifications (email, syslog, webhooks)

Checked against the VAST 5.5.3 VMS spec, the KB 5.5 pages named below, and live read-only calls.
On another release re-check every field with `scripts/vast_api.py spec model
EventDefinitionConfig` (and `EventDefinition`, `Alarm`, `Event`, `Webhook`).

## Contents
- [Model](#model)
- [Reading events and alarms](#reading-events-and-alarms)
- [Event definitions](#event-definitions)
- [Notification settings (email, syslog)](#notification-settings-email-syslog)
- [Webhooks](#webhooks)
- [SNMP](#snmp)
- [Changing things (needs a yes)](#changing-things-needs-a-yes)
- [Pitfalls](#pitfalls)

## Model

KB **Overview of Alarms and Events**, **Event Types**, **Managing Alarms and Events** (5.5).

- **Event definition** (`/eventdefinitions/`, ~440 on 5.5.3): what VMS watches. Fields:
  `name` (e.g. `CLUSTER_PHYSICAL_SPACE_IN_USE_PERCENT_MAJOR_THRESHOLD`), `object_type`
  (`Cluster`, `CNode`, `DNode`, `SSD`, `NIC`, `Quota`, `License`, `Certificate`, `VIPPool`...),
  `property`, `event_type`, `severity`, `trigger_on`/`trigger_off` (e.g. `["ge", 90]`),
  `enabled`, `alarm_only`, `disable_actions`, `email_recipients`, `webhooks` (ids), `user_action`
  (the recommended fix text) *(5.5.3 spec + live)*.
- `event_type` values seen on 5.5.3: `OBJECT_MODIFIED`, `THRESHOLD`, `RATE`,
  `PERSISTENT_THRESHOLD`, `OBJECT_CREATED`, `OBJECT_DELETED`, `NOTIFICATION`, `SECURITY`,
  `GENERAL`, plus `HW_VALIDATION` on events.
- **Event** (`/events/`): a logged occurrence. Kept until the log reaches 1.5 million events
  or 30 days (KB). Fields: `timestamp`, `severity`, `event_type`, `event_origin`
  (`USER`, `CLUSTER`, `MANAGEMENT`, `SECURITY`), `object_type`, `object_name`, `event_message`.
- **Alarm** (`/alarms/`): an event whose definition has a severity raises an alarm; it clears
  itself when the condition clears. Severities: `MINOR`, `MAJOR`, `CRITICAL` (events can also be
  `INFO`, which raises no alarm). Fields: `severity`, `alarm_message`, `object_type`,
  `object_name`, `object_id`, `event_name`, `timestamp`, `last_updated`, `acknowledged`.
- Lower-level hardware alarms (an SSD, a fan) are suppressed when the containing CNode/DNode
  alarms; similar alarms on several objects are aggregated into one entry (KB).
- **Notification actions** (`/eventdefinitionconfigs/`, a single object): the global SMTP server,
  default email recipients, syslog destination, severity names for webhooks, and a global
  `disable_actions` switch. Event definitions can override recipients and webhooks.

## Reading events and alarms

Filters that work on 5.5.3 (from the KB API reference and tried live):

```bash
vast_api.py get alarms                                   # active alarms (all)
vast_api.py get alarms severity=CRITICAL
vast_api.py get alarms object_type=CNode
vast_api.py get alarms alarm_message__contains=capacity
vast_api.py get events page_size=50                       # newest first, paginated
vast_api.py get events severity=MAJOR timestamp__gte=2026-01-15T00:00:00Z page_size=100
vast_api.py get events event_type=SECURITY page_size=50   # logins, failed logins
vast_api.py get events object_type=Cluster page_size=50
```

- `/events/` paginates (it has `count`, `next`): follow `next`, or narrow with `timestamp__gte`/`timestamp__lte`.
- **Unknown filter names are ignored silently**: `events?start_time=...` returned all events
  on 5.5.3. Check that `count` actually dropped; use `timestamp__gte`.
- An event's alarm links back via `event` (URL) and `event_definition` (URL or null).
- Prometheus: `/api/prometheusmetrics/alarms` gives the active alarms as series (see metrics.md).
- VAST CLI: `alarm list`, `alarm show`, `event list`, `event show` (KB 5.5 CLI reference).

## Event definitions

```bash
vast_api.py get eventdefinitions object_type=Cluster event_type=THRESHOLD fields=id,name,property,severity,trigger_on,enabled
vast_api.py get eventdefinitions name__contains=SPACE fields=id,name,severity,trigger_on
vast_api.py get eventdefinitions property=state fields=id,name,object_type,severity
```

(The KB API reference lists `metadata__property`; on 5.5.3 that filter was ignored and `property=` worked.)

Example (5.5.3 defaults): cluster `Capacity,physical_space_in_use_percent` raises MINOR at
`["ge", 85]`, MAJOR at `["ge", 90]`, CRITICAL at `["ge", 95]`. Thresholds may differ on the
user's cluster; read them.

Fields on a definition (UI terms in brackets, KB **Managing Alarms and Events**):
- `severity`, `trigger_on` / `trigger_off` (operator `gt`/`ge`/`lt`/`le` and value; Rate
  events also have a time frame such as `1h`).
- `alarm_only` (Alarm only): default on: actions fire only for alarm-raising events. Off: every
  event of the definition (e.g. every CNode state change) triggers its actions.
- `disable_actions`, `email_recipients` (overrides the default list), `webhooks` (ids; if none
  are attached, **all enabled webhooks fire** for that alarm).
- `enabled` (Activate/Deactivate): a disabled definition performs no notification actions.

## Notification settings (email, syslog)

Read them (no secrets are needed; don't print `smtp_password` back to the user):

```bash
vast_api.py get eventdefinitionconfigs
```

`EventDefinitionConfig` fields *(5.5.3 spec)*:

| Area | Fields |
|---|---|
| SMTP (global, needed for any email) | `smtp_host`, `smtp_port` (25 or 587 commonly), `smtp_user`, `smtp_password`, `smtp_use_tls`, `smtp_certificate_id`, `smtp_bind_vms_ip` |
| Email | `email_sender`, `email_subject` (blank = alarm text as subject), `email_recipients` (list) |
| Syslog | `syslog_host`, `syslog_port` (default 514), `syslog_protocol` (`udp` or `tcp`), `syslog_vms_audit`, `syslog_secure_audit`, `syslog_shell_audit`, `syslog_ipmi_audit`, `audit_logs_retention` (days) |
| Webhook severity names | `critical_value`, `major_value`, `minor_value`, `info_value` (sent as `vastdata_mapped_severity`) |
| Global | `disable_actions` (maintenance switch), quota-email settings `quota_email_*` |

Syslog lines look like (KB **Sending Alarms to a Syslog Server**):
`<ts> <host> vast_event AUDIT - VMS - Manager: admin, create monitor`.
The syslog server must accept the chosen protocol and port, and VMS must be able to reach it.

Web UI: Settings → Notifications (SMTP Setup, Email Setup, Webhook Setup, Syslog Setup).
VAST CLI: `eventdefinitionconfig modify --syslog-host <ip> --syslog-port 514 --syslog-protocol udp --enable-actions` (KB example).

## Webhooks

KB **Managing Webhooks** (5.5). Object `/webhooks/` *(5.5.3 spec)*: `name`, `url` (required),
`method` (`GET|POST|PUT|PATCH|DELETE`), `headers` (object), `data` (a JSON string template),
`enabled`, `certificate_id` (a certificate of `cert_type` `WEBHOOK`, for TLS/mTLS).

Template variables (KB): `${vastdata_event_name}`, `${vastdata_severity}`,
`${vastdata_mapped_severity}`, `${vastdata_cluster_name}`, `${vastdata_object_type}`,
`${vastdata_object_id}`, `${vastdata_object_name}`, `${vastdata_event_type}`,
`${vastdata_property}`, `${vastdata_event_origin}`, `${vastdata_timestamp}`,
`${vastdata_timestamp_unix}`, `${vastdata_timestamp_iso_8601}`.

A webhook request for a chat or incident tool, to show the user before sending (dry run first):

```bash
vast_api.py call POST /webhooks/ --data '{
  "name": "ops-alerts",
  "url": "https://hooks.example.com/vast",
  "method": "POST",
  "headers": {"Content-Type": "application/json"},
  "data": "{\"text\": \"VAST ${vastdata_severity}: ${vastdata_event_name} on ${vastdata_object_name} (${vastdata_cluster_name}) at ${vastdata_timestamp_iso_8601}\"}",
  "enabled": true}'
```

Then either attach it to specific definitions (`PATCH /eventdefinitions/<id>/` with
`{"webhooks": [<id>]}`) or rely on the rule that alarms whose definition has no webhook attached
go to all enabled webhooks. A webhook attached to a definition can't be disabled (KB).

## SNMP

Neither the 5.5.3 VMS spec nor the 5.5 KB has SNMP trap or SNMP-agent settings
(`vast_api.py spec search snmp` finds nothing). For an SNMP-based NMS, use one of the supported
paths: syslog forwarding, a webhook to the NMS's HTTP intake, or Prometheus
(`/api/prometheusmetrics/alarms`). On a newer release, run `spec search snmp` and
`kb search snmp` again before saying it's unsupported.

## Changing things (needs a yes)

All of these change the cluster. Show the exact request (helper `call` without `--yes`), get a yes:

| Change | Request (5.5.3 spec) | Impact |
|---|---|---|
| SMTP / email / syslog | `PATCH /eventdefinitionconfigs/<id>/` | Starts or stops notifications cluster-wide |
| Send a test notification with the settings | `PATCH /eventdefinitionconfigs/<id>/test/` | Sends a real email/syslog message |
| Maintenance mute | `PATCH /eventdefinitionconfigs/<id>/` `{"disable_actions": true}` | **Silences all notification actions** until set back to false. Remind the user to re-enable. |
| Tune a threshold / recipients / webhooks | `PATCH /eventdefinitions/<id>/` | Alarm behaviour changes; `reset` (`PATCH /eventdefinitions/<id>/reset/`) restores defaults |
| Test one definition | `PATCH /eventdefinitions/<id>/test/` | Fires that definition's actions |
| Webhook create / modify / delete | `POST /webhooks/`, `PATCH|DELETE /webhooks/<id>/` | |
| Acknowledge an alarm | `PATCH /alarms/<id>/` `{"acknowledged": true}` | Hides it from the view of non-root users; the condition is not fixed |
| Clear all alarms | `PATCH /alarms/clear/` | **Removes every current alarm** (KB "alarm clear"). Rarely right: alarms clear themselves when fixed. Warn. |
| Delete alarm(s) | `DELETE /alarms/<id>/`, `DELETE /alarms/bulk/` | Loses the record. Warn. |

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| No emails at all | `smtp_host` empty, or `disable_actions` true, or no recipients (global and per definition) | Read `eventdefinitionconfigs`; test with `.../test/` after a yes |
| Emails for some alarms only | That definition has its own `email_recipients`, or `disable_actions`/`enabled=false` on it | Read the definition |
| Webhook fires for every alarm | No webhook attached to the definitions → all enabled webhooks fire | Attach webhooks to the definitions you want |
| Webhook fires on recovery too | `alarm_only` false on that definition | Set `alarm_only` back to true (affects all its actions) |
| Can't disable a webhook | It is attached to event definitions (KB) | Detach first |
| Filter seems ignored | Unknown filter names are dropped silently | Check `count`; use names from the KB API reference |
| An expected SSD alarm is missing | Suppressed under the CNode/DNode alarm (KB) | Look at the parent object's alarm |
