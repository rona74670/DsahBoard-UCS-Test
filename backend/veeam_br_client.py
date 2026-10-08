"""
Veeam B&R REST API client (individual backup server, port 9419).
Auth: OAuth2 Bearer, x-api-version: 1.0-rev1
"""
import os, requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import os as _os
# TLS: set INFRA_CA_BUNDLE to a CA bundle path, 'true' (system CAs), or leave
# unset/false to skip verification (lab self-signed certs default).
_CA = _os.getenv("INFRA_CA_BUNDLE", "").strip()
_TLS_VERIFY = (True if _CA.lower() in ("true", "1")
               else (_CA if _CA and _CA.lower() not in ("false", "0")
                     else False))


_TIMEOUT = 30
_API_VER = "1.0-rev1"


def _get_pass():
    return os.getenv("VEEAM_PASS", "")


class VeeamBRClient:
    """Veeam Backup & Replication REST client (OAuth2, port 9419)."""

    def __init__(self, host: str, username: str, password: str = ""):
        h = host.rstrip("/").replace("https://", "").replace("http://", "")
        if ":" not in h.split("/")[-1]:
            h = f"{h}:9419"
        self.host     = f"https://{h}"
        self.username = username
        self.password = password or _get_pass()
        self._token: str | None = None
        self._auth_failed: bool = False

    def _get_token(self) -> None:
        if self._auth_failed:
            raise RuntimeError("Auth previously failed — skipping retry")
        r = requests.post(
            f"{self.host}/api/oauth2/token",
            data={"grant_type": "password",
                  "username":   self.username,
                  "password":   self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept":       "application/json",
                     "x-api-version": _API_VER},
            verify=_TLS_VERIFY, timeout=_TIMEOUT,
        )
        if r.status_code == 401:
            self._auth_failed = True
            r.raise_for_status()
        r.raise_for_status()
        self._token = r.json()["access_token"]

    def _hdrs(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept":        "application/json",
            "x-api-version": _API_VER,
        }

    def _get(self, path: str, params: dict | None = None):
        if not self._token:
            self._get_token()
        url = f"{self.host}/api/v1/{path.lstrip('/')}"
        r = requests.get(url, headers=self._hdrs(), params=params,
                         verify=_TLS_VERIFY, timeout=_TIMEOUT)
        if r.status_code == 401:
            self._get_token()
            r = requests.get(url, headers=self._hdrs(), params=params,
                             verify=_TLS_VERIFY, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _list(self, path: str, params: dict | None = None) -> list:
        data = self._get(path, params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data", [])
        return []

    # ── Public API ────────────────────────────────────────────────────────────

    def ping(self) -> dict:
        try:
            self._get_token()
            return {"status": "ok", "host": self.host, "auth": "oauth2"}
        except Exception as e:
            return {"status": "error", "host": self.host, "error": str(e)}

    def get_jobs(self) -> list:
        try:
            jobs   = self._list("jobs")
            states = {s["id"]: s for s in self._list("jobs/states")}
            return [_norm_job(j, states.get(j.get("id", ""))) for j in jobs]
        except Exception:
            return []

    def get_sessions(self, limit: int = 100) -> list:
        try:
            # Try limit first (works on Veeam 12.x), then pageSize (older), then top.
            # Stop immediately on auth failure to avoid account lockout.
            for params in [{"limit": limit}, {"pageSize": limit}, {"top": limit}]:
                if self._auth_failed:
                    break
                try:
                    items = self._list("sessions", params)
                    if items:
                        return [_norm_session(s) for s in items]
                except RuntimeError:
                    break   # auth failure — don't retry
                except Exception:
                    continue
            return []
        except Exception:
            return []

    def get_repositories(self) -> list:
        try:
            repos = self._list("backupInfrastructure/repositories")
            if not repos:
                return []
            # Fetch capacity from /states endpoint (Veeam 12.x standard)
            try:
                states = {s["id"]: s
                          for s in self._list("backupInfrastructure/repositories/states")}
            except Exception:
                states = {}
            # Merge state (capacity) data into repo objects
            merged = [{**r, **states.get(r.get("id", ""), {})} for r in repos]
            result = [_norm_repo(m) for m in merged]
            # If every repo still has 0 capacity, try per-repo detail endpoint
            if all(r["total_gb"] == 0 for r in result):
                detail_result = []
                for r, raw in zip(result, repos):
                    try:
                        det = self._get(
                            f"backupInfrastructure/repositories/{raw.get('id', '')}")
                        detail_result.append(_norm_repo({**raw, **det}))
                    except Exception:
                        detail_result.append(r)
                return detail_result
            return result
        except Exception:
            return []

    def get_backup_objects(self, limit: int = 1000) -> list:
        try:
            items = self._list("backupObjects", {"limit": limit})
            return [_norm_backup_object(o) for o in items]
        except Exception:
            return []

    def get_backups_map(self) -> dict:
        """backupId -> raw /backups entry (job/backup name, type, repository)."""
        try:
            return {b.get("id"): b for b in self._list("backups", {"limit": 1000}) if b.get("id")}
        except Exception:
            return {}

    def get_raw_sessions(self, since_iso: str, limit: int = 1000) -> list:
        """Raw job sessions created after since_iso (name, creationTime, endTime, id)."""
        try:
            return self._list("sessions", {"limit": limit, "createdAfterFilter": since_iso})
        except Exception:
            return []

    def get_task_sessions(self, session_id: str) -> list:
        """Per-VM task sessions of one job session (name, creationTime, endTime)."""
        try:
            return self._list(f"sessions/{session_id}/taskSessions", {"limit": 1000})
        except Exception:
            return []

    def get_restore_points(self, object_id: str, limit: int = 300) -> list:
        """Restore points of one backup object (VM), newest first: [{time, type}]."""
        try:
            items = self._list(f"backupObjects/{object_id}/restorePoints",
                               {"limit": limit, "orderColumn": "CreationTime", "orderAsc": "false"})
            return [{"time": o.get("creationTime", ""), "type": o.get("type", ""), "backup_id": o.get("backupId", ""), "raw": o} for o in items]
        except Exception:
            return []

    def get_summary(self) -> dict:
        # Fail fast on auth/connectivity issues so callers don't mistake
        # unreachable upstream servers for valid empty datasets.
        self._get_token()

        jobs     = self.get_jobs()
        repos    = self.get_repositories()
        sessions = self.get_sessions(limit=50)

        ok      = sum(1 for j in jobs if j["last_result"] in ("success", "succeeded"))
        warn    = sum(1 for j in jobs if j["last_result"] == "warning")
        failed  = sum(1 for j in jobs if j["last_result"] in ("failed", "error"))
        running = sum(1 for j in jobs if j["status"] in ("running", "starting"))

        repo_total = sum(r["total_gb"] for r in repos)
        repo_free  = sum(r["free_gb"]  for r in repos)
        repo_used  = repo_total - repo_free

        return {
            "server":          self.host,
            "jobs_total":      len(jobs),
            "jobs_ok":         ok,
            "jobs_warn":       warn,
            "jobs_failed":     failed,
            "jobs_running":    running,
            "repo_total_gb":   round(repo_total, 1),
            "repo_used_gb":    round(repo_used, 1),
            "repo_free_gb":    round(repo_free, 1),
            "repo_pct":        round(repo_used / repo_total * 100, 1) if repo_total else 0,
            "jobs":            jobs,
            "repos":           repos,
            "recent_sessions": sessions,
        }


# ── Normalizers ───────────────────────────────────────────────────────────────

def _norm_job(j: dict, state: dict | None) -> dict:
    s = state or {}
    return {
        "id":          j.get("id", ""),
        "name":        j.get("name", ""),
        "type":        j.get("type", ""),
        "enabled":     j.get("isEnabled", True),
        "status":      (s.get("status") or "").lower(),
        "last_result": (s.get("lastResult") or "").lower(),
        "last_run":    s.get("lastRun") or s.get("lastEndTime", ""),
    }

def _norm_session(s: dict) -> dict:
    # resourceReference may be a dict like {"name": "JobName", "id": "..."}
    ref = s.get("resourceReference") or {}
    ref_name = ref.get("name", "") if isinstance(ref, dict) else ""
    ref_id   = ref.get("id",   "") if isinstance(ref, dict) else ""
    # result can be a nested dict {"result": "Success", ...} or a plain string
    raw_result = s.get("result") or s.get("status") or ""
    if isinstance(raw_result, dict):
        raw_result = raw_result.get("result") or ""
    return {
        "id":         s.get("id", ""),
        "job_id":     s.get("jobId") or s.get("resourceId") or ref_id or "",
        "job_name":   s.get("jobName") or ref_name or s.get("name") or "",
        "status":     str(raw_result).lower(),
        "state":      (s.get("state") or "").lower(),
        "start_time": s.get("creationTime", ""),
        "end_time":   s.get("endTime", ""),
    }

def _norm_backup_object(o: dict) -> dict:
    pts = o.get("restorePointsCount", 0) or 0
    return {
        "id":             o.get("id", ""),
        "name":           o.get("name", ""),
        "type":           o.get("type", ""),
        "platform":       o.get("platformName", ""),
        "vi_type":        o.get("viType", ""),
        "path":           o.get("path", ""),
        "restore_points": pts,
        "protected":      pts > 0,
    }

def _norm_repo(r: dict) -> dict:
    # Fields already in GB (suffixed with GB — no byte conversion needed)
    cap_gb  = (r.get("capacityGB")   or r.get("CapacityGB")   or
               r.get("totalSpaceGB") or r.get("TotalSpaceGB") or None)
    free_gb = (r.get("freeGB")       or r.get("freeSpaceGB")  or
               r.get("FreeSpaceGB")  or r.get("availableSpaceGB") or None)

    if cap_gb is None:
        # Fields in bytes — convert to GB
        cap_b  = (r.get("capacity")  or r.get("totalSpace")  or
                  r.get("TotalSpace") or 0)
        free_b = (r.get("freeSpace") or r.get("FreeSpace")   or
                  r.get("availableSpace") or 0)
        if isinstance(cap_b, (int, float)) and cap_b > 1_000_000:
            cap_gb  = round(cap_b  / 1024**3, 1)
            free_gb = round(free_b / 1024**3, 1)
        else:
            cap_gb  = float(cap_b  or 0)
            free_gb = float(free_b or 0)

    cap  = float(cap_gb  or 0)
    free = float(free_gb or 0)
    return {
        "id":       r.get("id", ""),
        "name":     r.get("name", ""),
        "host":     r.get("hostName") or r.get("host") or r.get("serverName", ""),
        "type":     r.get("type", ""),
        "path":     r.get("path", ""),
        "total_gb": cap,
        "free_gb":  free,
        "used_gb":  round(cap - free, 1),
        "pct":      round((cap - free) / cap * 100, 1) if cap else 0,
    }