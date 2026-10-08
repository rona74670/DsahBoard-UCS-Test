"""Infinidat InfiniBox REST API client."""
import requests
import urllib3
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import os as _os
# TLS: set INFRA_CA_BUNDLE to a CA bundle path, 'true' (system CAs), or leave
# unset/false to skip verification (lab self-signed certs default).
_CA = _os.getenv("INFRA_CA_BUNDLE", "").strip()
_TLS_VERIFY = (True if _CA.lower() in ("true", "1")
               else (_CA if _CA and _CA.lower() not in ("false", "0")
                     else False))


TB = 1024 ** 4
GB = 1024 ** 3


def _bytes_to_tb(b) -> float:
    try:
        return round(int(b) / TB, 2)
    except Exception:
        return 0.0


def _drive_type(d: dict, model: str, vendor: str) -> str:
    """Best-effort drive media type: API field first, then model/vendor hints."""
    for key in ("type", "drive_type", "media_type", "disk_type", "technology"):
        val = d.get(key)
        if val:
            return str(val).replace("_", " ").strip().upper()
    hint = f"{vendor} {model}".upper()
    for token, label in (("NVME", "NVMe"), ("SSD", "SSD"), ("FLASH", "SSD"),
                         ("NL-SAS", "NL-SAS"), ("NLSAS", "NL-SAS"), ("SAS", "SAS"),
                         ("SATA", "SATA")):
        if token in hint:
            return label
    return ""


