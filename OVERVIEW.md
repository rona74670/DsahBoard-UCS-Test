# UCS Dashboard – Project Overview

## תיאור הפרויקט

דשבורד ניטור רב-סביבתי המכסה ארבעה תחומים:
1. **Cisco UCS** — ניטור חומרה (Blades, FI, PSU, Firmware) בשלוש חוות שרתים
2. **Infinidat** — ניטור אחסון (קיבולת, Snapshots, Replicas, ביצועים) בשלושה iBoxes
3. **VMware vCenter** — ניטור מכונות וירטואליות (VMs, Hosts, Clusters) בארבעה vCenters
4. **Veeam Backup** — ניטור גיבויים (Jobs, Repositories, Sessions) מחמישה שרתי Veeam (EM, PT, Fattal, TC, Lifesaver)

כולל **ניהול לקוחות** (Priority/SAP → שם לקוח) המשויך לכל VM,
**מעקב שינויים והיסטוריה** של מלאי ה-VMs (כולל צילומי מצב, השוואת גרסאות, גיבוי יומי אוטומטי
מלא — VMs+Hosts+Clusters+Datastores — וגיבוי חודשי אוטומטי מוגן במחיקה), דוח **תאריכי יצירת
VMs**, **DR Dashboard** לפי לקוח, **חיוב לפי גדילת משאבים** מעל % פטור שמוגדר לכל לקוח,
ו**עוזר AI** מבוסס שרת Ollama פנימי. הגיבוי היומי משמש גם לגישת **קריאה-בלבד לדשבורד חיצוני**
(ראו [`EXTERNAL_DASHBOARD_ACCESS.md`](EXTERNAL_DASHBOARD_ACCESS.md)).

כל הדשבורד נמצא **מאחורי אימות מלא** — Microsoft Entra ID SSO (עם allow-list הרשאות) או
כניסה עם שם משתמש/סיסמה (AD דרך LDAP, מוגבלת ל-IPs מקומיים בלבד).

> לפירוט מלא ועדכני של כל מודול, endpoint, טבלת DB ומשתני סביבה — ראו [`PROJECT_STATUS.md`](PROJECT_STATUS.md),
> שהוא המסמך החי המתעדכן בכל שינוי. מסמך זה הוא סקירה ארכיטקטונית כללית.

---

