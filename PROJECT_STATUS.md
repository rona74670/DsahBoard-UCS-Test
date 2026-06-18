# UCS Dashboard — Project Status
> עדכון אחרון: 2026-06-18

---

## סביבת הרצה

| פריט | ערך |
|---|---|
| Backend | FastAPI + uvicorn, Python 3.14.x (`py.exe`) |
| Port | **9000** |
| DB | SQLite — `backend/dashboard.db` |
| Frontend | Vanilla JS, כל הקבצים ב-`frontend/` |
| הרצה | `Push-Location backend; py -m uvicorn app:app --host 0.0.0.0 --port 9000 --reload` |

---

## ארכיטקטורה כוללת

```
DsahBoard-UCS-Test/
├── backend/
│   ├── app.py                  ← FastAPI main, כל ה-routes
│   ├── database.py             ← SQLite helpers + ibox_capacity_history
│   ├── infinidat_client.py     ← InfinidatClient REST wrapper
│   ├── ucs_client.py           ← UCSMClient (UCS Manager)
│   ├── .env                    ← סודות (לא ב-git)
│   └── dashboard.db            ← SQLite (לא ב-git)
└── frontend/
    ├── index.html              ← TC Farm (UCS)
    ├── pt.html                 ← PT Farm (UCS)
    ├── fattal.html             ← Fattal Farm (UCS)
    ├── compare.html            ← Compare blades
    ├── devices.html            ← Device registry
    ├── infinidat_tc.html       ← TC iBox-03  (v8.1.x)
    ├── infinidat_tc_old.html   ← Old-Infinidat-TC (v7.3.x, 10.10.15.10)
    ├── infinidat_pt.html       ← Infinidat-PT (v7.3.x, 10.10.25.200)
    ├── infinidat.js            ← JS משותף לכל דפי Infinidat
    ├── sidebar.js              ← Sidebar toggle logic
    └── style.css               ← Global dark theme CSS
```

---

## Infinidat iBoxes — פרטי חיבור

| ID | Label | Host | גרסה | user/pass ב-.env |
|---|---|---|---|---|
| `tc03` | TC iBox-03 | `ibox-tc-03.allegronet.co.il` | 8.1.10.250 | `IBOX_TC03_*` |
| `tc-old` | Old-Infinidat-TC | `10.10.15.10` | 7.3.30.60 | `IBOX_TC_OLD_*` |
| `pt` | Infinidat-PT | `10.10.25.200` | 7.3.30.60 | `IBOX_PT_*` |

**API Prefix:** `/api/ibox/{id}/` → endpoints: `ping`, `summary`, `pools`, `volumes`, `snapshots`, `health`, `replicas`, `events`, `top-volumes`, `cgs`, `hosts`, `capacity-trend`

**Frontend routes:** `/infinidat/tc`, `/infinidat/tc-old`, `/infinidat/pt`

---

## הבדלי Firmware

| Feature | v8.x (TC-03) | v7.x (Old-TC, PT) |
|---|---|---|
| `disk_usage` field בסנאפשוטים | ✅ — דלתא ייחודית | ❌ — `None` |
| פתרון | שדה `disk_usage` | flag `disk_usage_avail=False`, מציג "Referenced (TB)" מ-`used` |
| KPI כולל Physical Space | ✅ מוצג | N/A |

---

## Infinidat Client — מתודות (`infinidat_client.py`)

| מתודה | תיאור |
|---|---|
| `get_system()` | גרסה, host, health_state |
| `get_summary()` | capacity, counts, pools, health — נקרא על `/summary` |
| `get_pools()` | רשימת pools עם קיבולת |
| `get_volumes()` | MASTER volumes |
| `get_snapshots()` | כל הסנאפשוטים — by_pool, old_candidates, all_snapshots, disk_usage_avail |
| `get_health()` | drives, nodes, BBU |
| `get_replicas()` | replicas עם job history (state, role, entity_type, last_sync_ago_min, job_duration_s) |
| `get_events()` | 50 events אחרונים עם description מ-rendered |
| `get_top_volumes()` | top 10 largest + כל unprotected (ללא snapshot_policy_id) |
| `get_cgs()` | Consistency Groups (parent_id=None בלבד) |
| `get_hosts()` | total, mapped, unmapped, by_type |

---

## Database — טבלאות חדשות (`database.py`)

```sql
CREATE TABLE ibox_capacity_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ibox_id TEXT NOT NULL,
  recorded_at INTEGER NOT NULL,   -- ms since epoch
  phys_free_tb REAL,
  phys_total_tb REAL,
  phys_pct REAL
);
```

**פונקציות:**
- `record_ibox_capacity(ibox_id, phys_free_tb, phys_total_tb, phys_pct)` — נקרא בכל `/summary`
- `get_ibox_capacity_history(ibox_id, days=30)` → list of dicts
- `compute_days_until_full(history)` → int|None — linear regression

