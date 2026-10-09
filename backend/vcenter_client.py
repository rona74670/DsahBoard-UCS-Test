"""
VCenterClient — pyVmomi-based vSphere API client.
Uses PropertyCollector for fast bulk retrieval of all VM/host/cluster attributes.
"""

import ssl
import re as _re
import requests
import urllib3
from pyVmomi import vim, vmodl
from pyVim.connect import SmartConnect, Disconnect

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import os as _os
# TLS: set INFRA_CA_BUNDLE to a CA bundle path, 'true' (system CAs), or leave
# unset/false to skip verification (lab self-signed certs default).
_CA = _os.getenv("INFRA_CA_BUNDLE", "").strip()
_TLS_VERIFY = (True if _CA.lower() in ("true", "1")
               else (_CA if _CA and _CA.lower() not in ("false", "0")
                     else False))




# ── Change-tracking events ──────────────────────────────────────────────────

_TRACKED_EVENTS = [
    "VmCreatedEvent",
    "VmClonedEvent",
    "VmDeployedEvent",
    "VmRemovedEvent",
    "VmReconfiguredEvent",
]

_EVENT_LABEL = {
    "VmCreatedEvent":      "\u05D4\u05E7\u05DE\u05EA \u05E9\u05E8\u05EA",
    "VmClonedEvent":       "\u05E9\u05DB\u05E4\u05D5\u05DC/\u05D8\u05DE\u05E4\u05DC\u05D8",
    "VmDeployedEvent":     "\u05E4\u05E8\u05D9\u05E1\u05D4 \u05DE\u05D8\u05DE\u05E4\u05DC\u05D8",
    "VmRemovedEvent":      "\u05D4\u05E1\u05E8\u05EA \u05E9\u05E8\u05EA",
    "VmReconfiguredEvent": "\u05E9\u05D9\u05E0\u05D5\u05D9 \u05DE\u05E9\u05D0\u05D1",
}

def _kb_to_human(kb: int) -> str:
    gb = kb / (1024 * 1024)
    if gb >= 1024:
        return f"{gb/1024:.1f}TB"
    return f"{gb:.0f}GB"


def _dir_label(old: int, new: int) -> str:
    """Hebrew increased/decreased label so CPU/RAM changes read as clearly as Disk ones."""
    if new > old:
        return "\u05D4\u05D5\u05D2\u05D3\u05DC"  # הוגדל
    if new < old:
        return "\u05D4\u05D5\u05E7\u05D8\u05DF"  # הוקטן
    return "\u05E9\u05D5\u05E0\u05D4"            # שונה


def _parse_fmsg_detail(resource: str, full_msg: str) -> str:
    """Parse fullFormattedMessage into a concise human-readable change detail."""
    if not full_msg:
        return ""

    if resource == "CPU":
        m = _re.search(r'\.numCPU\b[^:]*:\s*(\d+)\s*->\s*(\d+)', full_msg, _re.I)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
            return f"{_dir_label(old, new)}: {old} \u2192 {new} vCPU"
        m = _re.search(r'\.numCoresPerSocket\b[^:]*:\s*(\d+)\s*->\s*(\d+)', full_msg, _re.I)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
            return f"{_dir_label(old, new)}: Cores/socket {old} \u2192 {new}"
        return ""

    if resource == "RAM":
        m = _re.search(r'\.memoryMB\b[^:]*:\s*(\d+)\s*->\s*(\d+)', full_msg, _re.I)
        if m:
            old_mb, new_mb = int(m.group(1)), int(m.group(2))
            def _gb(x): v = round(x/1024, 1); return f"{int(v)}GB" if v == int(v) else f"{v}GB"
            return f"{_dir_label(old_mb, new_mb)}: {_gb(old_mb)} \u2192 {_gb(new_mb)}"
        return ""

    if resource == "Disk":
        parts = []

        def _disk_labels_and_caps(text):
            """Return [(label, size_human)] by pairing each Hard disk label
            with the first capacityInKB that appears after it in text."""
            labels = [(m.start(), m.group(1))
                      for m in _re.finditer(r'label\s*=\s*"(Hard disk \d+)"', text, _re.I)]
            caps   = [(m.start(), int(m.group(1)))
                      for m in _re.finditer(r'capacityInKB\s*=\s*(\d+)', text)]
            result = []
            for lpos, lname in labels:
                for cpos, cval in caps:
                    if cpos > lpos:
                        result.append((lname, _kb_to_human(cval)))
                        break
            return result

        # Disk resize in Modified section: capacityInKB: OLD -> NEW
        mod_m = _re.search(r'Modified:(.*?)(?:Added:|Deleted:|$)', full_msg, _re.S)
        if mod_m:
            for m in _re.finditer(r'capacityInKB[^:]*:\s*(\d+)\s*->\s*(\d+)', mod_m.group(1)):
                old_h, new_h = _kb_to_human(int(m.group(1))), _kb_to_human(int(m.group(2)))
                parts.append(f"\u05D4\u05D5\u05D2\u05D3\u05DC: {old_h}\u2192{new_h}")

        # Disk added
        add_m = _re.search(r'Added:(.*?)(?:Deleted:|$)', full_msg, _re.S)
        if add_m:
            for lname, size in _disk_labels_and_caps(add_m.group(1)):
                parts.append(f"\u05E0\u05D5\u05E1\u05E3 {lname}: {size}")

        # Disk deleted
        del_m = _re.search(r'Deleted:(.*?)$', full_msg, _re.S)
        if del_m:
            for lname, size in _disk_labels_and_caps(del_m.group(1)):
                parts.append(f"\u05D4\u05D5\u05E1\u05E8 {lname}: {size}")

        return "; ".join(parts)

    return ""


def _classify_from_fmsg(full_msg: str) -> str:
    """Classify change type using specific property paths in fullFormattedMessage."""
    if _re.search(r'\.numCPU\b|\.numCoresPerSocket\b', full_msg, _re.I):
        return "CPU"
    if _re.search(r'\.memoryMB\b', full_msg, _re.I):
        return "RAM"
    if _re.search(r'capacityInKB|Hard disk', full_msg, _re.I):
        return "Disk"
    return ""


def _is_dr_vm_creation(user: str, vm_name: str) -> bool:
    """Return True if this VmCreatedEvent is an automated DR/SRM operation."""
    u = (user or "").lower()
    v = (vm_name or "").lower()
    # SRM automated account: VSPHERE.PT\SRM-d0527337-...
    if _re.search(r'srm-[0-9a-f]{8}-', u):
        return True
    # VMware DR placeholder VM: name ends with -phVm
    if v.endswith('-phvm'):
        return True
    return False


