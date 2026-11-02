#!/usr/bin/env python3
"""vast_monitor.py: read-only VAST cluster health report and metrics queries.

Standard library only (Python 3.8+). Every request is a GET; nothing is changed.
Connection: the same environment variables as vastpy-cli and vast_api.py (same folder)
  VMS_ADDRESS                VMS host or IP (the Web UI address)
  VMS_USER / VMS_PASSWORD    a VMS manager login, or VMS_TOKEN (API token, VAST 5.3+)
  VMS_TENANT_NAME            optional tenant context (tenant admins)
  VMS_CERT_FILE              CA bundle; VMS_INSECURE=1 skips certificate checks
  VMS_API_VERSION            default: latest

Commands:
  health [--json]                 one-page health report: cluster state/RAID/capacity, VMS,
                                  nodes and drives not ACTIVE/HEALTHY, active alarms, failed tasks
  query OBJECT_TYPE --prop FQN [--prop FQN ...] [--time-frame 1h | --from T --to T]
        [--granularity seconds|minutes|hours|days] [--aggregation avg|max|...] [--ids 1,2]
                                  /monitors/ad_hoc_query/ with repeated prop_list (as the API expects)
  monitor ID [--time-frame ...]   run a saved/predefined monitor (/monitors/<id>/query/)
  metrics [REGEX] [--class NAME]  search the metric catalog (/metrics/) for names (fqn) and units
  top [--kind user|client|view|vip|vippool|cnode|volume] [--by iops|bw|md_iops|latency]
                                  current top talkers from /monitors/topn/

Field names differ between releases: the report prints what the cluster returns and skips
fields it does not have. Check names with: vast_api.py spec model Cluster
"""
import argparse
import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


class VMS:
    def __init__(self):
        self.address = os.environ.get("VMS_ADDRESS")
        if not self.address:
            sys.exit("set VMS_ADDRESS (and VMS_USER/VMS_PASSWORD or VMS_TOKEN)")
        self.version = os.environ.get("VMS_API_VERSION", "latest")
        self.headers = {"Accept": "application/json"}
        token = os.environ.get("VMS_TOKEN")
        if token:
            self.headers["Authorization"] = "Api-Token " + token
        else:
            user, pw = os.environ.get("VMS_USER"), os.environ.get("VMS_PASSWORD")
            if not (user and pw):
                sys.exit("set VMS_USER and VMS_PASSWORD, or VMS_TOKEN")
            self.headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
        if os.environ.get("VMS_TENANT_NAME"):
            self.headers["X-Tenant-Name"] = os.environ["VMS_TENANT_NAME"]
        if os.environ.get("VMS_INSECURE") == "1":
            self.ctx = ssl._create_unverified_context()
        else:
            self.ctx = ssl.create_default_context(cafile=os.environ.get("VMS_CERT_FILE") or None)

    def get(self, path, params=None):
        """GET /api/<version>/<path>/; params is a list of (key, value) so keys can repeat."""
        path = path.strip("/")
        url = f"https://{self.address}/api/{self.version}/{path}/"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers, method="GET")
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as r:
                body = r.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"GET {url} -> {e.code}: {e.read().decode()[:400]}")
        try:
            return json.loads(body)
        except ValueError:
            return body

    def get_all(self, path, params=None):
        """All results of a list, following pagination when the endpoint paginates."""
        params = list(params or []) + [("page_size", 500)]
        data = self.get(path, params)
        if isinstance(data, list):
            return data
        out = list(data.get("results", []))
        page = 1
        while data.get("next"):
            page += 1
            data = self.get(path, params + [("page", page)])
            out.extend(data.get("results", []))
        return out

    def try_get_all(self, path, params=None):
        try:
            return self.get_all(path, params), None
        except Exception as e:  # endpoint missing on this release, or no permission
            return [], str(e)


OK_STATES = {"ACTIVE", "HEALTHY", "ONLINE", "UP", "CLUSTERED", "NONE"}


