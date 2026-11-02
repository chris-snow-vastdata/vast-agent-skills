#!/usr/bin/env python3
"""vast_api.py: read a VAST cluster's own API specs and call its REST API safely.

Standard library only (Python 3.8+), so it runs anywhere an agent can run Python.
Works across VAST versions: it never assumes an endpoint or field exists, it reads
them from the specs the cluster serves (VMS: Swagger 2.0 at /api/swagger.json;
DataEngine: OpenAPI 3 at /api/latest/dataengine/openapi.json, tenant-scoped).

Connection (environment variables, the same names vastpy-cli uses):
  VMS_ADDRESS       VMS host or IP (required)
  VMS_USER / VMS_PASSWORD   a VMS manager login, or
  VMS_TOKEN         an API token (VAST 5.3+)
  VMS_TENANT_NAME   tenant context (needed for the DataEngine API)
  VMS_CERT_FILE     CA bundle for the VMS certificate; VMS_INSECURE=1 skips verification
  VMS_API_VERSION   API version path segment (default: latest)

Commands (kb needs no cluster; the rest need VMS_ADDRESS and a login):
  kb search REGEX [--version 5.5]  search the VAST knowledge base index (kb.vastdata.com/llms.txt)
  kb get URL                       print a KB page as markdown
  version                          cluster name, version, build
  spec fetch [--dataengine]        download and cache the VMS (or DataEngine) spec for this cluster's build
  spec paths [REGEX] [--dataengine]        list endpoints (and methods)
  spec show PATH [METHOD] [--dataengine]   parameters and request body of one endpoint
  spec model NAME [--dataengine]           a schema: fields, types, enums, descriptions
  spec search TERM [--dataengine]          paths, schemas, fields and enum values matching TERM
  get PATH [key=value ...]          GET (read-only, safe); repeat a key to send it several times
  de-get PATH [key=value ...]       GET on the DataEngine API (needs VMS_TENANT_NAME)
  call METHOD PATH [--data JSON | --file F] [--dataengine] [--yes]
                                    POST/PATCH/PUT/DELETE. Without --yes it only prints the request.

Examples:
  vast_api.py version
  vast_api.py spec search delegation
  vast_api.py spec show /views/ post
  vast_api.py get views path=/data
  vast_api.py call PATCH /views/12/ --data '{"allowed_delegations": "NONE"}'          # dry run
  vast_api.py call PATCH /views/12/ --data '{"allowed_delegations": "NONE"}' --yes    # do it
"""

import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DE_PREFIX = "dataengine"


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# ------------------------------------------------------------------ connection