def _norm_event(e) -> dict:
    try:
        etype_full = type(e).__name__           # may be "vim.event.VmCreatedEvent"
        etype      = etype_full.split(".")[-1]  # always short: "VmCreatedEvent"
        if etype not in _EVENT_LABEL:
            return {}
        vm_name = ""
        if hasattr(e, "vm") and e.vm:
            vm_name = getattr(e.vm, "name", "") or ""
        user = (getattr(e, "userName", "") or "system").strip()
        ts   = ""
        ct   = getattr(e, "createdTime", None)
        if ct:
            try:   ts = ct.strftime("%Y-%m-%dT%H:%M:%S")
            except Exception: ts = str(ct)
        key  = int(getattr(e, "key", 0) or 0)

        # Skip DR replicas, Veeam and Lifesaver backup VMs (all event types)
        vm_lower = vm_name.lower()
        if "replica" in vm_lower or "veeam" in vm_lower or "lifesaver" in vm_lower:
            return {}

        change_info = ""
        label       = _EVENT_LABEL[etype]
        desc        = ""

        if etype == "VmCreatedEvent":
            if _is_dr_vm_creation(user, vm_name):
                return {}

        elif etype in ("VmClonedEvent", "VmDeployedEvent"):
            if _is_dr_vm_creation(user, vm_name):
                return {}
            # Capture source template/VM name
            src_obj = getattr(e, "sourceVm", None)
            if src_obj:
                src_name = getattr(src_obj, "name", "") or ""
                if src_name:
                    desc = f"מ: {src_name}"

        elif etype == "VmReconfiguredEvent":
            full_msg = (getattr(e, "fullFormattedMessage", "") or "").strip()
            resource = _classify_from_fmsg(full_msg)
            if not resource:
                return {}
            change_info = resource
            label = {
                "CPU":  "\u05E9\u05D9\u05E0\u05D5\u05D9 CPU",
                "RAM":  "\u05E9\u05D9\u05E0\u05D5\u05D9 RAM",
                "Disk": "\u05E9\u05D9\u05E0\u05D5\u05D9 Disk",
            }[resource]
            desc = _parse_fmsg_detail(resource, full_msg)

        return {
            "key":         key,
            "event_type":  etype,
            "event_label": label,
            "vm_name":     vm_name,
            "user_name":   user,
            "timestamp":   ts,
            "change_info": change_info,
            "description": desc,
        }
    except Exception:
        return {}

class VCenterClient:
    def __init__(self, host: str, username: str, password: str, port: int = 443):
        self.host = host
        self.username = username
        self.password = password
        self.port = port

    def _connect(self):
        ctx = ssl.create_default_context()
        if _TLS_VERIFY is False:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        elif isinstance(_TLS_VERIFY, str):
            ctx.load_verify_locations(_TLS_VERIFY)
        else:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return SmartConnect(
            host=self.host,
            user=self.username,
            pwd=self.password,
            port=self.port,
            sslContext=ctx,
        )

    # ------------------------------------------------------------------

    def get_events(self, hours: int = 25) -> list:
        """Query vCenter event history. hours <= 720 (30 days max)."""
        from datetime import datetime, timedelta, timezone as _tz
        si = self._connect()
        try:
            content = si.RetrieveContent()
            em      = content.eventManager
            end   = datetime.now(_tz.utc)
            start = end - timedelta(hours=min(hours, 720))
            time_filter = vim.event.EventFilterSpec.ByTime(beginTime=start, endTime=end)

            # Accept both "VmCreatedEvent" and "vim.event.VmCreatedEvent" from pyVmomi
            _tracked_set = set(_TRACKED_EVENTS) | {"vim.event." + t for t in _TRACKED_EVENTS}
            for type_ids in [_TRACKED_EVENTS,
                             ["vim.event." + t for t in _TRACKED_EVENTS],
                             None]:
                try:
                    spec = vim.event.EventFilterSpec(time=time_filter)
                    if type_ids is not None:
                        spec.eventTypeId = type_ids
                    raw = em.QueryEvents(spec) or []
                    # Filter in Python (needed for the None/all-events fallback)
                    raw = [e for e in raw if type(e).__name__ in _tracked_set]
                    if raw or type_ids is None:
                        return [n for n in (_norm_event(e) for e in raw) if n and n.get("key")]
                except Exception:
                    continue
            return []
        finally:
            Disconnect(si)

    def ping(self) -> dict:
        si = self._connect()
        try:
            about = si.content.about
            return {
                "status":    "ok",
                "host":      self.host,
                "version":   about.version,
                "build":     about.build,
                "full_name": about.fullName,
            }
        finally:
            Disconnect(si)

    # ------------------------------------------------------------------
    def get_vms(self) -> list[dict]:
        si = self._connect()
        try:
            content = si.RetrieveContent()
            custom_fields = _build_custom_fields(content)
            host_cluster_map, _ = _fetch_cluster_map(content)
            host_name_map       = _fetch_host_names(content)
            return _collect_vms(content, custom_fields, host_name_map, host_cluster_map)
        finally:
            Disconnect(si)

    # ------------------------------------------------------------------
    def get_hosts(self) -> list[dict]:
        si = self._connect()
        try:
            content = si.RetrieveContent()
            host_cluster_map, _ = _fetch_cluster_map(content)
            return _collect_hosts(content, host_cluster_map)
        finally:
            Disconnect(si)

    # ------------------------------------------------------------------
    def get_srm_info(self) -> dict:
        """Detect SRM via vCenter extensionManager and query SRM REST API if available."""
        si = self._connect()
        try:
            content = si.RetrieveContent()
            ext_mgr = content.extensionManager

            srm_ext = None
            for ext in (ext_mgr.extensionList or []):
                key = getattr(ext, "key", "") or ""
                if ("vcDr" in key or "srm" in key.lower()
                        or "draas" in key.lower() or "vmware.vr" in key.lower()):
                    srm_ext = ext
                    break

            if srm_ext is None:
                return {"installed": False, "vcenter": self.host}

            srm_url  = None
            for srv in (getattr(srm_ext, "server", []) or []):
                url = getattr(srv, "url", None)
                if url:
                    srm_url = url
                    break

            import urllib.parse
            srm_host = None
            if srm_url:
                try:
                    srm_host = urllib.parse.urlparse(srm_url).hostname
                except Exception:
                    pass

            base_info = {
                "installed":      True,
                "extension_key":  getattr(srm_ext, "key", ""),
                "version":        getattr(srm_ext, "version", ""),
                "url":            srm_url,
                "host":           srm_host or self.host,
                "vcenter":        self.host,
            }

            if not srm_host:
                srm_host = self.host

            # Try SRM REST API
            try:
                srm_data = _query_srm_api(srm_host, self.username, self.password)
                base_info.update(srm_data)
            except Exception as e:
                base_info["srm_api_error"] = str(e)
                base_info["protection_groups"] = []
                base_info["recovery_plans"] = []

            return base_info
        finally:
            Disconnect(si)

    # ------------------------------------------------------------------
    def get_summary(self) -> dict:
        si = self._connect()
        try:
            content = si.RetrieveContent()
            custom_fields       = _build_custom_fields(content)
            host_cluster_map, clusters = _fetch_cluster_map(content)
            host_name_map       = _fetch_host_names(content)
            ds_by_mor, host_ds_map = _fetch_datastores(content, host_cluster_map)
            affinity_rules      = _fetch_cluster_rules(content)
            vms   = _collect_vms(content, custom_fields, host_name_map, host_cluster_map, ds_by_mor)
            hosts = _collect_hosts(content, host_cluster_map, host_ds_map)
        finally:
            Disconnect(si)

        powered_on  = [v for v in vms if v["power_state"] == "poweredOn"]
        powered_off = [v for v in vms if v["power_state"] == "poweredOff"]
        suspended   = [v for v in vms if v["power_state"] == "suspended"]
        datastores  = sorted(ds_by_mor.values(), key=lambda d: d["name"].lower())

        return {
            "total_vms":        len(vms),
            "powered_on":       len(powered_on),
            "powered_off":      len(powered_off),
            "suspended":        len(suspended),
            "active_vcpu":      sum(v["num_cpu"] for v in powered_on),
            "active_ram_gb":    round(sum(v["memory_gb"] for v in powered_on), 1),
            "total_storage_gb": round(sum(v["storage_committed_gb"] for v in vms), 1),
            "clusters":         sorted(clusters),
            "hosts":            sorted(hosts, key=lambda h: (h["cluster"], h["name"])),
            "vms":              vms,
            "datastores":       datastores,
            "affinity_rules":   affinity_rules,
        }


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------