## ארכיטקטורה

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Browser (HTML/JS)                                    │
│  UCS │ Compare │ Infinidat │ vCenter │ History │ VM-Create │ Backup │ DR      │
│  Login │ Permissions │ Admin Overview                                        │
│  auth.js (session sync + CSRF) │ sidebar.js (ניווט + theme + AI widget)      │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │ HTTPS (port 9000) + עוגיית auth_token + csrf_token
┌──────────────────────────────▼───────────────────────────────────────────────┐
│  _AuthMiddleware → _CSRFMiddleware → _SecurityHeaders → CORS                 │
│  /api/* ללא JWT ⇒ 401   │   דף ללא JWT ⇒ 302 /login                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                      FastAPI Backend (Python 3.14)                            │
│  /api/auth/*  /api/authz/*          (Entra SSO + AD/local + allow-list)      │
│  /api/tc /api/pt /api/fattal        (UCS)                                    │
│  /api/ibox/{id}                     (Infinidat)                              │
│  /api/vcenter/{env}                 (vCenter)                                │
│  /api/vcenter/events  /history      (Change Tracking + Snapshots + VM-Create)│
│  /api/backup/em                     (Veeam EM — session auth, port 9398)     │
│  /api/backup/{pt|fattal|tc|lifesaver} (Veeam B&R — OAuth2, port 9419)        │
│  /api/customers /api/devices /api/dr /api/ai/chat                            │
│  ⟳ thread רקע: vc-events-poll (30 יום ראשוני, ואז כל שעתיים)                 │
└──┬─────────┬─────────┬──────────┬──────────────┬────────────────────────────┘
   │         │         │          │              │
┌──▼─────┐ ┌─▼───────┐ ┌▼────────────┐ ┌────────▼──────────┐ ┌──────────────┐
│Cisco   │ │Infinidat│ │VMware vCenter│ │      Veeam         │ │Entra ID /    │
│UCS XML │ │REST API │ │pyVmomi/SOAP  │ │ EM: session auth   │ │AD (LDAP) /   │
└────────┘ └─────────┘ └─────────────┘ │ B&R: OAuth2 Bearer │ │Ollama (AI)   │
   │                                    └────────────────────┘ └──────────────┘
┌──▼─────────────────────────────────────────────────────────────────────────┐
│                       SQLite — dashboard.db                                 │
│  manual_data │ devices │ customers │ vm_notes │ vm_sap_cache               │
│  ibox_capacity_history │ vcenter_events                                    │
│  auth_settings │ authz_users │ vm_snapshots │ vm_snapshot_items            │
│  customer_billing_config │ vm_snapshot_env_data                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## סביבות מוניטור

### UCS Farms

| Farm | Host | API Prefix | URL |
|------|------|------------|-----|
| TC-FARM | 10.10.140.100 | `/api/tc` | `/` |
| PT-FARM | 10.20.140.100 | `/api/pt` | `/pt` |
| FATTAL  | 10.8.0.160    | `/api/fattal` | `/fattal` |

### Infinidat iBoxes

| Label | Host | גרסה | API Prefix | URL |
|-------|------|------|------------|-----|
| TC iBox-03 | `ibox-tc-03.allegronet.co.il` | 8.1.x | `/api/ibox/tc03` | `/infinidat/tc` |
| Old-Infinidat-TC | `10.10.15.10` | 7.3.x | `/api/ibox/tc-old` | `/infinidat/tc-old` |
| Infinidat-PT | `10.10.25.200` | 7.3.x | `/api/ibox/pt` | `/infinidat/pt` |

### VMware vCenters

| Label | Host | URL |
|-------|------|-----|
| TC-vCenter | `al-vcenter6.allegronet.co.il` | `/vcenter/tc` |
| TC-vCenter8 | `vcenter-tc.allegronet.co.il` (10.10.15.70) | `/vcenter/tc8` |
| PT-vCenter | `vc-pt.allegronet.co.il` | `/vcenter/pt` |
| Fattal-vCenter | `vcenter6.fattal.co.il` | `/vcenter/fattal` |
| Overview | כל הסביבות | `/vcenter/overview` |
| Change Tracking | אירועי שינוי VMs | `/vcenter/changes` |
| History | צילומי מצב + השוואת גרסאות | `/vcenter/history` |
| VM Create | דוח תאריכי יצירת VMs | `/vcenter/vm-create` |

### Veeam Backup Servers

| Label | Host | פורט | Auth | URL |
|-------|------|------|------|-----|
| Backup EM | `al-veeambem.allegronet.co.il` | 9398 | Session (`X-RestSvcSessionId`) | `/backup` |
| PT Backup | `al-veeampt.allegronet.co.il` | 9419 | OAuth2 Bearer | `/backup/pt` |
| Fattal Backup | `ft-vbck.fattal.co.il` | 9419 | OAuth2 Bearer | `/backup/fattal` |
| TC Backup | `al-veeamcc.allegronet.co.il` | 9419 | OAuth2 Bearer | `/backup/tc` |
| Lifesaver Backup | `al-lifesaver.allegronet.co.il` | 9419 | OAuth2 Bearer | `/backup/lifesaver` |

> **משתמש:** `al-lifesaver\VeeamRO`
> **סיסמאות:** שמורות ב-`backend/.env` (נעול: BUILTIN\Administrators בלבד)

---

## מבנה הפרויקט

```
DsahBoard-UCS-Test/
├── backend/
│   ├── app.py                  # FastAPI – כל ה-routes + routers
│   ├── database.py             # SQLite helpers
│   ├── ucs_client.py           # Cisco UCS XML API client
│   ├── infinidat_client.py     # Infinidat REST API client
│   ├── vcenter_client.py       # VMware vCenter client (pyVmomi)
│   ├── perf_collector.py       # דגימת CPU/RAM/CPU-Ready לכל VM כל דקה (thread רקע)
│   ├── perf_store.py           # roll-up שעתי/יומי ב-SQLite + שאילתות סיכום
│   ├── perf_rightsizing.py     # המלצות right-sizing מנתוני הביצועים
│   ├── veeam_client.py         # Veeam EM client (session auth, port 9398)
│   ├── veeam_br_client.py      # Veeam B&R client (OAuth2, port 9419)
│   ├── auth.py                 # JWT (HS256) + bcrypt + אימות AD דרך LDAP
│   ├── ollama_client.py        # לקוח שרת Ollama הפנימי (עוזר AI)
│   ├── .env                    # Credentials — נעול ל-Administrators בלבד
│   └── dashboard.db            # SQLite (לא ב-git)
├── frontend/
│   ├── index.html / pt.html / fattal.html   # UCS farms
│   ├── compare.html            # השוואת Farms
│   ├── devices.html            # Device Registry
│   ├── customers.html          # ניהול לקוחות
│   ├── dr.html                 # DR Dashboard
│   ├── backup*.html            # Veeam: EM, PT, Fattal, TC, Lifesaver
│   ├── infinidat_*.html        # Infinidat: TC, TC-old, PT
│   ├── vcenter_*.html          # vCenter: TC, TC8, PT, Fattal, Overview,
│   │                           #   Cluster-Detail, Changes, History, VM-Create,
│   │                           #   Perf (CPU/RAM/CPU Ready), Rightsizing
│   ├── login.html              # דף התחברות (סיסמה מקומית / Entra SSO)
│   ├── permissions.html        # ניהול allow-list הרשאות
│   ├── billing_config.html     # הגדרות חיוב לקוחות (% פטור + מחירי משאבים, חדש 4.9)
│   ├── admin_overview.html     # Executive Summary + פאנל SSO/SSL (#sso)
│   ├── sidebar.js              # Sidebar דינמי + Light/Dark toggle + AI widget
│   ├── auth.js                 # סנכרון session, CSRF helper, logout
│   ├── infinidat.js / app.js / lang.js
│   ├── xlsx.full.min.js        # SheetJS, vendored locally — קריאה בלבד, לא כותב עיצוב
│   ├── exceljs.min.js          # ExcelJS, vendored locally — ליצוא Excel מעוצב (חדש 4.8)
│   └── style.css               # Global theme (dark + light mode)
├── scripts/                    # סקריפטי הפעלה/תיקון/אבחון (write_sidebar.py,
│                                #   setup_*_pass.ps1, patch_*.py, diag_*.py, test_veeam*.py וכו')
├── Customers/                  # קובצי מקור ליבוא לקוחות (Excel)
├── logos/, logs/, Cert/, tools/, Danny/
├── install_service.ps1         # התקנת שירות NSSM
├── stop_server.ps1 / start_server.vbs
├── OVERVIEW.md
└── PROJECT_STATUS.md
```

> **הערה:** תיקיית השורש מכילה גם עשרות סקריפטי `deploy_*`/`fix_*`/קבצי `*_done.txt`/`*.log`
> שהצטברו מסבבי פיתוח איטרטיביים (patches חד-פעמיים שהוחלו על production ולא נוקו).
> הלוגיקה החיה היא אך ורק ב-`backend/` וב-`frontend/`.

---

## API Endpoints — עיקריים

| קבוצה | Prefix | תיאור |
|--------|--------|--------|
| UCS | `/api/{tc\|pt\|fattal}` | `ping`, `summary`, `blades/enriched`, `hardware-summary`, `firmware`, `power-stats`, `network-adapters` |
| Infinidat | `/api/ibox/{id}` | `ping`, `summary`, `volumes`, `snapshots`, `replicas`, `replicas/detailed`, `top-volumes`, `performance`, `hardware` |
| vCenter | `/api/vcenter/{env}` | `ping`, `summary` (cache 180s) |
| vCenter Events | `/api/vcenter/events` | `poll` (admin), `export` |
| vCenter Performance | `/api/vcenter/perf` | `?range=24h\|7d\|30d\|90d\|180d&env=` (סיכום לכל VM כולל CPU Ready), `perf/vm` (סדרה לגרף), `perf/backups` (זמני גיבוי של VM מ-Veeam B&R לסימון בגרף), `perf/hosts` (ESXi של כל VM + עומס רגעי, חי), `perf/disks` (לייטנסי/IOPS לכל דיסק של VM, חי מ-vCenter), `perf/rightsizing`, `perf/status` |
| vCenter History | `/api/vcenter/history` | `snapshot` (POST, admin), `snapshots`, `snapshot/{id}`, DELETE `snapshot/{id}` |
| Veeam EM | `/api/backup/em` | `ping`, `summary` (session auth, cache 5min) |
| Veeam B&R | `/api/backup/{pt\|fattal\|tc\|lifesaver}` | `ping`, `summary` (OAuth2, cache 5min) |
| Customers | `/api/customers` | GET/POST/PUT/DELETE, `map`, `import` (Excel) |
| Devices | `/api/devices` | GET/POST/PUT/DELETE |
| Auth | `/api/auth/*` | `login`, `logout`, `session`, `login-options`, `microsoft/start`, `microsoft/callback`, `microsoft/config` |
| Authorization | `/api/authz/users` | GET/PUT allow-list, DELETE identity |
| AI | `/api/ai/chat` | צ'אט מול Ollama עם קונטקסט עמוד + היסטוריה |
| Health | `/health` | בדיקת חיות |

> פירוט מלא של כל route, method, auth requirement וטבלת DB — ב-`PROJECT_STATUS.md`.

---

## מסד הנתונים — טבלאות עיקריות

| טבלה | תיאור |
|-------|--------|
| `customers` | ~548 לקוחות, `sap_number` → `customer_name` |
| `devices` | Device Registry (UCS/other infra) |
| `manual_data` | metadata ידני ל-UCS (cabinet, assignment, vcenter, notes) |
| `ibox_capacity_history` | טרנד קיבולת Infinidat לאורך זמן |
| `vm_notes` | תפקיד שרת + איפיון (classification) per VM |
| `vcenter_events` | Change Tracking — לוג אירועי VM (append-only) |
| `vm_sap_cache` | VM → מס' פריוריטי (cache, מתמלא מ-summary) |
| `auth_settings` | קונפיג Entra SSO (key/value, לא ב-.env) |
| `authz_users` | allow-list הרשאות SSO (`admin`/`readonly`) |
| `vm_perf_hourly` / `vm_perf_daily` | roll-up ביצועים לכל VM: פיק/ממוצע CPU ו-RAM, ספירת דקות בעומס, ו-CPU Ready (פיק, ממוצע, דקות ≥5%/≥10%); שעתי נשמר 30 יום, יומי ~6 חודשים |
| `vm_snapshots` / `vm_snapshot_items` | צילומי מצב מלאי VMs (feature History); `taken_by='system-daily'` = גיבוי יומי אוטומטי (01:15), `protected=1` = גיבוי חודשי אוטומטי, לא נמחק אוטומטית |
| `vm_snapshot_env_data` | `summary_json` מלא (VMs+Hosts+Clusters+Datastores) לכל environment בכל snapshot — חדש 4.9.1, לצורך גישת דשבורד חיצוני |
| `customer_billing_config` | % גדילה פטורה + מחיר ליחידת משאב, לפי לקוח (feature חיוב, חדש 4.9) |

כל הטבלאות נוצרות/עוברות מיגרציה אוטומטית ב-`init_db()` בעליית השירות.
סכימת ה-SQL המלאה ב-`PROJECT_STATUS.md`.

---

## אימות והרשאות

- **שתי דרכי כניסה:** Microsoft Entra ID SSO (OAuth2 Authorization Code) לכל משתמש, או
  שם משתמש/סיסמה (AD דרך LDAP + fallback local) — מוגבל ל-IPs מקומיים בלבד (`LOCAL_LOGIN_SOURCE_IPS`).
- **Allow-list** (`authz_users`) — משתמש Entra שאינו ברשימה נחסם.
- **JWT** (HS256) ב-cookie HttpOnly `auth_token`; CSRF דרך cookie `csrf_token` + header `X-CSRF-Token`.
- ניהול דרך `/admin/permissions` (allow-list) ו-`/admin/overview#sso` (קונפיג SSO).

פירוט זרימת האימות המלאה, משתני env, וטבלת מודל ההרשאות — ב-`PROJECT_STATUS.md`.

---

## טכנולוגיות

| רכיב | טכנולוגיה |
|------|-----------|
| Backend | Python 3.14, FastAPI, uvicorn |
| UCS API | Cisco UCSM XML API (HTTPS POST /nuova) |
| Infinidat API | REST JSON over HTTPS |
| vCenter API | pyVmomi (PropertyCollector bulk fetch) |
| Veeam EM | REST API v1.6 (session-based) |
| Veeam B&R | REST API v1 (OAuth2 Bearer) |
| DB | SQLite 3 (WAL mode) |
| AI | Ollama (שרת LLM פנימי, streaming) |
| Excel | openpyxl (import) + SheetJS (ייצוא רגיל, vendored) + ExcelJS (ייצוא מעוצב — צבעים/גבולות, vendored, חדש 4.8) |
| Frontend | Vanilla HTML/CSS/JavaScript |
| Service | NSSM (Non-Sucking Service Manager) |
| Auth | JWT HS256 (HttpOnly cookie) + CSRF double-submit + Entra ID SSO |

---

## אבטחה

שלושה סבבי סקירת אבטחה בוצעו: Round 1 + Round 2 (יולי 2026) ו-Round 3 (ספטמבר 2026).
ב-Round 3 התגלה ותוקן ש-`_CSRFMiddleware` היה בפועל **pass-through ריק** מאז שנוצר —
לא בדק שום דבר — וכן open redirect אחרי SSO login (`next.startswith("/")` קיבל גם `//evil.com`)
וכמה ממצאי XSS ברגרסיות בדפים חדשים יותר. כל אלה תוקנו ומתועדים ב-`PROJECT_STATUS.md`.
פריט אחד עדיין ממתין: CSP `unsafe-inline` (דורש refactor מלא של inline scripts ב-frontend).

> `SECURITY_REVIEW.md` ו-`SECURITY_REVIEW_ROUND2.md` הם תיעוד נקודתי (snapshot) של הסבבים
> הללו נכון ליולי 2026 — הם **אינם** מכסים תכונות שנוספו מאז (עוזר AI, Entra SSO, allow-list)
> ואינם כוללים את ממצאי/תיקוני Round 3. ממצאי סקירת קוד עדכניים יותר (ספטמבר 2026) מתועדים
> ב-`PROJECT_STATUS.md`.

---

## הרחבות עתידיות

- [ ] CSP `unsafe-inline` refactor — הוצאת inline scripts לקבצי JS חיצוניים
- [ ] **Alerts badge** בסיידבר — events ברמת ERROR/WARNING
- [ ] **SRM REST API** — שדרוג SRM לגרסה 8.3+ לנתוני protection groups
- [ ] **DR Drill-down לקוח** — פירוט VM-רמה עם RPO היסטורי

---

*עדכון אחרון: ספטמבר 2026 (22/09/2026) | גרסה: 4.9.1 — תואם ל-`PROJECT_STATUS.md`*