class InfinidatClient:
    def __init__(self, host: str, username: str, password: str):
        self.host = host
        self.base = f"https://{host}/api/rest"
        self._session = requests.Session()
        self._session.auth = (username, password)
        self._session.verify = _TLS_VERIFY

    def _get(self, path: str, params: Optional[dict] = None):
        r = self._session.get(f"{self.base}/{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _get_all(self, path: str, params: Optional[dict] = None) -> list:
        """Paginate through all results automatically."""
        params = dict(params or {})
        params["page_size"] = 1000
        all_results: list = []
        page = 1
        while True:
            params["page"] = page
            data = self._get(path, params)
            results = data.get("result") or []
            all_results.extend(results)
            meta = data.get("metadata", {})
            if page >= meta.get("pages_total", 1):
                break
            page += 1
        return all_results

    # ── System ───────────────────────────────────────────────────────────
    def get_system(self) -> dict:
        data = self._get("system")
        return data.get("result", {})

    # ── Pools ────────────────────────────────────────────────────────────
    def get_pools(self) -> list:
        data = self._get("pools")
        pools = data.get("result") or []
        result = []
        for p in pools:
            phys_total = p.get("physical_capacity", 0)
            phys_alloc = p.get("allocated_physical_space", 0)
            phys_free  = p.get("free_physical_space", 0)
            virt_total = p.get("virtual_capacity", 0)
            virt_free  = p.get("free_virtual_space", 0)
            phys_pct   = round(phys_alloc / phys_total * 100, 1) if phys_total else 0
            result.append({
                "id":            p.get("id"),
                "name":          p.get("name", ""),
                "type":          p.get("type", "STANDARD"),
                "phys_total_tb": _bytes_to_tb(phys_total),
                "phys_used_tb":  _bytes_to_tb(phys_alloc),
                "phys_free_tb":  _bytes_to_tb(phys_free),
                "phys_pct":      phys_pct,
                "virt_total_tb": _bytes_to_tb(virt_total),
                "virt_free_tb":  _bytes_to_tb(virt_free),
                "virt_used_tb":  _bytes_to_tb(virt_total - virt_free),
                "data_reduction": round(p.get("data_reduction_ratio", 1), 2),
                "savings_tb":    _bytes_to_tb(p.get("capacity_savings", 0)),
            })
        return result

    # ── Volumes ──────────────────────────────────────────────────────────
    def get_volumes(self) -> dict:
        """Master (non-snapshot) volumes summary and per-pool breakdown."""
        vols = self._get_all("volumes", {"type": "MASTER"})
        by_pool: dict = {}
        total_size = 0
        total_used = 0
        for v in vols:
            pid   = v.get("pool_id")
            pname = v.get("pool_name", str(pid))
            if pid not in by_pool:
                by_pool[pid] = {"pool_id": pid, "pool_name": pname,
                                "count": 0, "total_size": 0, "total_used": 0}
            by_pool[pid]["count"]      += 1
            by_pool[pid]["total_size"] += v.get("size", 0)
            by_pool[pid]["total_used"] += v.get("used", 0)
            total_size += v.get("size", 0)
            total_used += v.get("used", 0)

        by_pool_list = [
            {**p,
             "total_size_tb": _bytes_to_tb(p["total_size"]),
             "total_used_tb": _bytes_to_tb(p["total_used"])}
            for p in by_pool.values()
        ]
        return {
            "total_count":   len(vols),
            "total_size_tb": _bytes_to_tb(total_size),
            "total_used_tb": _bytes_to_tb(total_used),
            "by_pool":       by_pool_list,
        }

    # ── Snapshots ────────────────────────────────────────────────────────
    def get_snapshots(self) -> dict:
        """All snapshots aggregated by pool + deletion candidates (oldest + biggest)."""
        import time
        now_ms = int(time.time() * 1000)

        snaps = self._get_all("volumes", {"type": "SNAPSHOT", "sort": "-created_at"})

        by_pool: dict = {}
        total_disk = 0

        all_detail = []
        has_disk_usage = any(s.get("disk_usage") is not None for s in snaps)

        all_detail = []
        for s in snaps:
            pid   = s.get("pool_id")
            pname = s.get("pool_name", str(pid))
            disk  = s.get("disk_usage") or 0 if has_disk_usage else 0

            if pid not in by_pool:
                by_pool[pid] = {"pool_id": pid, "pool_name": pname,
                                "count": 0, "total_disk": 0}
            by_pool[pid]["count"]      += 1
            by_pool[pid]["total_disk"] += disk
            total_disk += disk

            age_days = round((now_ms - (s.get("created_at") or now_ms)) / 86_400_000)
            all_detail.append({
                "id":             s.get("id"),
                "name":           s.get("name", "")[:80],
                "pool_name":      pname,
                "pool_id":        pid,
                "parent_size_tb": _bytes_to_tb(s.get("size", 0)),
                "disk_usage_tb":  _bytes_to_tb(disk),
                "disk_usage_raw": disk,
                "used_tb":        _bytes_to_tb(s.get("used", 0) or 0),
                "created_at":     s.get("created_at", 0),
                "age_days":       age_days,
                "policy":         s.get("snapshot_policy_name") or "",
                "write_protected": s.get("write_protected", False),
                "has_children":   s.get("has_children", False),
            })

        by_pool_list = sorted([
            {**p, "total_disk_tb": _bytes_to_tb(p["total_disk"])}
            for p in by_pool.values()
        ], key=lambda x: x["total_disk"], reverse=True)

        sort_key = "disk_usage_raw" if has_disk_usage else "used_tb"
        candidates = sorted(
            [s for s in all_detail if not s["write_protected"]],
            key=lambda s: (s["age_days"], s.get(sort_key, 0)),
            reverse=True
        )[:100]
        for s in candidates:
            del s["disk_usage_raw"]

        all_snaps_slim = [
            {
                "name":           s["name"],
                "pool_name":      s["pool_name"],
                "disk_usage_tb":  s["disk_usage_tb"],
                "used_tb":        s["used_tb"],
                "created_at":     s["created_at"],
                "age_days":       s["age_days"],
                "write_protected": s["write_protected"],
            }
            for s in all_detail
        ]

        return {
            "total_count":      len(snaps),
            "total_disk_tb":    _bytes_to_tb(total_disk),
            "disk_usage_avail": has_disk_usage,
            "by_pool":          by_pool_list,
            "old_candidates":   candidates,
            "all_snapshots":    all_snaps_slim,
        }

    # ── Health ───────────────────────────────────────────────────────────
    def get_health(self) -> dict:
        sys_data = self.get_system()
        health   = sys_data.get("health_state", {})

        nodes_raw = self._get("components/nodes").get("result") or []
        nodes = [
            {
                "name":       n.get("name", ""),
                "state":      n.get("state", ""),
                "model":      n.get("model", ""),
                "firmware":   n.get("firmware", ""),
                "bbu":        n.get("node_bbu_protection", ""),
                "bbu_pct":    n.get("protecting_bbu_charge_level", 0),
            }
            for n in nodes_raw
        ]
        return {
            "active_drives":    health.get("active_drives", 0),
            "failed_drives":    health.get("failed_drives", 0),
            "missing_drives":   health.get("missing_drives", 0),
            "phasing_out":      health.get("phasing_out_drives", 0),
            "bbu_charge":       health.get("bbu_aggregate_charge_percent", 0),
            "rebuild_1":        health.get("rebuild_1_inprogress", False),
            "rebuild_2":        health.get("rebuild_2_inprogress", False),
            "encryption":       health.get("encryption_enabled", False),
            "nodes":            nodes,
        }

    # ── Replicas ─────────────────────────────────────────────────────────
    def get_replicas(self) -> list:
        data  = self._get("replicas")
        reps  = data.get("result") or []
        import time
        now_ms = int(time.time() * 1000)
        result = []
        for r in reps:
            jobs = r.get("jobs") or []
            last_job = jobs[0] if jobs else {}
            last_sync_ms   = last_job.get("end_time")
            last_sync_ago  = round((now_ms - last_sync_ms) / 60000, 1) if last_sync_ms else None
            job_duration_s = round((last_job.get("end_time",0) - last_job.get("start_time",0)) / 1000, 1) if last_job else None
            result.append({
                "id":               r.get("id"),
                "state":            r.get("state", ""),
                "entity_type":      r.get("entity_type", ""),
                "role":             r.get("role") or "",
                "job_state":        r.get("job_state") or "",
                "last_sync_ms":     last_sync_ms,
                "last_sync_ago_min": last_sync_ago,
                "job_duration_s":   job_duration_s,
                "description":      r.get("description", ""),
                "remote_replica_id": r.get("remote_replica_id"),
                "concurrent":       r.get("concurrent_replica", False),
            })
        return result

    def get_replicas_detailed(self) -> list:
        """Replicas with entity names, remote host, RPO, and bytes transferred."""
        import time
        data  = self._get("replicas")
        reps  = data.get("result") or []
        now_ms = int(time.time() * 1000)

        # Build ID → name maps for volumes and CGs (best effort)
        vol_info: dict = {}
        cg_info:  dict = {}
        try:
            vols = self._get_all("volumes", {"type": "MASTER"})
            for v in vols:
                vol_info[v.get("id")] = {
                    "name":      v.get("name", ""),
                    "pool_name": v.get("pool_name", ""),
                    "size_tb":   _bytes_to_tb(v.get("size", 0)),
                }
        except Exception:
            pass
        try:
            raw = self._get("cgs", {"page_size": 500})
            for cg in (raw.get("result") or []):
                cg_info[cg.get("id")] = cg.get("name", "")
        except Exception:
            pass

        result = []
        for r in reps:
            jobs = r.get("jobs") or []
            last_job = jobs[0] if jobs else {}
            last_sync_ms  = last_job.get("end_time")
            last_sync_ago = round((now_ms - last_sync_ms) / 60000, 1) if last_sync_ms else None
            job_dur_s     = round((last_job.get("end_time", 0) - last_job.get("start_time", 0)) / 1000, 1) if last_job else None
            job_mb        = round((last_job.get("bytes_transferred") or 0) / 1_048_576, 1)

            entity_type      = r.get("entity_type", "")
            local_entity_id  = r.get("local_entity_id")
            entity_name      = ""
            pool_name        = ""
            entity_size_tb   = None

            if entity_type == "VOLUME" and local_entity_id:
                info = vol_info.get(local_entity_id, {})
                entity_name    = info.get("name", "")
                pool_name      = info.get("pool_name", "")
                entity_size_tb = info.get("size_tb")
            elif entity_type in ("CONS_GROUP", "CG") and local_entity_id:
                entity_name = cg_info.get(local_entity_id, "")

            if not entity_name:
                entity_name = r.get("description", "") or f"ID:{local_entity_id or r.get('id')}"

            remote_host = r.get("remote_host") or r.get("remote_replication_server") or ""
            link_type   = (r.get("link_type") or "").upper()

            # sync_interval in Infinidat REST API is in milliseconds
            sync_interval_ms = r.get("sync_interval") or 0
            rpo_value_raw    = r.get("rpo_value")

            if link_type == "SYNC" or sync_interval_ms == 0:
                rpo_min = 0          # synchronous replication â€” zero data loss
            elif sync_interval_ms:
                rpo_min = round(sync_interval_ms / 60000, 1)   # ms â†’ minutes
            elif rpo_value_raw:
                rpo_min = round(rpo_value_raw / 60, 1)         # assume seconds
            else:
                rpo_min = None

            rpo_ok = (last_sync_ago <= max(rpo_min, 1) * 1.2) if (rpo_min is not None and last_sync_ago is not None) else None

            result.append({
                "id":               r.get("id"),
                "state":            r.get("state", ""),
                "entity_type":      entity_type,
                "entity_name":      entity_name,
                "pool_name":        pool_name,
                "entity_size_tb":   entity_size_tb,
                "role":             r.get("role") or "",
                "job_state":        r.get("job_state") or "",
                "last_sync_ms":     last_sync_ms,
                "last_sync_ago_min": last_sync_ago,
                "job_duration_s":   job_dur_s,
                "job_mb":           job_mb,
                "description":      r.get("description", ""),
                "remote_host":      remote_host,
                "link_type":       link_type,
                "remote_replica_id": r.get("remote_replica_id"),
                "rpo_min":          rpo_min,
                "rpo_ok":           rpo_ok,
                "concurrent":       r.get("concurrent_replica", False),
            })
        return result

    # ── Top Volumes ───────────────────────────────────────────────────────
    def get_top_volumes(self) -> dict:
        """Top 10 largest volumes + volumes without snapshot policy."""
        data_top = self._get("volumes", {"type": "MASTER", "page_size": 10, "sort": "-size"})
        top = [
            {
                "name":       v.get("name", "")[:60],
                "pool_name":  v.get("pool_name", ""),
                "size_tb":    _bytes_to_tb(v.get("size", 0)),
                "used_tb":    _bytes_to_tb(v.get("used", 0)),
                "policy":     v.get("snapshot_policy_name") or "–",
                "mapped":     v.get("mapped", False),
                "provtype":   v.get("provtype", ""),
            }
            for v in (data_top.get("result") or [])
        ]

        all_vols = self._get_all("volumes", {"type": "MASTER"})
        unprotected = [
            {
                "name":      v.get("name", "")[:60],
                "pool_name": v.get("pool_name", ""),
                "size_tb":   _bytes_to_tb(v.get("size", 0)),
                "used_tb":   _bytes_to_tb(v.get("used", 0)),
                "mapped":    v.get("mapped", False),
            }
            for v in all_vols
            if not v.get("snapshot_policy_id") and not v.get("snapshot_policy_name")
        ]
        unprotected.sort(key=lambda x: x["size_tb"], reverse=True)

        return {
            "top10":       top,
            "unprotected": unprotected,
            "unprotected_count": len(unprotected),
            "total_count": len(all_vols),
        }

    # ── Consistency Groups ────────────────────────────────────────────────
    def get_cgs(self) -> list:
        data = self._get("cgs", {"page_size": 200})
        cgs  = data.get("result") or []
        result = []
        for cg in cgs:
            if cg.get("parent_id"):
                continue
            result.append({
                "id":            cg.get("id"),
                "name":          cg.get("name", ""),
                "type":          cg.get("type", ""),
                "is_replicated": cg.get("is_replicated", False),
                "pool_id":       cg.get("pool_id"),
                "has_children":  cg.get("has_children", False),
            })
        return result

    # ── Hosts Summary ─────────────────────────────────────────────────────
    def get_hosts(self) -> dict:
        hosts = self._get_all("hosts")
        by_type: dict = {}
        mapped_count = 0
        for h in hosts:
            htype = h.get("host_type", "OTHER")
            by_type[htype] = by_type.get(htype, 0) + 1
            if h.get("luns"):
                mapped_count += 1

        by_type_list = sorted(
            [{"type": k, "count": v} for k, v in by_type.items()],
            key=lambda x: x["count"], reverse=True
        )
        return {
            "total":         len(hosts),
            "mapped":        mapped_count,
            "unmapped":      len(hosts) - mapped_count,
            "by_type":       by_type_list,
        }

    # ── Events (enhanced) ─────────────────────────────────────────────────
    def get_events(self) -> list:
        data = self._get("events", {
            "page_size": 50,
            "sort":      "-timestamp",
            "visibility": "CUSTOMER",
        })
        evts = data.get("result") or []
        out  = []
        for e in evts:
            level = e.get("level", "INFO")
            if level not in ("WARNING", "ERROR", "CRITICAL"):
                continue
            out.append({
                "timestamp":   e.get("timestamp", 0),
                "level":       level,
                "description": e.get("description") or e.get("description_template", ""),
                "code":        e.get("code", ""),
            })
        return out

    # ── Performance ──────────────────────────────────────────────────
    def get_performance(self) -> dict:
        """Live IOPS/BW/latency via 2-second delta on system/stats."""
        import time

        def _sample():
            try:
                data = self._get("system/stats")
                ss   = data.get("result", {}).get("system_stats", [])
                tr = tw = wblk = rblk = 0
                nodes_out = []
                for node in ss:
                    cs   = node.get("cache_stats",     {})
                    ssds = node.get("ssd_device_stats", {}) or {}
                    ds   = node.get("drive_stats",      {}) or {}
                    ntr  = cs.get("total_reads",       0) or 0
                    ntw  = cs.get("total_writes",      0) or 0
                    nwb  = cs.get("num_blocks_written", 0) or 0
                    nrb  = ssds.get("total_block_reads", 0) or 0
                    lat  = ds.get("response_average",  None)
                    tr += ntr; tw += ntw; wblk += nwb; rblk += nrb
                    nodes_out.append({
                        "node_id": node.get("node_id"), "hostname": node.get("hostname",""),
                        "total_reads": ntr, "total_writes": ntw,
                        "write_blocks": nwb, "read_blocks": nrb,
                        "drive_lat_ms": lat,
                    })
                return {"total_reads":tr,"total_writes":tw,"write_blocks":wblk,"read_blocks":rblk}, nodes_out, time.time()
            except Exception:
                return None, [], time.time()

        s1, n1_list, t1 = _sample()
        time.sleep(1)
        s2, n2_list, t2 = _sample()
        dt = max(t2 - t1, 0.001)

        def iops(a, b, k): return round(max((b or {}).get(k,0)-(a or {}).get(k,0),0)/dt,1) if a and b else 0
        def blkmb(a, b, k): return round(max((b or {}).get(k,0)-(a or {}).get(k,0),0)*512/dt/1_048_576,1) if a and b else 0.0

        node_states: dict = {}
        try:
            for n in (self._get("components/nodes").get("result") or []):
                node_states[n.get("name","")] = n.get("state","")
        except Exception:
            pass

        nodes_out = []
        drive_lats = []
        for a, b in zip(n1_list, n2_list):
            name = a.get("hostname", f"node-{a.get('node_id','?')}")
            lat  = b.get("drive_lat_ms")
            if lat is not None:
                drive_lats.append(lat)
            nodes_out.append({
                "name":          name,
                "state":         node_states.get(name, "ACTIVE"),
                "read_iops":     iops(a, b, "total_reads"),
                "write_iops":    iops(a, b, "total_writes"),
                "read_bw_mbps":  blkmb(a, b, "read_blocks"),
                "write_bw_mbps": blkmb(a, b, "write_blocks"),
                "drive_lat_ms":  round(lat, 1) if lat is not None else None,
            })

        avg_lat = round(sum(drive_lats)/len(drive_lats), 1) if drive_lats else None
        ri = iops(s1, s2, "total_reads")
        wi = iops(s1, s2, "total_writes")
        return {
            "total_read_iops":     ri,
            "total_write_iops":    wi,
            "total_iops":          round(ri + wi, 1),
            "total_read_bw_mbps":  blkmb(s1, s2, "read_blocks"),
            "total_write_bw_mbps": blkmb(s1, s2, "write_blocks"),
            "avg_drive_lat_ms":    avg_lat,
            "nodes":               nodes_out,
        }

    # ── Hardware faults ───────────────────────────────────────────────
    def get_hardware(self) -> dict:
        """Drive and FC port status."""
        drives: list = []
        fc_ports: list = []

        try:
            comp = self._get("components").get("result", {})

            for enc in (comp.get("enclosures") or []):
                enc_id = enc.get("id", "")
                enc_idx = enc.get("index", enc.get("enclosure_index", enc_id))
                for d in (enc.get("drives") or []):
                    model = (d.get("model") or d.get("product_id") or "").strip()
                    vendor = (d.get("vendor") or "").strip()
                    drives.append({
                        "id":      d.get("id"),
                        "index":   d.get("drive_index"),
                        "enc":     enc_id,
                        "enc_index": enc_idx,
                        "slot":    d.get("drive_index"),
                        "state":   d.get("state", "UNKNOWN"),
                        "model":   model,
                        "vendor":  vendor,
                        "size_tb": _bytes_to_tb(d.get("bytes_capacity") or 0),
                        "serial":  (d.get("serial_number") or "").strip(),
                        "type":    _drive_type(d, model, vendor),
                    })

            for node in (comp.get("nodes") or []):
                node_name = node.get("name", "")
                for p in (node.get("fc_ports") or []):
                    link = p.get("link_state") or p.get("state", "UNKNOWN")
                    fc_ports.append({
                        "id":        p.get("id"),
                        "name":      p.get("name") or f"{node_name}/fc{p.get('system_interface_port_number','')}",
                        "wwpn":      p.get("wwpn", ""),
                        "node":      node_name,
                        "state":     link,
                        "speed_mbps": p.get("connection_speed") or p.get("max_speed"),
                        "enabled":   p.get("enabled", True),
                    })
        except Exception:
            pass

        failed_drives = [d for d in drives if d["state"] not in ("ACTIVE", "PHASING_IN", "TESTING", "AVAILABLE")]
        fc_down = [p for p in fc_ports if p.get("enabled") and p["state"] not in ("LINK_UP", "OK", None, "UNKNOWN")]

        return {
            "drives":        drives,
            "failed_drives": failed_drives,
            "fc_ports":      fc_ports,
            "fc_down":       fc_down,
            "summary": {
                "total_drives":   len(drives),
                "failed_drives":  len(failed_drives),
                "total_fc_ports": len(fc_ports),
                "fc_down":        len(fc_down),
            },
        }

    # ── Combined summary ─────────────────────────────────────────────────
    def get_summary(self) -> dict:
        sys  = self.get_system()
        cap  = sys.get("capacity", {})
        ec   = sys.get("entity_counts", {})
        hs   = sys.get("health_state", {})

        pools = self.get_pools()
        health = self.get_health()
        nodes = health.get("nodes") or []
        model = next((n.get("model", "") for n in nodes if n.get("model")), "")

        phys_total = cap.get("total_physical_capacity", 0)
        phys_free  = cap.get("free_physical_space", 0)
        phys_used  = phys_total - phys_free
        virt_total = cap.get("total_virtual_capacity", 0)
        virt_free  = cap.get("free_virtual_space", 0)
        virt_used  = virt_total - virt_free

        return {
            "system": {
                "name":    sys.get("system_name") or self.host,
                "version": sys.get("version", ""),
                "model":   model,
                "host":    self.host,
            },
            "capacity": {
                "phys_total_tb":    _bytes_to_tb(phys_total),
                "phys_used_tb":     _bytes_to_tb(phys_used),
                "phys_free_tb":     _bytes_to_tb(phys_free),
                "phys_pct":         round(phys_used / phys_total * 100, 1) if phys_total else 0,
                "virt_total_tb":    _bytes_to_tb(virt_total),
                "virt_used_tb":     _bytes_to_tb(virt_used),
                "virt_free_tb":     _bytes_to_tb(virt_free),
                "virt_pct":         round(virt_used / virt_total * 100, 1) if virt_total else 0,
                "data_reduction":   round(cap.get("data_reduction_ratio", 1), 2),
                "savings_tb":       _bytes_to_tb(cap.get("total_capacity_savings", 0)),
            },
            "counts": {
                "pools":     ec.get("pools", 0),
                "volumes":   ec.get("volumes", 0),
                "snapshots": ec.get("volume_snapshots", 0),
                "hosts":     ec.get("hosts", 0),
                "replicas":  ec.get("replicas", 0),
                "snap_groups": ec.get("snapshot_groups", 0),
            },
            "health":  health,
            "pools":   pools,
        }