def _build_custom_fields(content) -> dict:
    fields: dict[int, str] = {}
    if content.customFieldsManager and content.customFieldsManager.field:
        for f in content.customFieldsManager.field:
            fields[f.key] = f.name
    return fields


def _tspec(name, obj_type, path, select_names):
    return vmodl.query.PropertyCollector.TraversalSpec(
        name=name, type=obj_type, path=path, skip=False,
        selectSet=[vmodl.query.PropertyCollector.SelectionSpec(name=n) for n in select_names],
    )


def _paginate(pc, filter_spec, max_objects=2000) -> list:
    opts   = vmodl.query.PropertyCollector.RetrieveOptions(maxObjects=max_objects)
    result = pc.RetrievePropertiesEx([filter_spec], opts)
    objs   = list(result.objects) if result and result.objects else []
    token  = result.token if result else None
    while token:
        cont  = pc.ContinueRetrievePropertiesEx(token)
        objs += list(cont.objects) if cont and cont.objects else []
        token  = cont.token if cont else None
    return objs


# ── Cluster map ─────────────────────────────────────────────────────────

def _fetch_cluster_map(content) -> tuple[dict, list]:
    """Returns ({host_mor: cluster_name}, [cluster_name, ...])."""
    pc = content.propertyCollector
    traversal = [
        _tspec("f2c",  vim.Folder,     "childEntity", ["f2c", "dc2hf"]),
        _tspec("dc2hf", vim.Datacenter, "hostFolder", ["f2c"]),
    ]
    os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
    ps_ = vmodl.query.PropertyCollector.PropertySpec(
        type=vim.ClusterComputeResource, all=False, pathSet=["name", "host"])
    objs = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]), max_objects=200)

    host_cluster: dict[str, str] = {}
    cluster_names: list[str]     = []
    for obj in objs:
        props = {p.name: p.val for p in obj.propSet} if obj.propSet else {}
        cname = props.get("name", "Unknown")
        cluster_names.append(cname)
        for h in (props.get("host") or []):
            host_cluster[str(h)] = cname
    return host_cluster, sorted(set(cluster_names))


# ── Datastores (volumes) — capacity, free space, risk, host mounts ───────

_DS_CRITICAL_FREE_PCT = 10   # below this free % → critical (risk of running out of space)
_DS_WARNING_FREE_PCT  = 20   # below this free % → warning

def _ds_risk(free_pct: float) -> str:
    if free_pct < _DS_CRITICAL_FREE_PCT:
        return "critical"
    if free_pct < _DS_WARNING_FREE_PCT:
        return "warning"
    return "ok"


def _fetch_datastores(content, host_cluster_map) -> tuple[dict, dict]:
    """Returns ({ds_mor: ds_info}, {host_mor: [ds_info, ...]})."""
    pc = content.propertyCollector
    traversal = [
        _tspec("f2f",   vim.Folder,     "childEntity",     ["f2f", "dc2ds"]),
        _tspec("dc2ds", vim.Datacenter, "datastoreFolder", ["f2f"]),
    ]
    os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
    ps_ = vmodl.query.PropertyCollector.PropertySpec(
        type=vim.Datastore, all=False,
        pathSet=["name", "summary.capacity", "summary.freeSpace", "summary.type",
                  "summary.accessible", "host"])
    objs = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]), max_objects=500)

    ds_by_mor: dict = {}
    host_ds_map: dict = {}
    for obj in objs:
        if not obj.propSet:
            continue
        props    = {p.name: p.val for p in obj.propSet}
        mor      = str(obj.obj)
        capacity = props.get("summary.capacity", 0) or 0
        free     = props.get("summary.freeSpace", 0) or 0
        used     = max(capacity - free, 0)
        free_pct = round(free / capacity * 100, 1) if capacity else 0
        used_pct = round(used / capacity * 100, 1) if capacity else 0
        host_mounts = props.get("host") or []
        host_mors   = [str(getattr(hm, "key", "")) for hm in host_mounts if getattr(hm, "key", None) is not None]
        clusters    = sorted({host_cluster_map.get(hmor, "Standalone") for hmor in host_mors})

        ds_info = {
            "name":        props.get("name", ""),
            "capacity_gb": round(capacity / (1024 ** 3), 1),
            "free_gb":     round(free / (1024 ** 3), 1),
            "used_gb":     round(used / (1024 ** 3), 1),
            "free_pct":    free_pct,
            "used_pct":    used_pct,
            "type":        props.get("summary.type", "") or "",
            "accessible":  bool(props.get("summary.accessible", True)),
            "clusters":    clusters,
            "risk":        _ds_risk(free_pct),
        }
        ds_by_mor[mor] = ds_info
        for hmor in host_mors:
            host_ds_map.setdefault(hmor, []).append(ds_info)

    return ds_by_mor, host_ds_map


# ── DRS affinity / anti-affinity rules ────────────────────────────────────

def _fetch_cluster_rules(content) -> list[dict]:
    """Returns cluster VM/host affinity & anti-affinity rules (DRS rules)."""
    pc = content.propertyCollector
    traversal = [
        _tspec("f2c",   vim.Folder,     "childEntity", ["f2c", "dc2hf"]),
        _tspec("dc2hf", vim.Datacenter, "hostFolder",  ["f2c"]),
    ]
    os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
    ps_ = vmodl.query.PropertyCollector.PropertySpec(
        type=vim.ClusterComputeResource, all=False, pathSet=["name", "configurationEx"])
    objs = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]), max_objects=200)

    rules_out: list[dict] = []
    for obj in objs:
        if not obj.propSet:
            continue
        props = {p.name: p.val for p in obj.propSet}
        cname = props.get("name", "Unknown")
        cfg   = props.get("configurationEx")
        if cfg is None:
            continue

        def _safe_name(mo) -> str:
            try:
                return getattr(mo, "name", "") or ""
            except Exception:
                return ""

        vm_groups:   dict = {}
        host_groups: dict = {}
        for g in (getattr(cfg, "group", []) or []):
            try:
                if isinstance(g, vim.cluster.VmGroup):
                    vm_groups[g.name] = [_safe_name(v) for v in (g.vm or [])]
                elif isinstance(g, vim.cluster.HostGroup):
                    host_groups[g.name] = [_safe_name(h) for h in (g.host or [])]
            except Exception:
                continue

        for r in (getattr(cfg, "rule", []) or []):
            try:
                name      = getattr(r, "name", "") or ""
                enabled   = bool(getattr(r, "enabled", True))
                mandatory = bool(getattr(r, "mandatory", False))

                if isinstance(r, vim.cluster.AffinityRuleSpec):
                    rules_out.append({
                        "cluster": cname, "name": name, "type": "affinity",
                        "enabled": enabled, "mandatory": mandatory,
                        "vms": [n for n in (_safe_name(v) for v in (r.vm or [])) if n],
                        "hosts": [],
                    })
                elif isinstance(r, vim.cluster.AntiAffinityRuleSpec):
                    rules_out.append({
                        "cluster": cname, "name": name, "type": "anti-affinity",
                        "enabled": enabled, "mandatory": mandatory,
                        "vms": [n for n in (_safe_name(v) for v in (r.vm or [])) if n],
                        "hosts": [],
                    })
                elif isinstance(r, vim.cluster.VmHostRuleInfo):
                    affine_group      = getattr(r, "affineHostGroupName", "") or ""
                    anti_affine_group = getattr(r, "antiAffineHostGroupName", "") or ""
                    kind        = "vm-host-affinity" if affine_group else "vm-host-anti-affinity"
                    host_group  = affine_group or anti_affine_group
                    rules_out.append({
                        "cluster": cname, "name": name, "type": kind,
                        "enabled": enabled, "mandatory": mandatory,
                        "vms":   vm_groups.get(getattr(r, "vmGroupName", ""), []),
                        "hosts": host_groups.get(host_group, []),
                    })
            except Exception:
                continue
    return rules_out


