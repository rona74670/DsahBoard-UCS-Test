# UCS Dashboard – Project Overview

## תיאור הפרויקט

דשבורד ניטור רב-סביבתי לצי שרתי Cisco UCS Manager. מספק תמונת מצב חומרה מלאה בזמן אמת על פני מספר חוות שרתים, עם יכולות ייצוא, ניהול ידני והשוואה בין סביבות.

---

## ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (HTML/JS)                        │
│   TC-FARM │ PT-FARM │ FATTAL │ Compare │ Devices                │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP (port 9000)
┌──────────────────────▼──────────────────────────────────────────┐
│                   FastAPI Backend (Python)                        │
│   /api/tc/...  │  /api/pt/...  │  /api/fattal/...               │
│   /api/devices  (global device registry)                         │
└────────────────┬────────────────────────┬───────────────────────┘
                 │                        │
    ┌────────────▼───────────┐   ┌────────▼───────────┐
    │  Cisco UCS Manager     │   │  SQLite DB          │
    │  XML API (/nuova)      │   │  dashboard.db       │
    │  SSL / self-signed OK  │   │  manual_data table  │
    └────────────────────────┘   │  devices table      │
                                 └────────────────────┘
```

---

## סביבות מוניטור (Farms)

| Farm | Host | API Prefix | URL |
|------|------|-----------|-----|
| TC-FARM | 10.10.140.100 | `/api/tc` | `http://server:9000/` |
| PT-FARM | 10.20.140.100 | `/api/pt` | `http://server:9000/pt` |
| FATTAL  | 10.8.0.160    | `/api/fattal` | `http://server:9000/fattal` |

---

## מבנה הפרויקט

```
DsahBoard-UCS-Test/
├── backend/
│   ├── app.py              # FastAPI – router factory + endpoints
│   ├── ucs_client.py       # Cisco UCS XML API client
│   ├── database.py         # SQLite layer (manual_data + devices)
│   ├── dashboard.db        # SQLite database (נוצר אוטומטית)
│   └── .env                # Credentials (לא ב-git)
├── frontend/
│   ├── index.html          # TC-FARM dashboard
│   ├── pt.html             # PT-FARM dashboard
│   ├── fattal.html         # FATTAL dashboard
│   ├── compare.html        # השוואה בין Farms
│   ├── devices.html        # ניהול התקנים (Device Registry)
│   ├── app.js              # כל לוגיקת ה-JavaScript
│   └── style.css           # עיצוב (dark theme)
├── logs/                   # לוגים של השרת (נוצר ע"י Service)
├── tools/nssm/             # NSSM binary (נוצר ע"י install_service.ps1)
├── start_server.vbs        # הפעלה ידנית בלי חלון שחור
├── stop_server.ps1         # עצירת השרת
├── install_service.ps1     # התקנת Windows Service (24/7)
└── OVERVIEW.md             # מסמך זה
```

---

## API Endpoints

### Per-Farm (דוגמה עם `/api/tc`)

| Method | Path | תיאור |
|--------|------|--------|
| GET | `/api/tc/ping` | בדיקת חיבור |
| GET | `/api/tc/summary` | סיכום כולל (KPI, FI, Blades, Faults) |
| GET | `/api/tc/blades/enriched` | Blades עם CPU/Memory/Storage/RAID |
| GET | `/api/tc/hardware-summary` | CPU/Memory/PSU/Fan/IPs tables |
| GET | `/api/tc/firmware` | גרסאות BIOS + CIMC + Adapter |
| GET | `/api/tc/power-stats` | צריכת חשמל per chassis |
| GET | `/api/tc/network-adapters` | VIC adapters + vNIC MAC + vHBA WWPN |
| GET | `/api/tc/pools` | UUID/IP/MAC/WWPN pool availability |
| GET | `/api/tc/faults` | Active faults |
| GET | `/api/tc/manual-data` | נתוני שיוך/ארון/vCenter מה-DB |
| PUT | `/api/tc/manual-data` | שמירת נתונים ידניים |

### Global

| Method | Path | תיאור |
|--------|------|--------|
| GET | `/api/devices` | רשימת כל ההתקנים |
| POST | `/api/devices` | הוספת התקן |
| PUT | `/api/devices/{id}` | עדכון התקן |
| DELETE | `/api/devices/{id}` | מחיקת התקן |

---

## מסד הנתונים (SQLite)