class Conn:
    def __init__(self):
        self.address = os.environ.get("VMS_ADDRESS") or die("set VMS_ADDRESS (the VMS host or IP)")
        self.address = re.sub(r"^https?://", "", self.address).rstrip("/")
        self.user, self.password = os.environ.get("VMS_USER"), os.environ.get("VMS_PASSWORD")
        self.api_token = os.environ.get("VMS_TOKEN")
        self.tenant = os.environ.get("VMS_TENANT_NAME")
        self.version = os.environ.get("VMS_API_VERSION", "latest")
        if not self.api_token and not (self.user and self.password):
            die("set VMS_USER and VMS_PASSWORD, or VMS_TOKEN")
        self.ctx = ssl.create_default_context(cafile=os.environ.get("VMS_CERT_FILE") or None)
        if os.environ.get("VMS_INSECURE") in ("1", "true", "yes"):
            self.ctx.check_hostname, self.ctx.verify_mode = False, ssl.CERT_NONE
        self._jwt = None

    def _raw(self, method, url, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        h = {"Accept": "application/json", **(headers or {})}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except urllib.error.URLError as e:
            die(f"cannot reach https://{self.address}: {e.reason}")

    def jwt(self):
        """A session JWT for the user (POST /api/token/). Tenant scope comes from X-Tenant-Name."""
        if self._jwt is None:
            form = urllib.parse.urlencode({"username": self.user, "password": self.password}).encode()
            req = urllib.request.Request(f"https://{self.address}/api/token/", data=form, method="POST")
            try:
                with urllib.request.urlopen(req, context=self.ctx, timeout=60) as r:
                    self._jwt = json.loads(r.read())["access"]
            except urllib.error.HTTPError as e:
                die(f"login failed: HTTP {e.code} {e.read()[:300]!r}")
        return self._jwt

    def headers(self, dataengine=False, tenant=True):
        h = {}
        scoped = bool(self.tenant) and tenant
        if self.api_token:
            h["Authorization"] = f"Api-Token {self.api_token}"
        elif dataengine or scoped:
            # Basic auth plus X-Tenant-Name is rejected; a JWT plus X-Tenant-Name works,
            # including for the cluster admin acting in a tenant.
            h["Authorization"] = f"Bearer {self.jwt()}"
        else:
            h["Authorization"] = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        if scoped:
            h["X-Tenant-Name"] = self.tenant
        elif dataengine:
            die("the DataEngine API is tenant-scoped: set VMS_TENANT_NAME")
        return h

    def url(self, path, dataengine=False, params=None):
        path = path.lstrip("/")
        if path.startswith("api/"):
            path = path[4:]
        base = f"https://{self.address}/api/{self.version}/"
        if dataengine and not path.startswith(DE_PREFIX):
            path = f"{DE_PREFIX}/{path}"
        u = base + path
        if params:
            u += "?" + urllib.parse.urlencode(params)
        return u

    def request(self, method, path, body=None, dataengine=False, params=None, tenant=True):
        status, raw = self._raw(method, self.url(path, dataengine, params), body, self.headers(dataengine, tenant))
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw.decode(errors="replace")
        return status, payload


# ------------------------------------------------------------------ specs

def cache_dir(conn, build):
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "vast-skills"
    d = root / re.sub(r"[^A-Za-z0-9_.-]", "_", conn.address) / re.sub(r"[^A-Za-z0-9_.-]", "_", build)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cluster_version(conn):
    st, res = conn.request("GET", "clusters/", tenant=False)
    if st in (401, 403) and conn.tenant:      # a tenant-only login
        st, res = conn.request("GET", "clusters/")
    if st != 200:
        die(f"GET /clusters/ -> HTTP {st}: {str(res)[:300]}")
    rows = res.get("results", res) if isinstance(res, dict) else res
    c = rows[0] if rows else {}
    return {"name": c.get("name"), "sw_version": c.get("sw_version"), "build": c.get("build"),
            "psnt": c.get("psnt"), "state": c.get("state")}


def spec_file(conn, dataengine, fetch=False):
    """The cached spec for this cluster's build. The VMS spec is fetched without tenant scope
    (a tenant-scoped login sees a much smaller spec, cached separately as vms@<tenant>.json)."""
    build = cluster_version(conn).get("build") or "unknown"
    d = cache_dir(conn, build)
    if dataengine:
        f = d / "dataengine.json"
    else:
        f = d / "vms.json"
    if fetch or not f.exists():
        path = "dataengine/openapi.json" if dataengine else "swagger.json"
        st, res = conn.request("GET", path, dataengine=dataengine, tenant=dataengine)
        if not dataengine and st in (401, 403) and conn.tenant:
            f = d / f"vms@{conn.tenant}.json"
            st, res = conn.request("GET", path)
        if st != 200 or not isinstance(res, dict):
            die(f"GET /api/{conn.version}/{path} -> HTTP {st}: {str(res)[:300]}")
        f.write_text(json.dumps(res))
    return f


class Spec:
    def __init__(self, doc):
        self.doc = doc
        self.v3 = "openapi" in doc
        self.schemas = (doc.get("components", {}).get("schemas", {}) if self.v3 else doc.get("definitions", {}))

    def resolve(self, s, depth=0):
        if not isinstance(s, dict) or depth > 8:
            return s
        if "$ref" in s:
            name = s["$ref"].split("/")[-1]
            return {"$schema_name": name, **self.resolve(self.schemas.get(name, {}), depth + 1)}
        for key in ("allOf", "anyOf", "oneOf"):
            if key in s:
                parts = [self.resolve(p, depth + 1) for p in s[key]]
                if key == "allOf":
                    merged = {"type": "object", "properties": {}, "required": []}
                    for p in parts:
                        merged["properties"].update(p.get("properties", {}))
                        merged["required"] += p.get("required", [])
                    return merged
                non_null = [p for p in parts if p.get("type") != "null"]
                if len(non_null) == 1:
                    return non_null[0]
                return {key: parts}
        return s

    def describe(self, s, depth=0):
        s = self.resolve(s)
        t = s.get("type") or ("ref " + s.get("$schema_name", "") if s.get("$schema_name") else "")
        if t == "array":
            return f"array of {self.describe(s.get('items', {}), depth + 1)}"
        bits = [t or "any"]
        if s.get("$schema_name") and t != "ref " + s["$schema_name"]:
            bits.append(f"<{s['$schema_name']}>")
        if "enum" in s:
            bits.append("one of " + "|".join(map(str, s["enum"])))
        for k in ("format", "maxLength", "minimum", "maximum", "default"):
            if k in s:
                bits.append(f"{k}={s[k]}")
        if any(k in s for k in ("anyOf", "oneOf")):
            bits.append(" or ".join(self.describe(p, depth + 1) for p in (s.get("anyOf") or s.get("oneOf"))))
        return " ".join(str(b) for b in bits)

    def fields(self, s):
        s = self.resolve(s)
        req = set(s.get("required", []))
        out = []
        for name, p in sorted(s.get("properties", {}).items()):
            p_r = self.resolve(p)
            desc = (p_r.get("description") or p.get("description") or p_r.get("title") or "").strip()
            out.append((name, name in req, self.describe(p), " ".join(desc.split())[:160]))
        return out


def load_spec(conn, dataengine):
    return Spec(json.loads(spec_file(conn, dataengine).read_text()))


def print_fields(spec, schema, indent="  "):
    rows = spec.fields(schema)
    if not rows:
        print(f"{indent}{spec.describe(schema)}")
    for name, req, typ, desc in rows:
        print(f"{indent}{name}{' (required)' if req else ''}: {typ}" + (f"  - {desc}" if desc else ""))


def cmd_spec(conn, args):
    de = "--dataengine" in args
    args = [a for a in args if a != "--dataengine"]
    if not args:
        die("spec fetch|paths|show|model|search")
    sub, rest = args[0], args[1:]
    if sub == "fetch":
        for d in ([True] if de else [False]):
            f = spec_file(conn, d, fetch=True)
            doc = json.loads(f.read_text())
            print(f"{'dataengine' if d else 'vms'}: {len(doc.get('paths', {}))} paths -> {f}")
        return
    spec = load_spec(conn, de)
    paths = spec.doc.get("paths", {})
    methods = ("get", "post", "put", "patch", "delete")
    if sub == "paths":
        rx = re.compile(rest[0], re.I) if rest else None
        for p in sorted(paths):
            if rx is None or rx.search(p):
                print(f"{p}  [{' '.join(m.upper() for m in methods if m in paths[p])}]")
    elif sub == "show":
        if not rest:
            die("spec show PATH [METHOD]")
        p = rest[0] if rest[0].startswith("/") else "/" + rest[0]
        if p not in paths:
            alt = [k for k in paths if k.rstrip("/") == p.rstrip("/")]
            p = alt[0] if alt else die(f"{p} not in this cluster's spec (try: spec paths REGEX)")
        want = [rest[1].lower()] if len(rest) > 1 else [m for m in methods if m in paths[p]]
        for m in want:
            op = paths[p].get(m) or die(f"{m.upper()} not allowed on {p}")
            print(f"{m.upper()} {p}  {op.get('summary') or ''}".rstrip())
            if op.get("description"):
                print("  " + " ".join(op["description"].split())[:600])
            for prm in op.get("parameters", []) + paths[p].get("parameters", []):
                prm = spec.resolve(prm)
                if prm.get("in") == "body":
                    print("  body:")
                    print_fields(spec, prm.get("schema", {}), "    ")
                else:
                    typ = spec.describe(prm.get("schema", prm))
                    print(f"  {prm.get('in')} {prm.get('name')}{' (required)' if prm.get('required') else ''}: {typ}"
                          + (f"  - {' '.join((prm.get('description') or '').split())[:120]}" if prm.get("description") else ""))
            body = op.get("requestBody", {}).get("content", {})
            for ctype, c in body.items():
                print(f"  body ({ctype}):")
                print_fields(spec, c.get("schema", {}), "    ")
            print()
    elif sub == "model":
        if not rest:
            die("spec model NAME")
        names = [n for n in spec.schemas if n.lower() == rest[0].lower()] or \
                [n for n in spec.schemas if rest[0].lower() in n.lower()]
        if not names:
            die(f"no schema like {rest[0]!r}")
        for n in names[:5]:
            s = spec.schemas[n]
            print(f"{n}" + (f": {' '.join(s.get('description', '').split())[:300]}" if s.get("description") else ""))
            print_fields(spec, s)
            print()
        if len(names) > 5:
            print(f"... and {len(names) - 5} more: {', '.join(names[5:20])}")
    elif sub == "search":
        if not rest:
            die("spec search TERM")
        rx = re.compile(rest[0], re.I)
        print("paths:")
        for p in sorted(paths):
            ops = paths[p]
            text = p + " " + " ".join(str(ops[m].get("summary", "")) + str(ops[m].get("description", ""))
                                      for m in methods if m in ops)
            if rx.search(text):
                print(f"  {p}  [{' '.join(m.upper() for m in methods if m in ops)}]")
        print("schemas and fields:")
        for n, s in sorted(spec.schemas.items()):
            if rx.search(n):
                print(f"  schema {n}")
            for f, p in (spec.resolve(s).get("properties") or {}).items():
                pr = spec.resolve(p)
                blob = " ".join([f, str(pr.get("description", "")), str(p.get("description", "")),
                                 " ".join(map(str, pr.get("enum", [])))])
                if rx.search(blob):
                    print(f"  {n}.{f}: {spec.describe(p)}")
    else:
        die(f"unknown spec command {sub}")


def kv(args):
    """key=value arguments as (key, value) pairs; a key may repeat (e.g. prop_list=a prop_list=b)."""
    out = []
    for a in args:
        if "=" not in a:
            die(f"expected key=value, got {a!r}")
        out.append(tuple(a.split("=", 1)))
    return out


def show(status, payload):
    print(json.dumps(payload, indent=2) if not isinstance(payload, str) else payload)
    if status >= 400:
        print(f"HTTP {status}", file=sys.stderr)
        sys.exit(1)


KB_INDEX = "https://kb.vastdata.com/llms.txt"


def kb_fetch(url):
    if not url.startswith("http"):
        url = "https://kb.vastdata.com/" + url.lstrip("/")
    if "kb.vastdata.com" in url and not url.split("#")[0].endswith((".md", ".txt")):
        url = url.split("#")[0].rstrip("/") + ".md"
    req = urllib.request.Request(url, headers={"User-Agent": "vast-skills"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        die(f"cannot fetch {url}: {e}")


def kb_version_of(url):
    """The release a KB page is for, from its slug suffix (-55, -55-1, -534, ...), or '' if unversioned."""
    slug = url.rsplit("/", 1)[-1].removesuffix(".md") if hasattr(str, "removesuffix") else url.rsplit("/", 1)[-1][:-3]
    m = re.search(r"-(5\d)(\d?)(?:-\d+)?$", slug)
    if not m:
        return "API 5.5" if "/api-5-5/" in url else ""
    major_minor = f"{m.group(1)[0]}.{m.group(1)[1]}"
    return major_minor + (f".{m.group(2)}" if m.group(2) else "")


def cmd_kb(args):
    if not args:
        die("kb search REGEX [--version X.Y] | kb get URL")
    if args[0] == "get" and len(args) > 1:
        text = kb_fetch(args[1])
        text = re.sub(r"(?s)^---.*?---\s*", "", text, count=1)   # front matter
        text = re.sub(r"(?m)^> .*\n?", "", text)                 # the index banner
        print(text.strip())
        return
    if args[0] != "search" or len(args) < 2:
        die("kb search REGEX [--version X.Y] | kb get URL")
    want = args[args.index("--version") + 1] if "--version" in args else None
    rx = re.compile(args[1], re.I)
    hits = 0
    for line in kb_fetch(KB_INDEX).splitlines():
        m = re.match(r"- \[(.*?)\]\((.*?)\)(?::\s*(.*))?", line.strip())
        if not m or not rx.search(line):
            continue
        title, url, desc = m.group(1), m.group(2), (m.group(3) or "")
        ver = kb_version_of(url)
        if want and ver and not ver.replace("API ", "").startswith(want):
            continue
        hits += 1
        print(f"[{ver or 'any'}] {title}\n    {url}" + (f"\n    {desc[:160]}" if desc else ""))
    if not hits:
        print("no matches (try a broader REGEX, or drop --version)")


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    if argv[0] == "kb":
        cmd_kb(argv[1:])
        return
    conn = Conn()
    cmd, rest = argv[0], argv[1:]
    if cmd == "version":
        print(json.dumps(cluster_version(conn), indent=2))
    elif cmd == "spec":
        cmd_spec(conn, rest)
    elif cmd in ("get", "de-get"):
        if not rest:
            die(f"{cmd} PATH [key=value ...]")
        show(*conn.request("GET", rest[0], dataengine=(cmd == "de-get"), params=kv(rest[1:])))
    elif cmd == "call":
        if len(rest) < 2:
            die("call METHOD PATH [--data JSON | --file F] [--dataengine] [--yes]")
        method, path = rest[0].upper(), rest[1]
        opts = rest[2:]
        de, yes = "--dataengine" in opts, "--yes" in opts
        body = None
        if "--data" in opts:
            body = json.loads(opts[opts.index("--data") + 1])
        elif "--file" in opts:
            body = json.loads(Path(opts[opts.index("--file") + 1]).read_text())
        if method == "GET":
            show(*conn.request("GET", path, dataengine=de))
            return
        url = conn.url(path, de)
        if not yes:
            print(f"DRY RUN (add --yes to send): {method} {url}")
            if body is not None:
                print(json.dumps(body, indent=2))
            return
        show(*conn.request(method, path, body=body, dataengine=de))
    else:
        die(f"unknown command {cmd} (see --help)")


if __name__ == "__main__":
    main(sys.argv[1:])