# ── Host name map ────────────────────────────────────────────────────────

def _fetch_host_names(content) -> dict:
    """Returns {host_mor: hostname}."""
    pc = content.propertyCollector
    traversal = [
        _tspec("f2f",  vim.Folder,          "childEntity", ["f2f", "dc2hf", "cr2h"]),
        _tspec("dc2hf", vim.Datacenter,     "hostFolder",  ["f2f"]),
        _tspec("cr2h",  vim.ComputeResource, "host",        []),
    ]
    os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
    ps_ = vmodl.query.PropertyCollector.PropertySpec(type=vim.HostSystem, all=False, pathSet=["name"])
    objs = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]), max_objects=500)
    return {str(obj.obj): obj.propSet[0].val for obj in objs if obj.propSet}


# ── DVPortgroup map (name + VLAN per portgroup key) ──────────────────────

def _parse_vlan(vlan) -> "int | str | None":
    """Parse a DVS vlan spec into a human-readable value."""
    if vlan is None:
        return None
    try:
        if isinstance(vlan, vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec):
            return int(vlan.vlanId)
        if isinstance(vlan, vim.dvs.VmwareDistributedVirtualSwitch.TrunkVlanSpec):
            ranges = getattr(vlan, "vlanId", []) or []
            if not ranges:
                return "trunk"
            parts = []
            for r in ranges:
                if r.start == r.end:
                    parts.append(str(r.start))
                else:
                    parts.append(f"{r.start}-{r.end}")
            return "trunk:" + ",".join(parts)
    except Exception:
        pass
    return None


def _fetch_dvportgroup_map(content) -> dict:
    """Returns {portgroup_key: {name, vlan_id}} for all DVPortgroups."""
    try:
        pc = content.propertyCollector
        traversal = [
            _tspec("f2f",   vim.Folder,      "childEntity",   ["f2f", "dc2net"]),
            _tspec("dc2net", vim.Datacenter, "networkFolder", ["f2f"]),
        ]
        os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
        ps_ = vmodl.query.PropertyCollector.PropertySpec(
            type=vim.dvs.DistributedVirtualPortgroup, all=False,
            pathSet=["name", "key", "config"])
        objs = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]), max_objects=1000)
        result: dict = {}
        for obj in objs:
            if not obj.propSet:
                continue
            props = {p.name: p.val for p in obj.propSet}
            key    = props.get("key", "")
            name   = props.get("name", "")
            config = props.get("config")
            vlan_id = None
            if config is not None:
                dpc = getattr(config, "defaultPortConfig", None)
                if dpc is not None:
                    vlan_id = _parse_vlan(getattr(dpc, "vlan", None))
            if key:
                result[key] = {"name": name, "vlan_id": vlan_id}
        return result
    except Exception:
        return {}


def _extract_vm_port_groups(nics, dvpg_map: dict) -> tuple:
    """Return (port_groups_list, vlan_ids_list) from VM NICs."""
    pg_names: list = []
    vlan_ids: list = []
    for nic in nics:
        backing = getattr(nic, "backing", None)
        if backing is None:
            continue
        pg_name  = None
        vlan_id  = None
        if isinstance(backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo):
            pg_name = getattr(backing, "deviceName", "") or ""
        elif isinstance(backing, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo):
            port = getattr(backing, "port", None)
            if port:
                pgkey = getattr(port, "portgroupKey", "") or ""
                if pgkey and pgkey in dvpg_map:
                    info    = dvpg_map[pgkey]
                    pg_name = info.get("name", "")
                    vlan_id = info.get("vlan_id")
        if pg_name and pg_name not in pg_names:
            pg_names.append(pg_name)
            vlan_ids.append(vlan_id)
    return pg_names, vlan_ids


# ── VM bulk fetch ────────────────────────────────────────────────────────

_WIN_SERVER_BUILDS = {
    "26100": "Windows Server 2025", "20348": "Windows Server 2022",
    "17763": "Windows Server 2019", "14393": "Windows Server 2016",
    "9600": "Windows Server 2012 R2", "9200": "Windows Server 2012",
    "7601": "Windows Server 2008 R2",
}


def _parse_guest_detail(raw: str) -> str:
    """Turn guest.guestDetailedData (key='value' pairs reported by VMware Tools)
    into a precise OS label, e.g. 'Windows Server 2022 Standard (build 20348)'."""
    if not raw:
        return ""
    kv = dict(_re.findall(r"(\w+)='([^']*)'", raw))
    name  = (kv.get("prettyName") or kv.get("distroName") or "").strip()
    build = (kv.get("buildNumber") or "").strip()
    if not name and kv.get("familyName", "").lower() == "windows" and build in _WIN_SERVER_BUILDS:
        name = _WIN_SERVER_BUILDS[build]
    if not name:
        return ""
    return f"{name} (build {build})" if build and "build" not in name.lower() else name


def _fetch_guest_detail(content, traversal) -> dict:
    """moId -> precise OS label. Separate, best-effort query: guest.guestDetailedData is not
    available on older vCenter/ESXi versions, and an unknown property would otherwise fail the
    whole VM query, so any error here just means 'no detail'."""
    try:
        pc  = content.propertyCollector
        os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
        ps_ = vmodl.query.PropertyCollector.PropertySpec(
            type=vim.VirtualMachine, all=False, pathSet=["guest.guestDetailedData"])
        out = {}
        for o in _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_])):
            props = {p.name: p.val for p in o.propSet} if o.propSet else {}
            label = _parse_guest_detail(props.get("guest.guestDetailedData") or "")
            if label:
                out[o.obj._moId] = label
        return out
    except Exception:
        return {}