def health(vms, as_json=False):
    rep = {"cluster": {}, "vms": [], "not_ok": {}, "alarms": [], "tasks_failed": [], "errors": {}}
    clusters, err = vms.try_get_all("clusters")
    if err:
        rep["errors"]["clusters"] = err
    keys = ["name", "sw_version", "build", "state", "leader_state", "ssd_raid_state", "nvram_raid_state",
            "memory_raid_state", "raid_rebuild_progress", "remaining_stripes_health", "md_usage_health",
            "upgrade_state", "upgrade_phase", "expansion_state", "burst_mode_state",
            "physical_space_in_use_percent", "logical_space_in_use_percent", "usable_capacity_tb",
            "free_usable_capacity_tb", "logical_space_tb", "logical_space_in_use_tb", "drr_text",
            "used_handles_percent", "iops", "bw_mb", "latency_ms"]
    for c in clusters:
        rep["cluster"] = {k: c[k] for k in keys if k in c}
    vmss, err = vms.try_get_all("vms")
    rep["vms"] = [{k: v.get(k) for k in ("name", "state", "sw_version")} for v in vmss]
    for kind in ("cnodes", "dnodes", "cboxes", "dboxes", "eboxes", "dtrays", "ssds", "nvrams",
                 "nics", "nicports", "psus", "fans"):
        items, err = vms.try_get_all(kind)
        if err:
            rep["errors"][kind] = err
            continue
        bad = []
        for it in items:
            st = it.get("display_state") or it.get("state")
            if st is not None and str(st).upper() not in OK_STATES or it.get("enabled") is False:
                bad.append({k: it.get(k) for k in ("id", "name", "title", "state", "display_state", "enabled")
                            if it.get(k) not in (None, "")})
        rep["not_ok"][kind] = {"total": len(items), "not_ok": bad}
    alarms, err = vms.try_get_all("alarms")
    if err:
        rep["errors"]["alarms"] = err
    rep["alarms"] = [{k: a.get(k) for k in ("id", "severity", "object_type", "object_name", "alarm_message",
                                             "timestamp", "acknowledged")} for a in alarms]
    tasks, err = vms.try_get_all("vtasks", [("state", "FAILED")])
    if err:
        rep["errors"]["vtasks"] = err
    rep["tasks_failed"] = [{k: t.get(k) for k in ("id", "name", "state", "start_time", "end_time")} for t in tasks]
    if as_json:
        print(json.dumps(rep, indent=2, default=str))
        return
    print("== Cluster")
    for k, v in rep["cluster"].items():
        print(f"  {k}: {v}")
    print("== VMS")
    for v in rep["vms"]:
        print(f"  {v}")
    print("== Components (state not ACTIVE/HEALTHY, or disabled)")
    for kind, r in rep["not_ok"].items():
        if r["total"]:
            print(f"  {kind}: {r['total']} total, {len(r['not_ok'])} not ok")
            for b in r["not_ok"]:
                print(f"    {b}")
    sev = {}
    for a in rep["alarms"]:
        sev[a["severity"]] = sev.get(a["severity"], 0) + 1
    print(f"== Active alarms: {len(rep['alarms'])} {sev}")
    for a in sorted(rep["alarms"], key=lambda a: {"CRITICAL": 0, "MAJOR": 1, "MINOR": 2}.get(a["severity"], 3)):
        print(f"  [{a['severity']}] {a['object_type']} {a['object_name']}: {a['alarm_message']} ({a['timestamp']})"
              + (" ack" if a.get("acknowledged") else ""))
    print(f"== Failed VMS tasks: {len(rep['tasks_failed'])}")
    for t in rep["tasks_failed"]:
        print(f"  {t}")
    for k, e in rep["errors"].items():
        print(f"  (could not read {k}: {e[:160]})")


def print_series(data):
    if not isinstance(data, dict) or "data" not in data:
        print(json.dumps(data, indent=2))
        return
    cols = data["prop_list"]  # the response's own column order; it may differ from the request
    print("\t".join(cols))
    for row in data["data"]:
        print("\t".join("" if v is None else str(v) for v in row))


def time_params(a):
    p = []
    if a.time_frame:
        p.append(("time_frame", a.time_frame))
    if a.from_time:
        p.append(("from_time", a.from_time))
    if a.to_time:
        p.append(("to_time", a.to_time))
    if a.granularity:
        p.append(("granularity", a.granularity))
    if a.aggregation:
        p.append(("aggregation", a.aggregation))
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("health")
    h.add_argument("--json", action="store_true")
    for name in ("query", "monitor"):
        q = sub.add_parser(name)
        q.add_argument("target", help="object type (query) or monitor id (monitor)")
        if name == "query":
            q.add_argument("--prop", action="append", required=True, help="metric fqn, repeatable")
            q.add_argument("--ids", help="comma-separated object ids")
        q.add_argument("--time-frame", default=None, help="e.g. 10m, 2h, 7D")
        q.add_argument("--from", dest="from_time")
        q.add_argument("--to", dest="to_time")
        q.add_argument("--granularity")
        q.add_argument("--aggregation")
        q.add_argument("--json", action="store_true")
    m = sub.add_parser("metrics")
    m.add_argument("regex", nargs="?", default=".")
    m.add_argument("--class", dest="cls")
    t = sub.add_parser("top")
    t.add_argument("--kind", default="user")
    t.add_argument("--by", default="iops")
    a = ap.parse_args()
    vms = VMS()
    if a.cmd == "health":
        health(vms, a.json)
    elif a.cmd == "query":
        p = [("object_type", a.target)] + [("prop_list", x) for x in a.prop]
        if a.ids:
            p += [("object_ids", i.strip()) for i in a.ids.split(",")]
        if not (a.time_frame or a.from_time):
            p.append(("time_frame", "10m"))
        d = vms.get("monitors/ad_hoc_query", p + time_params(a))
        print(json.dumps(d, indent=2)) if a.json else print_series(d)
    elif a.cmd == "monitor":
        d = vms.get(f"monitors/{a.target}/query", time_params(a))
        print(json.dumps(d, indent=2)) if a.json else print_series(d)
    elif a.cmd == "metrics":
        params = [("class_name", a.cls)] if a.cls else None
        rx = re.compile(a.regex, re.I)
        for x in vms.get_all("metrics", params):
            line = f"{x.get('fqn')}\t{','.join(x.get('object_types') or [])}\t{x.get('units')}\t{x.get('title')}"
            if rx.search(line):
                print(line)
    elif a.cmd == "top":
        d = vms.get("monitors/topn")
        print(f"sample: {d.get('timestamp')}")
        rows = (d.get("data", {}).get(a.kind) or {}).get(a.by) or []
        if not rows:
            print(f"no data for kind={a.kind} by={a.by}; kinds: {', '.join(d.get('data', {}))}")
        for r in rows:
            print(f"  {r.get('total')}\t(read {r.get('read')}, write {r.get('write')})\t{r.get('title')}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        sys.exit(str(e))
