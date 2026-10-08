"""
Veeam Enterprise Manager REST API client.
REST API port: 9398  (web UI is on 9443 — different service)
Auth: POST /api/sessionMngr/?v=v1_6  with Basic creds → X-RestSvcSessionId header
"""

import os
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import os as _os
# TLS: set INFRA_CA_BUNDLE to a CA bundle path, 'true' (system CAs), or leave
# unset/false to skip verification (lab self-signed certs default).
_CA = _os.getenv("INFRA_CA_BUNDLE", "").strip()
_TLS_VERIFY = (True if _CA.lower() in ("true", "1")
               else (_CA if _CA and _CA.lower() not in ("false", "0")
                     else False))


_TIMEOUT      = 60   # Veeam EM can be slow on large queries
_TIMEOUT_SESS = 90   # session queries need extra time
_API_VER = "v1_6"


def _get_pass() -> str:
    return os.getenv("VEEAM_PASS", "")


class VeeamEMClient:
    """Veeam Enterprise Manager REST client (session-based Basic auth, port 9398)."""

    def __init__(self, host: str, username: str, password: str = ""):
        h = host.rstrip("/")
        # Strip any existing scheme so we can rebuild it
        h = h.replace("https://", "").replace("http://", "")
        # Replace web UI port 9443 with REST API port 9398 if present
        if ":9443" in h:
            h = h.replace(":9443", ":9398")
        # Ensure REST API port is set
        if ":" not in h.split("/")[-1]:
            h = f"{h}:9398"
        self.host = f"https://{h}"
        self.username = username
        self.password = password or _get_pass()
        self._session_id: str | None = None

    def _base(self) -> str:
        return f"{self.host}/api"

    # ── Session management ────────────────────────────────────────────────────

    def _create_session(self) -> None:
        url = f"{self._base()}/sessionMngr/?v={_API_VER}"
        r = requests.post(
            url,
            auth=(self.username, self.password),
            headers={"Accept": "application/json"},
            verify=_TLS_VERIFY,
            timeout=_TIMEOUT,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(
                f"Veeam session creation failed: HTTP {r.status_code} — {r.text[:200]}"
            )
        self._session_id = r.headers.get("X-RestSvcSessionId", "")

    def _hdrs(self) -> dict:
        return {
            "Accept": "application/json",
            "X-RestSvcSessionId": self._session_id or "",
        }

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str) -> dict | list:
        if not self._session_id:
            self._create_session()
        url = f"{self._base()}/{path.lstrip('/')}"
        r = requests.get(url, headers=self._hdrs(), verify=_TLS_VERIFY, timeout=_TIMEOUT)
        if r.status_code == 401:
            self._create_session()
            r = requests.get(url, headers=self._hdrs(), verify=_TLS_VERIFY, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _query(self, entity_type: str, page_size: int = 100) -> list:
        """Veeam EM query API — /api/query?type=X&format=Entities&pageSize=N"""
        if not self._session_id:
            self._create_session()
        url = (f"{self._base()}/query"
               f"?type={entity_type}&format=Entities&pageSize={page_size}")
        r = requests.get(url, headers=self._hdrs(), verify=_TLS_VERIFY, timeout=_TIMEOUT_SESS)
        if r.status_code == 401:
            self._create_session()
            r = requests.get(url, headers=self._hdrs(), verify=_TLS_VERIFY, timeout=_TIMEOUT_SESS)
        r.raise_for_status()
        data = r.json()
        # Veeam EM uses lowercase keys: {"entities": {"replicas": {"replicas": [...]}, ...}}
        # Try lowercase first, then PascalCase for older versions
        entities = data.get("entities") or data.get("Entities") or {}
        if not isinstance(entities, dict):
            return []
        # Walk all non-None values to find a list of entity objects
        for key, inner in entities.items():
            if inner is None:
                continue
            if isinstance(inner, list):
                return inner
            if isinstance(inner, dict):
                for v in inner.values():
                    if isinstance(v, list):
                        return v
        return []

    # ── Public API ────────────────────────────────────────────────────────────

    def ping(self) -> dict:
        try:
            self._create_session()
            return {
                "status":      "ok",
                "host":        self.host,
                "http_status": 201,
                "auth_method": "session",
                "session_id":  (self._session_id or "")[:8] + "...",
            }
        except Exception as e:
            return {"status": "error", "host": self.host, "error": str(e)}

    def probe(self) -> dict:
        """Diagnostic: create session then try all known API paths."""
        results = {"host": self.host, "auth_method": "session", "endpoints": {}}
        try:
            self._create_session()
            results["session"] = "ok"
        except Exception as e:
            results["session"] = f"FAILED: {e}"
            return results

        paths = [
            "/backupServers",
            "/jobs",
            "/repositories",
            "/jobSessions",
            "/replicas",
            "/query?type=Job&format=Entities&pageSize=3",
            "/query?type=BackupJobSession&format=Entities&pageSize=100",
            "/query?type=Repository&format=Entities&pageSize=3",
            "/query?type=BackupServer&format=Entities&pageSize=3",
            "/query?type=Replica&format=Entities&pageSize=10",
            "/query?type=ReplicaJobSession&format=Entities&pageSize=10",
            "/query?type=FailoverPlan&format=Entities&pageSize=10",
            "/query?type=FailoverPlanSession&format=Entities&pageSize=10",
        ]
        for path in paths:
            url = f"{self._base()}/{path.lstrip('/')}"
            try:
                r = requests.get(url, headers=self._hdrs(),
                                 verify=_TLS_VERIFY, timeout=_TIMEOUT)
                try:
                    body = r.json()
                except Exception:
                    body = r.text[:300]
                results["endpoints"][path] = {
                    "status": r.status_code,
                    "sample": body if not isinstance(body, (dict, list))
                              else (body[:2] if isinstance(body, list)
                                    else {k: str(v)[:100] for k, v in list(body.items())[:4]}),
                }
            except Exception as e:
                results["endpoints"][path] = {"error": str(e)}
        return results

    def get_backup_servers(self) -> list:
        try:
            # Direct endpoint returns refs; follow each to get details
            data = self._get("/backupServers")
            refs = (data if isinstance(data, list)
                    else data.get("refs") or data.get("Refs") or [])
            if refs:
                return [_norm_server_ref(s) for s in refs]
            recs = self._query("BackupServer")
            return [_norm_server(s) for s in recs]
        except Exception:
            return []

    def get_job_sessions(self, limit: int = 100) -> list:
        """Returns the most recent N job sessions."""
        try:
            recs = self._query("BackupJobSession", page_size=limit)
            return [_norm_session(s) for s in recs]
        except Exception:
            return []

    def get_jobs(self) -> list:
        """
        Try direct /api/jobs first; fall back to deriving jobs from recent sessions
        (needed when the service account lacks access to the jobs endpoint).
        """
        try:
            recs = self._query("Job")
            if recs:
                return [_norm_job(j) for j in recs]
        except Exception:
            pass
        try:
            data = self._get("/jobs")
            recs = data if isinstance(data, list) else data.get("Refs", [])
            if recs:
                return [_norm_job(j) for j in recs]
        except Exception:
            pass
        # Fallback: derive unique jobs from recent sessions
        return self._jobs_from_sessions()

    def _jobs_from_sessions(self) -> list:
        """Infer job list from the most recent sessions (last-run status per job)."""
        try:
            sessions = self.get_job_sessions(limit=100)
            seen: dict = {}
            for s in sessions:
                name = s.get("job_name", "")
                if not name or name in seen:
                    continue
                seen[name] = {
                    "id":          s.get("job_id", ""),
                    "name":        name,
                    "type":        "",
                    "state":       s.get("state", ""),
                    "last_status": s.get("status", ""),
                    "last_run":    s.get("end_time") or s.get("start_time", ""),
                    "server_name": "",
                }
            return list(seen.values())
        except Exception:
            return []

    def get_repositories(self) -> list:
        try:
            recs = self._query("Repository")
            if recs:
                return [_norm_repo(r) for r in recs]
            data = self._get("/repositories")
            refs = (data if isinstance(data, list)
                    else data.get("refs") or data.get("Refs") or [])
            return [_norm_repo(r) for r in refs]
        except Exception:
            return []

    def get_replicas(self) -> list:
        """Fetch Veeam replication jobs from Enterprise Manager, one entry per unique UID."""
        try:
            recs = self._query("Replica", page_size=1000)
            # Deduplicate by uid — query returns one entry per restore point
            seen: dict = {}
            for r in recs:
                uid = r.get("uid") or r.get("UID") or r.get("objectId", "")
                if uid and uid not in seen:
                    seen[uid] = r
            return [_norm_replica(r) for r in seen.values()]
        except Exception:
            return []

    def get_replica_sessions(self, limit: int = 200) -> list:
        """Fetch recent replication job sessions."""
        try:
            recs = self._query("ReplicaJobSession", page_size=limit)
            return [_norm_replica_session(s) for s in recs]
        except Exception:
            return []

    def get_dr_summary(self) -> dict:
        """Fetch DR/replication summary: unique replica jobs + recent sessions."""
        replicas = self.get_replicas()
        sessions = self.get_replica_sessions(limit=500)

        # Merge last session per job by name (replica.name == session.job_name)
        last_by_name: dict = {}
        for s in sessions:
            jname = s.get("job_name", "")
            if jname and jname not in last_by_name:
                last_by_name[jname] = s

        for rep in replicas:
            ls = last_by_name.get(rep.get("name", ""))
            if ls:
                rep["last_status"] = ls.get("status", "")
                rep["last_run"]    = ls.get("end_time") or ls.get("start_time", "")
                rep["last_server"] = ls.get("server_name", rep.get("server_name", ""))

        ok      = sum(1 for r in replicas if r.get("last_status", "").lower() in ("success", "succeeded"))
        warn    = sum(1 for r in replicas if r.get("last_status", "").lower() == "warning")
        failed  = sum(1 for r in replicas if r.get("last_status", "").lower() in ("failed", "error"))
        unknown = len(replicas) - ok - warn - failed

        return {
            "replicas_total":   len(replicas),
            "replicas_ok":      ok,
            "replicas_warn":    warn,
            "replicas_failed":  failed,
            "replicas_unknown": unknown,
            "replicas":         replicas,
            "recent_sessions":  sessions[:100],
        }

    def get_summary(self) -> dict:
        servers  = self.get_backup_servers()
        repos    = self.get_repositories()
        sessions = self.get_job_sessions(limit=100)
        jobs     = self.get_jobs()  # may reuse sessions internally

        last_by_job: dict = {}
        for s in sessions:
            jid = s.get("job_id", "")
            if jid and jid not in last_by_job:
                last_by_job[jid] = s

        for j in jobs:
            ls = last_by_job.get(j.get("id", ""))
            if ls:
                j["last_run"]    = ls.get("end_time") or ls.get("start_time")
                j["last_status"] = ls.get("status", j.get("last_status", ""))

        ok      = sum(1 for j in jobs if j.get("last_status", "").lower() in ("success", "succeeded"))
        warn    = sum(1 for j in jobs if j.get("last_status", "").lower() == "warning")
        failed  = sum(1 for j in jobs if j.get("last_status", "").lower() in ("failed", "error"))
        running = sum(1 for j in jobs if j.get("state", "").lower() in ("running", "working", "starting"))

        repo_total = sum(r.get("total_gb", 0) for r in repos)
        repo_free  = sum(r.get("free_gb",  0) for r in repos)
        repo_used  = repo_total - repo_free

        return {
            "servers_count":   len(servers),
            "jobs_total":      len(jobs),
            "jobs_ok":         ok,
            "jobs_warn":       warn,
            "jobs_failed":     failed,
            "jobs_running":    running,
            "repo_total_gb":   round(repo_total, 1),
            "repo_used_gb":    round(repo_used,  1),
            "repo_free_gb":    round(repo_free,  1),
            "repo_pct":        round(repo_used / repo_total * 100, 1) if repo_total else 0,
            "servers":         servers,
            "jobs":            jobs,
            "repos":           repos,
            "recent_sessions": sessions[:50],
        }


# ── Normalizers ───────────────────────────────────────────────────────────────

def _norm_server(s: dict) -> dict:
    return {
        "id":      s.get("UID") or s.get("Id") or s.get("ObjectId", ""),
        "name":    s.get("Name") or s.get("serverName", ""),
        "version": s.get("Version") or s.get("version", ""),
        "type":    s.get("Type") or s.get("type", ""),
    }

def _norm_server_ref(s: dict) -> dict:
    """Normalize a backup server ref object (from /backupServers direct endpoint)."""
    links = s.get("links") or s.get("Links") or []
    href = links[0].get("href", "") if links else ""
    name = s.get("Name") or s.get("name") or ""
    if not name:
        # Extract name from href: .../backupServers/<uid>  → use uid as name fallback
        parts = href.rstrip("/").split("/")
        name = parts[-1] if parts else href
    return {
        "id":      s.get("UID") or s.get("uid") or s.get("ObjectId", ""),
        "name":    name,
        "version": s.get("Version") or s.get("version", ""),
        "type":    s.get("Type") or s.get("type", ""),
        "href":    href,
    }

def _norm_replica(r: dict) -> dict:
    """Normalize a Replica entity from /query?type=Replica.

    The 'name' field = job name (not VM name).
    Links contain repository, backup server, and the entity detail URL.
    One entry per restore point is returned by the API — callers must dedup by uid.
    """
    uid = r.get("uid") or r.get("UID") or r.get("objectId", "")
    replica_id = uid.split(":")[-1] if ":" in uid else uid

    # Parse named links
    links = r.get("links") or []
    server_name = ""
    repo_name = ""
    entity_href = r.get("href", "")
    for lnk in links:
        ltype = lnk.get("type", "")
        if ltype == "BackupServerReference":
            server_name = lnk.get("name", "")
        elif ltype == "RepositoryReference":
            repo_name = lnk.get("name", "")

    return {
        "id":           replica_id,
        "uid":          uid,
        "name":         r.get("name") or r.get("Name", ""),  # = job name
        "platform":     r.get("platform") or r.get("Platform", "VMware"),
        "server_name":  server_name,
        "repo_name":    repo_name,
        "entity_href":  entity_href,
        "restore_points": 0,
        "last_status":  "",
        "last_run":     "",
        "source_host":  "",
        "target_host":  "",
    }

def _norm_replica_session(s: dict) -> dict:
    """Normalize a ReplicaJobSession entity from /query?type=ReplicaJobSession."""
    uid     = s.get("uid") or s.get("UID") or s.get("objectId", "")
    job_uid = s.get("jobUid") or s.get("JobUid") or ""
    job_id  = job_uid.split(":")[-1] if ":" in job_uid else job_uid
    links   = s.get("links") or []
    server_name = next((l.get("name","") for l in links if l.get("type")=="BackupServerReference"), "")
    return {
        "id":          uid.split(":")[-1] if ":" in uid else uid,
        "uid":         uid,
        "job_id":      job_id,
        "job_uid":     job_uid,
        "job_name":    s.get("jobName") or s.get("JobName", ""),
        "status":      (s.get("result") or s.get("Result") or "").lower(),
        "state":       (s.get("state") or s.get("State") or "").lower(),
        "start_time":  s.get("creationTimeUTC") or s.get("CreationTime", ""),
        "end_time":    s.get("endTimeUTC") or s.get("EndTime", ""),
        "is_retry":    bool(s.get("isRetry", False)),
        "progress":    s.get("progress") or 0,
        "failure_msg": s.get("failureMessage") or "",
        "server_name": server_name,
    }

def _norm_job(j: dict) -> dict:
    return {
        "id":          j.get("UID") or j.get("Id") or j.get("ObjectId", ""),
        "name":        j.get("Name") or j.get("JobName", ""),
        "type":        j.get("JobType") or j.get("Type") or j.get("type", ""),
        "state":       (j.get("LastState") or j.get("State") or "").lower(),
        "last_status": (j.get("LastResult") or j.get("Result") or "").lower(),
        "last_run":    j.get("LastRunLocal") or j.get("CreationTime") or j.get("EndTime", ""),
        "server_name": j.get("BackupServerName") or j.get("serverName", ""),
    }

def _norm_session(s: dict) -> dict:
    return {
        "id":         s.get("UID") or s.get("Id") or s.get("ObjectId", ""),
        "job_id":     s.get("JobUid") or s.get("JobId", ""),
        "job_name":   s.get("JobName", ""),
        "status":     (s.get("Result") or s.get("Status") or "").lower(),
        "state":      (s.get("State") or "").lower(),
        "start_time": s.get("CreationTime") or s.get("StartTime", ""),
        "end_time":   s.get("EndTime", ""),
    }

def _norm_repo(r: dict) -> dict:
    cap  = r.get("Capacity") or r.get("CapacityGB") or 0
    free = r.get("FreeSpace") or r.get("FreeSpaceGB") or 0
    # Convert bytes → GB if value looks like bytes (> 1 million)
    if isinstance(cap, (int, float)) and cap > 1_000_000:
        cap  = round(cap  / 1024**3, 1)
        free = round(free / 1024**3, 1)
    return {
        "id":       r.get("UID") or r.get("Id") or r.get("ObjectId", ""),
        "name":     r.get("Name", ""),
        "host":     r.get("Host") or r.get("HostName", ""),
        "type":     r.get("Type") or r.get("Kind", ""),
        "total_gb": float(cap  or 0),
        "free_gb":  float(free or 0),
        "used_gb":  round(float(cap or 0) - float(free or 0), 1),
        "pct":      round((float(cap or 0) - float(free or 0)) / float(cap) * 100, 1) if cap else 0,
    }