def _collect_vms(content, custom_fields, host_name_map, host_cluster_map, ds_by_mor=None) -> list[dict]:
    pc = content.propertyCollector
    traversal = [
        _tspec("f2f",  vim.Folder,          "childEntity",  ["f2f", "dc2vm", "dc2hf"]),
        _tspec("dc2vm", vim.Datacenter,     "vmFolder",     ["f2f"]),
        _tspec("dc2hf", vim.Datacenter,     "hostFolder",   ["f2f"]),
        _tspec("cr2rp", vim.ComputeResource, "resourcePool", ["rp2rp", "rp2vm"]),
        _tspec("rp2rp", vim.ResourcePool,   "resourcePool", ["rp2rp", "rp2vm"]),
        _tspec("rp2vm", vim.ResourcePool,   "vm",           []),
    ]
    os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
    ps_ = vmodl.query.PropertyCollector.PropertySpec(
        type=vim.VirtualMachine, all=False,
        pathSet=[
            "name", "config.hardware.numCPU", "config.hardware.memoryMB",
            "config.guestFullName", "summary.guest.guestFullName",
            "runtime.powerState", "runtime.host", "datastore",
            "summary.storage.committed", "summary.storage.uncommitted",
            "summary.guest.ipAddress", "summary.guest.hostName",
            "summary.guest.toolsVersionStatus2", "customValue",
            "guest.disk", "guest.toolsRunningStatus",
            "config.managedBy", "config.version",
            "config.tools.syncTimeWithHost", "config.hardware.device",
            "summary.quickStats.overallCpuUsage",
            "summary.quickStats.guestMemoryUsage",
            "config.createDate",
        ],
    )
    objs = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]))
    dvpg_map = _fetch_dvportgroup_map(content)
    guest_detail = _fetch_guest_detail(content, traversal)
    vms  = []
    for obj in objs:
        try:
            props = {p.name: p.val for p in obj.propSet} if obj.propSet else {}
            vm_d = _props_to_vm(props, custom_fields, host_name_map, host_cluster_map, dvpg_map, ds_by_mor)
            vm_d["guest_os_detail"] = guest_detail.get(obj.obj._moId, "")
            vms.append(vm_d)
        except Exception:
            pass
    vms.sort(key=lambda v: (v["power_state"] != "poweredOn", v["name"].lower()))
    return vms


def _props_to_vm(props, custom_fields, host_name_map, host_cluster_map, dvpg_map=None, ds_by_mor=None) -> dict:
    host_obj    = props.get("runtime.host")
    host_mor    = str(host_obj) if host_obj is not None else ""
    host_name   = host_name_map.get(host_mor, "")
    cluster     = host_cluster_map.get(host_mor, "Standalone")

    ds_by_mor = ds_by_mor or {}
    vm_datastores = []
    for ds_obj in (props.get("datastore") or []):
        ds_info = ds_by_mor.get(str(ds_obj))
        if ds_info:
            vm_datastores.append(ds_info)
    ds_names = [d["name"] for d in vm_datastores]
    ds_risk  = "ok"
    if any(d["risk"] == "critical" for d in vm_datastores):
        ds_risk = "critical"
    elif any(d["risk"] == "warning" for d in vm_datastores):
        ds_risk = "warning"

    committed_bytes   = props.get("summary.storage.committed",   0) or 0
    uncommitted_bytes = props.get("summary.storage.uncommitted", 0) or 0
    cpu_usage_mhz     = props.get("summary.quickStats.overallCpuUsage", 0) or 0
    mem_alloc_mb      = props.get("config.hardware.memoryMB", 0) or 0
    mem_usage_mb      = props.get("summary.quickStats.guestMemoryUsage", 0) or 0
    mem_pct           = round(mem_usage_mb / mem_alloc_mb * 100, 1) if mem_alloc_mb else 0
    stor_total        = committed_bytes + uncommitted_bytes
    stor_pct          = round(committed_bytes / stor_total * 100, 1) if stor_total else 0

    custom_attrs: dict[str, str] = {}
    for attr in (props.get("customValue") or []):
        custom_attrs[custom_fields.get(attr.key, str(attr.key))] = attr.value

    managed_by = props.get("config.managedBy")
    is_dr_replica = False
    if managed_by is not None:
        ext_key = getattr(managed_by, "extensionKey", "") or ""
        if "vcdr" in ext_key.lower() or "srm" in ext_key.lower():
            is_dr_replica = True
    if not is_dr_replica:
        _nm = (props.get("name", "") or "").lower()
        if "replica" in _nm or "-phvm" in _nm:
            is_dr_replica = True

    live_os = props.get("summary.guest.guestFullName", "") or ""
    cfg_os  = props.get("config.guestFullName", "") or ""

    nics = [d for d in (props.get("config.hardware.device") or [])
            if isinstance(d, vim.vm.device.VirtualEthernetCard)]
    nic_total     = len(nics)
    nic_connected = sum(1 for n in nics if getattr(n.connectable, "connected", False))
    port_groups, vlan_ids = _extract_vm_port_groups(nics, dvpg_map or {})

    # Sum of the VM's virtual disks' configured capacity — unlike summary.storage.committed/
    # uncommitted, this is NOT inflated by temporary snapshot delta files (e.g. backup jobs),
    # so it only moves when a disk is actually resized/added/removed.
    disks = [d for d in (props.get("config.hardware.device") or [])
             if isinstance(d, vim.vm.device.VirtualDisk)]
    disk_capacity_kb = sum(getattr(d, "capacityInKB", 0) or 0 for d in disks)
    disk_capacity_gb = round(disk_capacity_kb / (1024 ** 2), 1)
    # PropertyCollector silently drops "config.hardware.device" for some VMs (observed on
    # VMs with many disks/snapshots — likely a per-object response-size limit), which reads
    # back as an empty device list here rather than an error. A real VM with meaningful
    # storage usage never has an actual 0GB disk capacity, so treat that combination as
    # "unknown" (None) instead of 0 — callers already fall back to committed+uncommitted
    # when this field is None, and reporting it as a real 0 previously caused false
    # "-100% storage" deltas for every affected VM.
    if disk_capacity_gb == 0 and (committed_bytes + uncommitted_bytes) / (1024 ** 3) > 1:
        disk_capacity_gb = None

    # In-guest disk usage as reported by VMware Tools (guest.disk: per-partition capacity/
    # freeSpace). None = no data (Tools missing/not running, or VM never reported any).
    guest_disks = props.get("guest.disk") or []
    guest_cap_b  = sum(getattr(d, "capacity", 0) or 0 for d in guest_disks)
    guest_free_b = sum(getattr(d, "freeSpace", 0) or 0 for d in guest_disks)
    if guest_disks and guest_cap_b > 0:
        guest_disk_used_gb = round((guest_cap_b - guest_free_b) / (1024 ** 3), 1)
        guest_disk_capacity_gb = round(guest_cap_b / (1024 ** 3), 1)
    else:
        guest_disk_used_gb = None
        guest_disk_capacity_gb = None

    # config.createDate only populated on vSphere 6.7U2+; may be absent on older VMs/hosts
    create_dt = props.get("config.createDate")
    created_date = create_dt.isoformat() if create_dt else ""

    return {
        "name":                   props.get("name", ""),
        "created_date":           created_date,
        "power_state":            str(props.get("runtime.powerState", "unknown")),
        "cluster":                cluster,
        "num_cpu":                props.get("config.hardware.numCPU", 0) or 0,
        "memory_gb":              round((props.get("config.hardware.memoryMB", 0) or 0) / 1024, 1),
        "storage_committed_gb":   round(committed_bytes   / (1024 ** 3), 1),
        "storage_uncommitted_gb": round(uncommitted_bytes / (1024 ** 3), 1),
        "storage_disk_capacity_gb": disk_capacity_gb,
        "guest_disk_used_gb":     guest_disk_used_gb,
        "guest_disk_capacity_gb": guest_disk_capacity_gb,
        "vmtools_running":        str(props.get("guest.toolsRunningStatus", "") or ""),
        "guest_os":               live_os or cfg_os,
        "guest_os_confirmed":     bool(live_os),
        "ip_address":             props.get("summary.guest.ipAddress", "") or "",
        "hostname":               props.get("summary.guest.hostName",  "") or "",
        "host":                   host_name,
        "vmtools_version":        "",
        "vmtools_status":         str(props.get("summary.guest.toolsVersionStatus2", "") or ""),
        "hw_version":             str(props.get("config.version", "") or ""),
        "nic_total":              nic_total,
        "nic_connected":          nic_connected,
        "port_groups":            port_groups,
        "vlan_ids":               vlan_ids,
        "is_thin":                uncommitted_bytes > 0,
        "time_sync_with_host":    bool(props.get("config.tools.syncTimeWithHost", False)),
        "sap_number":             custom_attrs.get("SAP_NUMBER", "").strip(),
        "is_dr_replica":          is_dr_replica,
        "custom_attrs":           custom_attrs,
        "cpu_usage_mhz":          cpu_usage_mhz,
        "mem_pct":                mem_pct,
        "stor_pct":               stor_pct,
        "datastores":             ds_names,
        "datastore_risk":         ds_risk,
    }