### manual_data
| עמודה | סוג | תיאור |
|-------|-----|--------|
| farm | TEXT | מזהה הסביבה: tc / pt / fattal |
| server_key | TEXT | מזהה השרת (serverId: chassis/blade) |
| assignment | TEXT | שיוך (VM, שירות, צוות) |
| cabinet | TEXT | ארון / מיקום פיזי |
| vcenter | TEXT | שם vCenter |
| notes | TEXT | הערות חופשיות |
| updated_at | TEXT | תאריך עדכון אחרון |

### devices
| עמודה | סוג | תיאור |
|-------|-----|--------|
| id | INTEGER | מזהה אוטומטי |
| farm | TEXT | הסביבה שאליה שייך (TC-FARM / ALL / ...) |
| name | TEXT | שם ידידותי |
| type | TEXT | UCS / InfiniBand / Host / Storage / Switch / Generic |
| host | TEXT | כתובת IP / hostname |
| username | TEXT | משתמש לגישה |
| password | TEXT | סיסמה |
| port | INTEGER | פורט (ברירת מחדל: 443) |
| protocol | TEXT | https / http / ssh / snmp / other |
| notes | TEXT | הערות |
| enabled | INTEGER | 1=פעיל, 0=כבוי |
| created_at | TEXT | תאריך יצירה |
| updated_at | TEXT | תאריך עדכון |

---

## הפעלה ועצירה

### הפעלה ידנית (ללא חלון)
```
פתח את start_server.vbs בלחיצה כפולה
```

### עצירה ידנית
```powershell
.\stop_server.ps1
```

### התקנת Windows Service (24/7)
```powershell
# הרץ כ-Administrator
powershell -ExecutionPolicy Bypass -File install_service.ps1
```
- השרת יעלה אוטומטית עם Windows
- אם קורס, NSSM מפעיל מחדש תוך 5 שניות
- לוגים ב-`logs\dashboard_stdout.log`

### הסרת ה-Service
```powershell
Stop-Service UcsDashboard
.\tools\nssm\nssm.exe remove UcsDashboard confirm
```

---

## סקציות בדשבורד

| סקציה | תוכן |
|--------|-------|
| KPI Cards | FI / Chassis / Blades / Racks / SP / Faults |
| System Info | Domain, IP, Uptime, Mode |
| Fabric Interconnects | מודל, Serial, IP, State |
| Blade Servers | CPU, Memory, Storage, RAID, Service Profile, vCenter, שיוך, ארון |
| Rack Servers | מידע בסיסי |
| CPU Summary | מודל CPU, Cores, GHz, Status – ניתן לסינון |
| Memory | כל DIMM, GB, Type, MHz – ניתן לסינון |
| PSU | לכל chassis, צריכה, Serial |
| Fan Modules | לכל chassis |
| Blade IPs | Management IP per blade |
| Firmware | BIOS + CIMC + Adapter גרסה לכל blade |
| Power & Temp | Input/Output Watt per chassis |
| Physical Adapters | VIC model, serial per blade |
| vNIC Ethernet | MAC addresses per interface |
| vHBA FC | WWPN / Node WWN per HBA |
| Pool Availability | UUID/IP/MAC/WWPN: Size, Assigned, Free |
| Active Faults | כל השגיאות עם severity |

---

## טכנולוגיות

| רכיב | טכנולוגיה |
|------|-----------|
| Backend | Python 3.14, FastAPI 0.111, uvicorn |
| UCS API | Cisco UCSM XML API (HTTPS POST /nuova) |
| Database | SQLite 3 (built-in Python) |
| Frontend | Vanilla HTML/CSS/JavaScript (ללא framework) |
| Excel Export | SheetJS (xlsx) CDN |
| 24/7 Service | NSSM (Non-Sucking Service Manager) |

---

## הרחבות עתידיות

- [ ] **InfiniBand** – ניטור Mellanox/NVIDIA UFM דרך REST API
- [ ] **VMware vCenter** – חיבור לרשימת VMs per blade
- [ ] **Storage** – NetApp / Pure Storage API integration  
- [ ] **Alerts** – email/Teams notification על Critical faults
- [ ] **History** – שמירת snapshots תקופתיים ב-DB לגרפים
- [ ] **Authentication** – login page עם LDAP/AD
- [ ] **Dark/Light mode toggle**
- [ ] **Scheduled auto-refresh** – רענון אוטומטי כל X דקות

---

*נוצר: יוני 2026 | גרסה: 3.0.0*
