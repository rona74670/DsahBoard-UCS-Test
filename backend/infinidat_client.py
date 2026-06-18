"""Infinidat InfiniBox REST API client."""
import requests
import urllib3
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TB = 1024 ** 4
GB = 1024 ** 3


def _bytes_to_tb(b) -> float:
    try:
        return round(int(b) / TB, 2)
    except Exception:
        return 0.0


class InfinidatClient:
    def __init__(self, host: str, username: str, password: str):
        self.host = host
        self.base = f"https://{host}/api/rest"
        self._session = requests.Session()
        self._session.auth = (username, password)
        self._session.verify = False

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
        total_disk = 0   # sum of disk_usage — actual physical delta each snapshot occupies

        all_detail = []
        has_disk_usage = any(s.get("disk_usage") is not None for s in snaps)

        all_detail = []
        for s in snaps:
            pid   = s.get("pool_id")
            pname = s.get("pool_name", str(pid))
            # disk_usage = physical delta unique to this snapshot — only available in InfiniBox v8+
            # On v7.x this field is None; 'used' is the full logical size (not delta) — misleading
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

        # Best deletion candidates: unprotected, sorted by age desc then relevant size desc
        sort_key = "disk_usage_raw" if has_disk_usage else "used_tb"
        candidates = sorted(
            [s for s in all_detail if not s["write_protected"]],
            key=lambda s: (s["age_days"], s.get(sort_key, 0)),
            reverse=True
        )[:100]
        for s in candidates:
            del s["disk_usage_raw"]

        # Slim list for full-browser table (name, pool, size, date, lock)
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
            "disk_usage_avail": has_disk_usage,   # False on firmware v7.x
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

    # ── Top Volumes ───────────────────────────────────────────────────────
    def get_top_volumes(self) -> dict:
        """Top 10 largest volumes + volumes without snapshot policy."""
        # Largest by provisioned size (only sort that API supports)
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

        # All master volumes to find unprotected ones
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
            # Only show top-level CGs (parent_id == null means it's a master, not a snapshot)
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

    # ── Combined summary ─────────────────────────────────────────────────
    def get_summary(self) -> dict:
        sys  = self.get_system()
        cap  = sys.get("capacity", {})
        ec   = sys.get("entity_counts", {})
        hs   = sys.get("health_state", {})

        pools = self.get_pools()
        health = self.get_health()

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