# ── SRM REST API helper ─────────────────────────────────────────────────

def _query_srm_api(host: str, username: str, password: str) -> dict:
    """
    Attempt to authenticate against VMware SRM REST API and return protection
    groups + recovery plans.  SRM 8.3+ exposes a REST API under /api/.
    """
    sess = requests.Session()
    sess.verify = _TLS_VERIFY

    rest_bases = [
        f"https://{host}/api",
        f"https://{host}:443/api",
        f"https://{host}:8095/api",
        f"https://{host}/dr/api",
        f"https://{host}/dr-api",
    ]
    token = None
    base  = None
    for b in rest_bases:
        try:
            r = sess.post(
                f"{b}/session",
                json={"username": username, "password": password},
                timeout=10,
            )
            if r.status_code == 200:
                try:
                    token = r.json()
                    if not isinstance(token, str):
                        token = str(token)
                except Exception:
                    token = r.text.strip('"')
                base = b
                break
        except Exception:
            continue

    if not token or not base:
        raise RuntimeError("SRM REST API not reachable — ניתן לפתוח ישירות ב-SRM")

    # VMware standard session header (works for SRM 8.x and vCenter REST API)
    sess.headers["vmware-api-session-id"] = token
    sess.headers["vmware-srm-session"]    = token  # fallback for older SRM

    session = sess

    # Protection groups
    r = session.get(f"{base}/protection-groups", timeout=30)
    r.raise_for_status()
    pg_raw = r.json()
    groups_raw = pg_raw if isinstance(pg_raw, list) else pg_raw.get("list", [])

    # Recovery plans
    r = session.get(f"{base}/recovery-plans", timeout=30)
    r.raise_for_status()
    rp_raw = r.json()
    plans_raw = rp_raw if isinstance(rp_raw, list) else rp_raw.get("list", [])

    # Enrich each protection group with its protected VMs
    groups = []
    for g in groups_raw[:30]:
        pg_id = g.get("id") or g.get("protection_group_id", "")
        vms_out = []
        try:
            rv = session.get(f"{base}/protection-groups/{pg_id}/protected-vms", timeout=15)
            if rv.ok:
                vm_data = rv.json()
                vms_list = vm_data if isinstance(vm_data, list) else vm_data.get("list", [])
                for v in vms_list[:100]:
                    vms_out.append({
                        "id":    v.get("id", ""),
                        "name":  v.get("name") or v.get("vm_id", ""),
                        "state": v.get("protection_state") or v.get("state", ""),
                    })
        except Exception:
            pass
        groups.append({
            "id":        pg_id,
            "name":      g.get("name", ""),
            "state":     g.get("state", ""),
            "type":      g.get("protection_group_type") or g.get("type", ""),
            "vm_count":  len(vms_out),
            "vms":       vms_out,
        })

    plans = [{
        "id":          p.get("id", ""),
        "name":        p.get("name", ""),
        "state":       p.get("state", ""),
        "last_tested": p.get("last_test_time") or p.get("last_tested_at"),
    } for p in plans_raw]

    return {"protection_groups": groups, "recovery_plans": plans}


# ── Host bulk fetch ──────────────────────────────────────────────────────

def _extract_ntp(date_time_info) -> list[str]:
    try:
        servers = date_time_info.ntpConfig.server
        return list(servers) if servers else []
    except Exception:
        return []


def _collect_hosts(content, host_cluster_map, host_ds_map=None) -> list[dict]:
    pc = content.propertyCollector
    traversal = [
        _tspec("f2f",   vim.Folder,          "childEntity", ["f2f", "dc2hf", "cr2h"]),
        _tspec("dc2hf", vim.Datacenter,      "hostFolder",  ["f2f"]),
        _tspec("cr2h",  vim.ComputeResource, "host",        []),
    ]
    os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
    ps_ = vmodl.query.PropertyCollector.PropertySpec(
        type=vim.HostSystem, all=False,
        pathSet=[
            "name",
            "summary.hardware.numCpuCores",
            "summary.hardware.numCpuPkgs",
            "summary.hardware.cpuMhz",
            "summary.hardware.memorySize",
            "summary.quickStats.overallCpuUsage",
            "summary.quickStats.overallMemoryUsage",
            "summary.overallStatus",
            "runtime.connectionState",
            "runtime.powerState",
            "hardware.systemInfo.model",
            "hardware.systemInfo.vendor",
            "config.dateTimeInfo",
        ],
    )
    objs  = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]), max_objects=500)
    hosts = []
    for obj in objs:
        try:
            props = {p.name: p.val for p in obj.propSet} if obj.propSet else {}
            mor   = str(obj.obj)

            cpu_cores     = props.get("summary.hardware.numCpuCores", 0) or 0
            cpu_mhz       = props.get("summary.hardware.cpuMhz", 0)      or 0
            cpu_total_mhz = cpu_cores * cpu_mhz
            cpu_usage_mhz = props.get("summary.quickStats.overallCpuUsage", 0) or 0
            cpu_pct       = round(cpu_usage_mhz / cpu_total_mhz * 100, 1) if cpu_total_mhz else 0

            mem_total_mb  = (props.get("summary.hardware.memorySize", 0) or 0) / (1024 ** 2)
            mem_usage_mb  = props.get("summary.quickStats.overallMemoryUsage", 0) or 0
            mem_pct       = round(mem_usage_mb / mem_total_mb * 100, 1) if mem_total_mb else 0

            host_datastores = (host_ds_map or {}).get(mor, [])
            ds_risk = "ok"
            if any(d["risk"] == "critical" for d in host_datastores):
                ds_risk = "critical"
            elif any(d["risk"] == "warning" for d in host_datastores):
                ds_risk = "warning"

            hosts.append({
                "name":           props.get("name", ""),
                "cluster":        host_cluster_map.get(mor, "Standalone"),
                "cpu_cores":      cpu_cores,
                "cpu_pkgs":       props.get("summary.hardware.numCpuPkgs", 0) or 0,
                "cpu_total_mhz":  cpu_total_mhz,
                "cpu_usage_mhz":  cpu_usage_mhz,
                "cpu_pct":        cpu_pct,
                "mem_total_gb":   round(mem_total_mb / 1024, 1),
                "mem_usage_gb":   round(mem_usage_mb / 1024, 1),
                "mem_pct":        mem_pct,
                "status":         str(props.get("summary.overallStatus",     "unknown")),
                "connection":     str(props.get("runtime.connectionState",   "unknown")),
                "power":          str(props.get("runtime.powerState",        "unknown")),
                "model":          props.get("hardware.systemInfo.model",  "") or "",
                "vendor":         props.get("hardware.systemInfo.vendor", "") or "",
                "ntp_servers":    _extract_ntp(props.get("config.dateTimeInfo")),
                "datastores":     host_datastores,
                "datastore_risk": ds_risk,
            })
        except Exception:
            pass
    return hosts