---

## Frontend — infinidat.js

### State variables
```js
_snapCandidates    // deletion candidates list
_allSnaps          // כל הסנאפשוטים
_allSnapsSortField // 'date' | 'size'
_allSnapsSortAsc   // bool
_diskUsageAvail    // true=v8.x, false=v7.x
```

### Render functions
| פונקציה | מה היא עושה |
|---|---|
| `renderPoolBars()` | progress bars לכל pool |
| `renderPoolsTable()` | טבלת pools |
| `renderVolumesTable()` | טבלת volumes |
| `renderSnapshots()` | KPIs + by-pool table + candidates + all-snaps |
| `renderAllSnaps()` | טבלה כווצת עם sort לפי size/date, מציג referenced TB ב-v7.x |
| `filterCandidates()` | client-side filter לפי min-age + pool |
| `renderHealth()` | nodes table + BBU summary |
| `renderReplicas()` | 7 עמודות: ID, State, Role, Entity Type, Last Sync, Duration, Job State |
| `renderEvents()` | events table |
| `renderTopVolumes()` | top10 + unprotected table עם badge |
| `renderCGs()` | Consistency Groups |
| `renderHosts()` | KPI pills + type breakdown |
| `renderCapacityTrend()` | days-until-full + canvas sparkline |

### loadAll() — סדר קריאות
1. `await /summary` → renders KPIs, pools, health
2. `Promise.all`: volumes, replicas, events, top-volumes, cgs, hosts, capacity-trend
3. `apiFetch('/snapshots')` — בנפרד (איטי — paginate 2500+)

---

## Sidebar

כל 8 דפי HTML מכילים sidebar אחיד עם קבוצת Infinidat עם 3 לינקים:
- TC iBox-03 → `/infinidat/tc`
- Old-Infinidat-TC → `/infinidat/tc-old`
- Infinidat-PT → `/infinidat/pt`

`sbGroup(id)` פותח/סוגר קבוצה. הדף הפעיל מסומן `class="sb-item active"`.

---

## מה עוד לעשות (Next Steps)

### גבוהה עדיפות
- [ ] **Capacity Trend chart** — יש HTML + JS אבל צריך מספר ימים של נתונים (`ibox_capacity_history`) — לבדוק אחרי כמה ימים
- [ ] **infinidat_tc_old.html** — חסרים בה כרגע הסקשנים: Top Volumes, CGs, Hosts — צריך להוסיף כמו ב-tc.html
- [ ] **Auto-refresh** — להוסיף timer (כל 5/15 דק') עם countdown

### בינוני
- [ ] **Search/filter** על טבלת All Snapshots (חיפוש לפי שם)
- [ ] **Pool filter** גם על All Snapshots (כמו שיש ב-Candidates)
- [ ] **Compare Infinidat** — דף השוואה בין שלושת ה-iBoxes
- [ ] **Alerts badge** בסייד-בר — אם יש events ברמת ERROR

### נמוך
- [ ] **QoS** — API 404 ב-v7.x ו-v8.x — לא זמין
- [ ] **Performance stats** — API 404 — לא זמין
- [ ] **Drive detail table** — כרגע רק aggregate counts

---

## `.env` structure (לא ב-git)

```env
# UCS Farms
TC_HOST=...
TC_USER=...
TC_PASS=...
PT_HOST=...
PT_USER=...
PT_PASS=...
FATTAL_HOST=...
FATTAL_USER=...
FATTAL_PASS=...

# Infinidat iBox
IBOX_TC03_HOST=ibox-tc-03.allegronet.co.il
IBOX_TC03_USER=CockpitDash
IBOX_TC03_PASS=...
IBOX_TC_OLD_HOST=10.10.15.10
IBOX_TC_OLD_USER=CockpitDash
IBOX_TC_OLD_PASS=...
IBOX_PT_HOST=10.10.25.200
IBOX_PT_USER=CockpitDash
IBOX_PT_PASS=...
```

---

## Known Issues / הערות

1. **`disk_usage` ב-v7.x** — `None` — תוקן: `_diskUsageAvail=False` → מציג `used_tb` עם תווית "Referenced"
2. **Snapshot sort API** — רק `-created_at` עובד. `-disk_usage`, `-size`, `-used` → 400. לכן הסורטינג נעשה בצד שרת בפייתון.
3. **`has_snapshot_policy=false` filter** — API מחזיר 400. נפתר: fetch כולם, filter בפייתון.
4. **Replicas** — `role` ו-`job_state` עלולים להיות ריקים — JS מציג `–`.
5. **Capacity Trend** — ה-sparkline עובד רק עם 2+ readings. כרגע `readings=0/1` עד שיצטברו נתונים.