# -- Lightweight per-minute performance sampling (Performance page) --------

def collect_perf_samples(si) -> list:
    """One cheap PropertyCollector pass over every powered-on VM: only CPU/RAM live stats.

    Takes an already-open ServiceInstance (the collector keeps one session open between
    samples instead of logging in every minute). Returns
    [{name, num_cpu, mem_mb, cpu_pct, mem_pct}, ...] where cpu_pct is the VM's CPU usage as a
    percentage of its maximum (runtime.maxCpuUsage = vCPUs x host core MHz, the same basis
    vSphere uses for its own "CPU usage %") and mem_pct is guest-active memory / configured RAM.
    """
    content = si.RetrieveContent()
    pc = content.propertyCollector
    traversal = [
        _tspec("f2f",  vim.Folder,          "childEntity",  ["f2f", "dc2vm", "dc2hf"]),
        _tspec("dc2vm", vim.Datacenter,     "vmFolder",     ["f2f"]),
        _tspec("dc2hf", vim.Datacenter,     "hostFolder",   ["f2f"]),
        _tspec("cr2rp", vim.ComputeResource, "resourcePool", ["rp2rp", "rp2vm"]),
        _tspec("rp2rp", vim.ResourcePool,   "resourcePool", ["rp2rp", "rp2vm"]),
        _tspec("rp2vm", vim.ResourcePool,   "vm",           []),
    ]
    os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
    ps_ = vmodl.query.PropertyCollector.PropertySpec(
        type=vim.VirtualMachine, all=False,
        pathSet=[
            "name", "runtime.powerState", "runtime.maxCpuUsage", "runtime.host",
            "config.hardware.numCPU", "config.hardware.memoryMB",
            "summary.quickStats.overallCpuUsage", "summary.quickStats.guestMemoryUsage",
        ],
    )
    objs = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]))
    out = []
    for obj in objs:
        props = {p.name: p.val for p in obj.propSet} if obj.propSet else {}
        if str(props.get("runtime.powerState", "")) != "poweredOn":
            continue
        name = props.get("name", "")
        mem_mb = props.get("config.hardware.memoryMB", 0) or 0
        max_mhz = props.get("runtime.maxCpuUsage", 0) or 0
        if not name or not mem_mb or not max_mhz:
            continue
        cpu_mhz = props.get("summary.quickStats.overallCpuUsage", 0) or 0
        out.append({
            "_obj":    obj.obj,
            "host_mor": str(props.get("runtime.host") or ""),
            "name":    name,
            "num_cpu": props.get("config.hardware.numCPU", 0) or 0,
            "mem_mb":  mem_mb,
            "cpu_pct": round(min(cpu_mhz / max_mhz * 100, 100.0), 1),
            "mem_pct": round(min((props.get("summary.quickStats.guestMemoryUsage", 0) or 0) / mem_mb * 100, 100.0), 1),
        })
    return out


_ready_counter_ids: dict = {}   # vCenter instanceUuid -> counter id of cpu.ready.summation


_mem_counter_ids: dict = {}   # vCenter instanceUuid -> {"swap": id, "balloon": id, "lat": id}


def collect_mem_pressure(si, samples: list) -> None:
    """Adds host-side memory pressure to each sample (realtime, last ~1 min, averaged):
    "swap_mb"     mem.swapped      - VM memory the host pushed to disk (any value > 0 is bad)
    "balloon_mb"  mem.vmmemctl     - memory the host reclaims through the balloon driver
    "mem_lat_pct" mem.latency      - % of time the VM waits for memory because of compression/swapping
    Failures leave the samples untouched (CPU/RAM sampling must never break)."""
    content = si.RetrieveContent()
    pm = content.perfManager
    key = content.about.instanceUuid
    ids = _mem_counter_ids.get(key)
    if ids is None:
        by_name = {(c.groupInfo.key, c.nameInfo.key, str(c.rollupType)): c.key for c in pm.perfCounter}
        ids = {"swap": by_name.get(("mem", "swapped", "average")),
               "balloon": by_name.get(("mem", "vmmemctl", "average")),
               "lat": by_name.get(("mem", "latency", "average"))}
        _mem_counter_ids[key] = ids
    want = {cid: k for k, cid in ids.items() if cid is not None}
    if not want:
        return
    by_obj = {s["_obj"]: s for s in samples if s.get("_obj") is not None}
    objs = list(by_obj)
    for i in range(0, len(objs), 150):
        specs = [vim.PerformanceManager.QuerySpec(
                     entity=o, intervalId=20, maxSample=3,
                     metricId=[vim.PerformanceManager.MetricId(counterId=cid, instance="") for cid in want])
                 for o in objs[i:i + 150]]
        try:
            res = pm.QueryPerf(querySpec=specs)
        except Exception:
            continue
        for r in res or []:
            s = by_obj.get(r.entity)
            if not s:
                continue
            for series in (r.value or []):
                k = want.get(series.id.counterId)
                vals = [v for v in (series.value or []) if v is not None and v >= 0]
                if not k or not vals:
                    continue
                avg = sum(vals) / len(vals)
                if k == "swap":
                    s["swap_mb"] = round(avg / 1024, 1)
                elif k == "balloon":
                    s["balloon_mb"] = round(avg / 1024, 1)
                else:
                    s["mem_lat_pct"] = round(avg, 2)


def collect_host_live(si) -> dict:
    """Live load of every ESXi host: {host mor string: {...}} (one light PropertyCollector pass).

    The mor string is str(obj) - the same form as the "host_mor" collect_perf_samples puts on each VM."""
    content = si.RetrieveContent()
    pc = content.propertyCollector
    traversal = [
        _tspec("f2f",   vim.Folder,          "childEntity", ["f2f", "dc2hf", "cr2h"]),
        _tspec("dc2hf", vim.Datacenter,      "hostFolder",  ["f2f"]),
        _tspec("cr2h",  vim.ComputeResource, "host",        []),
    ]
    os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=content.rootFolder, skip=True, selectSet=traversal)
    ps_ = vmodl.query.PropertyCollector.PropertySpec(
        type=vim.HostSystem, all=False,
        pathSet=[
            "name",
            "summary.hardware.numCpuCores", "summary.hardware.cpuMhz", "summary.hardware.memorySize",
            "summary.quickStats.overallCpuUsage", "summary.quickStats.overallMemoryUsage",
            "summary.overallStatus", "runtime.connectionState", "runtime.inMaintenanceMode",
        ],
    )
    objs = _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_]), max_objects=500)
    out = {}
    for obj in objs:
        props = {p.name: p.val for p in obj.propSet} if obj.propSet else {}
        cores = props.get("summary.hardware.numCpuCores", 0) or 0
        total_mhz = cores * (props.get("summary.hardware.cpuMhz", 0) or 0)
        cpu_mhz = props.get("summary.quickStats.overallCpuUsage", 0) or 0
        mem_total_mb = (props.get("summary.hardware.memorySize", 0) or 0) / (1024 ** 2)
        mem_mb = props.get("summary.quickStats.overallMemoryUsage", 0) or 0
        out[str(obj.obj)] = {
            "name":         props.get("name", ""),
            "cores":        cores,
            "cpu_pct":      round(cpu_mhz / total_mhz * 100, 1) if total_mhz else 0,
            "mem_total_gb": round(mem_total_mb / 1024, 1),
            "mem_pct":      round(mem_mb / mem_total_mb * 100, 1) if mem_total_mb else 0,
            "status":       str(props.get("summary.overallStatus", "unknown")),
            "connection":   str(props.get("runtime.connectionState", "unknown")),
            "maintenance":  bool(props.get("runtime.inMaintenanceMode", False)),
        }
    return out


def collect_cpu_ready(si, samples: list) -> None:
    """Adds "ready_pct" (CPU Ready per vCPU, %) to each sample that vCenter has realtime data for.

    cpu.ready.summation is milliseconds summed over all vCPUs per 20 s realtime interval, so
    ready % per vCPU = ready_ms / (20000 * numCPU) * 100. The last 3 realtime samples (~1 minute)
    are averaged. Failures leave the samples untouched (CPU/RAM sampling must never break)."""
    content = si.RetrieveContent()
    pm = content.perfManager
    key = content.about.instanceUuid
    cid = _ready_counter_ids.get(key)
    if cid is None:
        for c in pm.perfCounter:
            if (c.groupInfo.key, c.nameInfo.key, str(c.rollupType)) == ("cpu", "ready", "summation"):
                cid = _ready_counter_ids[key] = c.key
                break
        if cid is None:
            return
    by_obj = {s["_obj"]: s for s in samples if s.get("_obj") is not None}
    objs = list(by_obj)
    for i in range(0, len(objs), 150):
        specs = [vim.PerformanceManager.QuerySpec(
                     entity=o, metricId=[vim.PerformanceManager.MetricId(counterId=cid, instance="")],
                     intervalId=20, maxSample=3) for o in objs[i:i + 150]]
        try:
            res = pm.QueryPerf(querySpec=specs)
        except Exception:
            continue
        for r in res or []:
            s = by_obj.get(r.entity)
            if not s or not r.value or not r.value[0].value or not s["num_cpu"]:
                continue
            vals = [v for v in r.value[0].value if v is not None and v >= 0]
            if vals:
                s["ready_pct"] = round(sum(vals) / len(vals) / (20000.0 * s["num_cpu"]) * 100, 2)


_disk_counter_ids: dict = {}   # vCenter instanceUuid -> {"read_ms": id, ...}

_DISK_COUNTERS = {
    "read_ms":    ("totalReadLatency",  "average"),
    "write_ms":   ("totalWriteLatency", "average"),
    "read_iops":  ("numberReadAveraged", "average"),
    "write_iops": ("numberWriteAveraged", "average"),
    "read_kbps":  ("read",  "average"),
    "write_kbps": ("write", "average"),
}


def _find_vm(si, name: str):
    """VM managed object by exact (case-insensitive) name, or None."""
    content = si.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
    try:
        pc = content.propertyCollector
        ts = vmodl.query.PropertyCollector.TraversalSpec(name="v", type=vim.view.ContainerView, path="view", skip=False)
        os_ = vmodl.query.PropertyCollector.ObjectSpec(obj=view, skip=True, selectSet=[ts])
        ps_ = vmodl.query.PropertyCollector.PropertySpec(type=vim.VirtualMachine, all=False, pathSet=["name"])
        want = name.lower()
        for o in _paginate(pc, vmodl.query.PropertyCollector.FilterSpec(objectSet=[os_], propSet=[ps_])):
            props = {p.name: p.val for p in o.propSet} if o.propSet else {}
            if (props.get("name") or "").lower() == want:
                return o.obj
    finally:
        view.Destroy()
    return None


def collect_vm_disks(si, vm_name: str) -> dict:
    """Live latency/IOPS/throughput per virtual disk of one VM (realtime 20 s samples, last ~5 min).

    Returns {"found": bool, "powered_on": bool, "disks": [{label, instance, datastore, size_gb,
    read_ms, write_ms, read_ms_max, write_ms_max, read_iops, write_iops, read_mbps, write_mbps}]}.
    Latency is what the ESXi host sees (guest-visible storage latency), in milliseconds."""
    vm = _find_vm(si, vm_name)
    if vm is None:
        return {"found": False, "powered_on": False, "disks": []}
    powered = str(vm.runtime.powerState) == "poweredOn"
    devices = vm.config.hardware.device if vm.config else []
    ctrl = {}
    for d in devices:
        if isinstance(d, vim.vm.device.VirtualSCSIController):
            ctrl[d.key] = "scsi%d" % d.busNumber
        elif isinstance(d, vim.vm.device.VirtualAHCIController):
            ctrl[d.key] = "sata%d" % d.busNumber
        elif isinstance(d, vim.vm.device.VirtualNVMEController):
            ctrl[d.key] = "nvme%d" % d.busNumber
        elif isinstance(d, vim.vm.device.VirtualIDEController):
            ctrl[d.key] = "ide%d" % d.busNumber
    disks = {}
    for d in devices:
        if not isinstance(d, vim.vm.device.VirtualDisk):
            continue
        inst = "%s:%d" % (ctrl.get(d.controllerKey, "scsi0"), d.unitNumber or 0)
        fname = getattr(d.backing, "fileName", "") or ""
        ds = fname[1:fname.index("]")] if fname.startswith("[") and "]" in fname else ""
        disks[inst] = {
            "label": d.deviceInfo.label if d.deviceInfo else inst, "instance": inst, "datastore": ds,
            "size_gb": round((d.capacityInKB or 0) / 1048576, 1),
            "read_ms": None, "write_ms": None, "read_ms_max": None, "write_ms_max": None,
            "read_iops": None, "write_iops": None, "read_mbps": None, "write_mbps": None,
        }
    if powered and disks:
        content = si.RetrieveContent()
        pm = content.perfManager
        key = content.about.instanceUuid
        ids = _disk_counter_ids.get(key)
        if ids is None:
            by_name = {(c.groupInfo.key, c.nameInfo.key, str(c.rollupType)): c.key for c in pm.perfCounter}
            ids = {k: by_name.get(("virtualDisk", n, r)) for k, (n, r) in _DISK_COUNTERS.items()}
            _disk_counter_ids[key] = ids
        want = {cid: k for k, cid in ids.items() if cid is not None}
        if want:
            spec = vim.PerformanceManager.QuerySpec(
                entity=vm, intervalId=20, maxSample=15,
                metricId=[vim.PerformanceManager.MetricId(counterId=cid, instance="*") for cid in want])
            res = pm.QueryPerf(querySpec=[spec])
            for r in (res or []):
                for series in (r.value or []):
                    k = want.get(series.id.counterId)
                    row = disks.get(series.id.instance)
                    vals = [v for v in (series.value or []) if v is not None and v >= 0]
                    if not k or row is None or not vals:
                        continue
                    avg = sum(vals) / len(vals)
                    if k in ("read_ms", "write_ms"):
                        row[k], row[k + "_max"] = round(avg, 1), round(max(vals), 1)
                    elif k in ("read_iops", "write_iops"):
                        row[k] = round(avg, 1)
                    else:
                        row[k.replace("kbps", "mbps")] = round(avg / 1024, 2)
    return {"found": True, "powered_on": powered, "disks": sorted(disks.values(), key=lambda x: x["instance"])}


def open_session(host: str, username: str, password: str):
    """Open a long-lived vCenter session (caller is responsible for Disconnect)."""
    return VCenterClient(host=host, username=username, password=password)._connect()
