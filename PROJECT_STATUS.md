# UCS Dashboard — Project Status

**עדכון אחרון:** אוקטובר 2026 (08/10/2026)  
**גרסה:** 4.11.0  
**מצב:** Production — פעיל 24/7 כ-Windows Service, **מאחורי אימות מלא** (Entra ID SSO + allow-list)

> ⚠️ **שינוי מהותי מגרסה 4.4.3:** הגישה הפתוחה ללא אימות **בוטלה**. כל דף וכל endpoint
> (חוץ מ-`/login` ו-`/api/auth/*`) דורשים JWT תקין בעוגיית `auth_token`.

---

## מצב נוכחי לפי מודולים

### ✅ UCS (Cisco)
- שלושה farms: TC / PT / Fattal
- Blades, FI, PSU, Fans, Firmware
- השוואת Blades בין farms
- Device Registry (CRUD + Excel export)
- Manual metadata (cabinet, assignment, vCenter, notes)

### ✅ Infinidat
- שלושה iBoxes: TC-03 (v8.1.x), Old-TC (v7.3.x), PT (v7.3.x)
- קיבולת, Pools, Volumes (MASTER בלבד), Snapshots, Replicas
- Top-10 Volumes + unprotected, CG list, Hosts list
- Trend קיבולת (תרשים, נשמר ב-DB)
- Hardware (Drives, FC Ports)
- **באדג' דגם (Model)** בכותרת כל דף — חדש 4.8; נשלף מ-`components/nodes` (אותו endpoint שכבר שימש את טאב ה-Health), מוצג ליד גרסת התוכנה

### ✅ vCenter
- ארבעה vCenters: TC / TC8 (`vcenter-tc.allegronet.co.il`) / PT / Fattal
- KPI bar: VMs, Hosts, vCPU, RAM, Storage
- טבלת Hosts עם usage bars
- **מס. פריוריטי + שם לקוח** לכל VM
- **↔ DR badge** לשכפולי SRM
- **מיון לפי כל עמודה** (↕/↑/↓)
- **פאנל סיכום משאבים** — סה"כ | פועלות | כבויות, דינמי לפי סינון
- **יצוא Excel מסונן** — כולל חיפוש לפי שם לקוח
- In-memory cache TTL=180s
- **דף Overview** — מאחד כל vCenters
- **דף פירוט קלסטר** (`vcenter_cluster_detail.html`) — גאג'ים, ממצאים, מארחים
- **יתירות N+X** אחידה בכל 4 דפי vCenter (נוסחת ratio)
- **מעקב שינויים** (`vcenter_changes.html`) — אירועי VM לפי סביבה ולקוח, מיון עמודות, פילטרי חברה/משתמש/אירוע, TC + TC8 + PT + Fattal
- **עמודות אופציונליות** — כפתור `📋 עמודות` בכל 4 דפי vCenter (DNS Name, VMtools סטטוס, HW Version, Thin/Thick, שעון מהמארח, מצב רשת, כרטיסי רשת, Port Group, VLAN, סוג רשת)
- **מצב רשת + כרטיסי רשת** — `nic_connected/nic_total` מ-pyVmomi; עמודת "מצב רשת" (מחובר/לא מחובר, ברירת מחדל גלויה) + "כרטיסי רשת" (X/Y, ספירת מחוברים); ניתן למיין
- **Port Group + VLAN** — חילוץ מ-pyVmomi: שם portgroup לפי NIC (standard vSwitch + DVS), VLAN ID מ-DVPortgroup config
- **סוג רשת** — מיפוי VLAN→תיאור: VLAN 3=DMZ Bezeqint, 9=לקוחות, 11=פנימית אלגרונט, 13=DMZ אלגרונט, 15=ניהול, 34=גיבוי
- **דומיין** — חתיכת הדומיין מה-DNS Name (אחרי נקודה ראשונה); שרתים ללא DNS מציגים "WorkGroup"; ניתן למיין ולסנן לפיו (dropdown ב-toolbar)
- **איפיון** — רשימת בחירה עם 12 ערכים (כולל מרכזיה, שרת לניהול סטוראג, שרת VMware אלגרונט, **אלגרונט החדשה** — חדש 4.8) + אופציית **"✏️ אחר (הקלדה חופשית)"** שהופכת את התא לשדה טקסט חופשי — חדש 4.8; נשמר ב-`vm_notes.classification` ב-SQLite
- **תפקיד שרת** — הפך מתא טקסט חופשי בלבד לרשימת בחירה (DC, SQL, פריוריטי, סאפ, טרמינל, קבצים, מדפסות, ברוקר, ווב, רישיונות, קוקפיט, ניהול קוקפיט, סייבס, G4, GOC, FTP, FSlogix, דואר, Entra connect, DB Cache, ממשקים, TSG, אפליקציות) + אותה אופציית **"✏️ אחר (הקלדה חופשית)"** — חדש 4.8; שרתים עם ערך קיים שלא ברשימה ממשיכים להיות מוצגים כטקסט חופשי אוטומטית; נשמר ב-`vm_notes.note`
- **דף Overview** — עמודות `תפקיד השרת` + `איפיון` בטאב "כל המכונות" ובטאב "לפי לקוח"
- **דף ביצועים** (`vcenter_perf.html`, `/vcenter/perf`) — פיקים/ממוצעים של CPU ו-RAM לכל VM (דגימה כל דקה, roll-up שעתי/יומי), מד עומס, גרף לכל VM, יצוא Excel. **חדש 4.10: צ'קבוקס `⏱ הצג CPU Ready`** — ראו "שינויים מרכזיים — גרסה 4.10.0". **חדש 4.11: סימון זמני גיבוי בגרף ה-VM** (צ'קבוקס `💾 הצג זמני גיבוי בגרף`) — ראו "שינויים מרכזיים — גרסה 4.11.0"
- **Right-sizing** (`vcenter_rightsizing.html`, `perf_rightsizing.py`) — המלצות הקטנה/הגדלה לפי נתוני הביצועים

### ✅ vCenter Change Tracking — חדש בגרסה 4.3

דף `/vcenter/changes` — מעקב אחר שינויים ב-VMs בכל 3 הסביבות (TC / PT / Fattal)

**תכונות:**
- אירועים: שינוי CPU / RAM / דיסק, הוספה/הסרה של דיסק, יצירה/מחיקה/clone של VM, snapshot
- **עמודת פרטים** — מציגה ערכים לפני ואחרי: `הוגדל: 300GB→400GB`, `4→8 vCPUs`
- **עמודת לקוח** — שם לקוח לפי שייכות VM דרך attribute `SAP_NUMBER` ב-vSphere → `customers` DB
- **סינון VMs אוטומטי** (Backend + JS):
  - Replica VMs (`*replica*`) — שייכות ל-DR, לא שינוי ידני
  - Veeam VMs (`*veeam*`) — פרוצדורת גיבוי אוטומטית
  - AL-Lifesaver (`*lifesaver*`) — שרת גיבוי
  - SRM/DR VMs (accounts עם `srm-`, שמות עם `-phVm`)
- **טבלה עם עמודות קבועות** (`table-layout: fixed`) — VM 22% | לקוח 20% | אירוע 9% | פרטים 22% | משתמש 15% | תאריך 12%
- **יצוא Excel** — Bearer token נכון
- **תוצאות:** TC ~320 אירועים, PT ~11, Fattal ~22

**תיקון קריטי — TC vCenter:**  
`app.py` קורא `VCENTER_TC8_HOST` אך `.env` הכיל `VCENTER_TC_HOST` (חסר "8").  
הוספו משתני `VCENTER_TC8_*` ל-.env (כפילות של `VCENTER_TC_*`) → TC עלה מ-0 ל-320 אירועים.

### ✅ DR Dashboard (`/dr`)
- דף DR מקצה לקצה לפי לקוח
- גילוי SRM אוטומטי דרך vCenter extensionManager
- matching דו-שלבי: prod VMs → SAP → resolve DR replicas
- שרשרת DR אנימציה + RPO badge ב-3 צבעים

### ✅ Veeam Backup — חדש בגרסה 4.2
- **Backup EM** (`/backup`) — `al-veeambem.allegronet.co.il:9398`
  - Session auth (X-RestSvcSessionId)
  - Jobs נגזרים מ-BackupJobSessions (כי `/api/jobs` → 403 ל-VeeamRO)
  - Repos, Sessions
- **PT Backup** (`/backup/pt`) — `al-veeampt.allegronet.co.il:9419`
  - OAuth2 Bearer, `x-api-version: 1.0-rev1`
  - Jobs, Repositories, Recent Sessions
- **Fattal Backup** (`/backup/fattal`) — `ft-vbck.fattal.co.il:9419`
  - אותה תצורה כמו PT Backup
  - סיסמא נפרדת: `VEEAM_FATTAL_PASS` ב-.env
- **TC Backup** (`/backup/tc`) — Veeam B&R TCP-FARM
  - `al-veeamcc.allegronet.co.il:9419`, OAuth2 Bearer
- **Lifesaver Backup** (`/backup/lifesaver`) — `al-lifesaver.allegronet.co.il:9419`
  - Veeam B&R Lifesaver node, OAuth2 Bearer

### ⚠️ מצב חיבוריות נוכחי (Clone Server, 27/07/2026)

- **vCenter Fattal**: תוקן חיבור הרשת, אך נדרשה התאמת credentials. שגיאת `InvalidLogin` אובחנה מה-backend ונפתרה לאחר עדכון ערכי Fattal ב-`.env`.
- **Fattal Backup** (`ft-vbck.fattal.co.il:9419`): כשל DNS בשרת המשובט.
  - backend מחזיר `NameResolutionError` עבור `ft-vbck.fattal.co.il`.
  - `Resolve-DnsName`/`nslookup` לא מחזירים IP תקין לשם זה.
- **PT Backup** (`al-veeampt.allegronet.co.il:9419`): DNS תקין אך אין ניתוב/גישה ליעד.
  - השם נפתר ל-`10.10.76.158`.
  - `Test-NetConnection` לפורט `9419` נכשל (`TcpTestSucceeded=False`).
  - backend מחזיר `ConnectTimeoutError`.

**פעולות נדרשות מצוות תקשורת/תשתיות:**
- להוסיף/לתקן רשומת DNS עבור `ft-vbck.fattal.co.il` על ה-DNS של השרת המשובט.
- לפתוח/לאפשר תעבורה TCP `9419` מהשרת הזה אל `10.10.76.158` (PT Veeam).
- לאמת מסלול חזרה (return path) וחוקי FW בין סגמנט השרת (`10.114.x.x`) לרשת PT.

### ✅ Executive Summary (`/admin/overview`)
- דף `admin_overview.html` — סיכום כל הסביבות עבור הנהלה
- KPI cards, טבלאות מצב, תמצות נתוני vCenter + Infinidat + Backup

### ✅ Light/Dark Mode — חדש בגרסה 4.2
- כפתור ☽/☀ בסרגל העליון (header) בכל הדפים
- `body.light-mode` CSS class עם `!important` overrides
- שמירת העדפה ב-`localStorage('cockpit_theme')`
- כיסוי כל רכיבי ה-UI: vCenter, Infinidat, Backup, Compare, Devices

### ✅ Customer Management
- טבלת `customers` ב-SQLite
- API: GET/POST/PUT/DELETE + import
- **548 לקוחות** — 543 יובאו מ-Excel המקורי + 5 נוספו ב-22/09/2026 מסנכרון מול `לקוחות מעודכן.xlsx`

### ✅ אימות והרשאות — חדש בגרסה 4.7
- **Microsoft Entra ID SSO** — OAuth2 Authorization Code מלא מול `login.microsoftonline.com`
- **כניסה עם שם משתמש/סיסמה — מקומית בלבד** (AD דרך LDAP, או משתמש local fallback)
- **Allow-list** — טבלת `authz_users`; משתמש Entra שאינו ברשימה מקבל `?error=unauthorized_user`
- דף **ניהול הרשאות** (`/admin/permissions`) + פאנל SSO/SSL ב-`/admin/overview#sso`
- דף התחברות ייעודי `login.html` — מציג את אפשרויות הכניסה לפי ה-IP של הפונה

### ✅ עוזר AI — חדש בגרסה 4.7
- Widget צף (🤖) בפינה השמאלית-תחתונה של כל דף, נבנה ב-`sidebar.js`
- Backend: `POST /api/ai/chat` → `ollama_client.py` → שרת Ollama פנימי (`10.114.36.10:11434`)
- שולח את טקסט העמוד הנוכחי (עד 6000 תווים) כקונטקסט + 20 הודעות היסטוריה

### ✅ vCenter History — חדש בגרסה 4.7
- דף `/vcenter/history` — צילומי מצב (snapshots) של מלאי ה-VMs מכל הסביבות
- השוואה בין שתי נקודות זמן (גרסה↔גרסה או גרסה↔מצב חי): נוספו / הוסרו / שונו משאבים
- דוח מקובץ **לפי לקוח** עם דלתות CPU / RAM / דיסק
- **בדיקת קישוריות לפני שמירת גרסה** — חדש 4.8; לחיצה על "שמור מצב נוכחי" בודקת `/ping` מול כל 4 vCenters במקביל; אם אחד לא מגיב, מוצגת אזהרה באנגלית (שם הסביבה שנכשלה) עם בחירה: להמשיך ולשמור בכל זאת, או לבטל ולתקן קודם
- **מי שינה ומתי** בדוח ההשוואה — חדש 4.8; לכל שרת "שונה" בדוח, המערכת מחפשת ב-Change Tracking (`vcenter_events`) את אירוע ה-`VmReconfiguredEvent` הרלוונטי **בדיוק בטווח הזמן שבין שתי הגרסאות שנבחרו** (לא סתם האירוע האחרון), ומציגה שם משתמש + תאריך; אם לא נמצא אירוע תואם — "מי/מתי לא ידוע" במקום לנחש
- **יצוא Excel מעוצב** — חדש 4.8; נבנה מחדש עם ספריית **ExcelJS** (ראו סעיף תלויות למטה) — כותרות מודגשות בצבע לפי סוג טאב, מסגרות, פסים מוצללים, שורת כותרת קפואה. טאב חדש **"All Servers"** (שונו + ללא שינוי, עם עמודת סטטוס) עם בלוק סיכום בתחתית: לפני/אחרי/Δ/% שינוי לכל משאב על **כלל** השרתים כולל שרתים שנוספו/הוסרו — תואם לכרטיסיות שבמסך
- **Retention הוגדל ל-100** — חדש 4.9 (היה 50); `VM_SNAPSHOT_RETENTION`
- **סנפשוט חודשי אוטומטי מוגן** — חדש 4.9; thread רקע יוצר סנפשוט ב-1 לכל חודש בשעה 00:01, מסומן `protected=1`, **לא נספר** במגבלת ה-retention ולעולם לא נמחק אוטומטית
- **מחיקת סנפשוט מוגן דורשת סיסמה** — חדש 4.9; `SNAPSHOT_DELETE_PASSWORD`; סנפשוטים רגילים ממשיכים להימחק כרגיל (רק הרשאת admin)
- **אזהרת מחיקה משופרת** — חדש 4.9; מציגה איזו גרסה בדיוק תימחק (תאריך/VM count/מי שמר/הערה) ומדגישה שהפעולה סופית, לפני בקשת אישור
- **חיוב לפי גדילת משאבים** — חדש 4.9; ראו סעיף ייעודי למטה ("הגדרות חיוב לקוחות")

### ✅ vCenter VM Create — חדש בגרסה 4.7
- דף `/vcenter/vm-create` — דוח **תאריכי יצירה** של VMs, מקובץ לפי שנה (לא כלי הקמה)
- מקור: `config.createDate` מ-vSphere; כשחסר — נופל לאירוע היצירה המוקדם ביותר ב-`vcenter_events`

### ✅ הגדרות חיוב לקוחות — חדש בגרסה 4.9
- דף `/admin/billing` (admin בלבד) — לכל לקוח, בנפרד: % גדילה פטורה מחיוב ל-vCPU/RAM/Storage
  (0–100%, לא נעול ל-5–10) + מחיר ₪ אופציונלי ליחידת משאב. לקוח ללא הגדרה = בדיוק כמו קודם, ללא חיוב.
- נוסחה (לכל משאב בנפרד): `לחיוב = max(0, גדילה בפועל − (הבסיס × % הפטור))`; הבסיס הוא ה"לפני"
  של **ההשוואה הספציפית** שנבחרה (לא שנה קלנדרית קבועה); התכווצות משאבים לעולם לא לחיוב
- מוצג בדוח ההשוואה (History): עמודה "💰 לחיוב" בטבלת "לפי לקוח" על המסך + כרטיסיית KPI
  "סה"כ לחיוב" (מופיעה רק אם יש לקוח מוגדר) + עמודות מקבילות בטאב "By Customer" ביצוא Excel
  המלא, וגם בטאב "Summary" של יצוא "לקוח זה" הממוקד

---

## מבנה קבצים — Frontend

| קובץ | מודול | מצב |
|------|--------|------|
| `index.html` | UCS TC | ✅ |
| `pt.html` | UCS PT | ✅ |
| `fattal.html` | UCS Fattal | ✅ |
| `compare.html` | UCS Compare | ✅ |
| `devices.html` | Device Registry | ✅ |
| `customers.html` | ניהול לקוחות | ✅ |
| `dr.html` | DR Dashboard | ✅ |
| `backup.html` | Veeam EM | ✅ |
| `backup_pt.html` | PT Backup | ✅ |
| `backup_fattal.html` | Fattal Backup | ✅ |
| `backup_tc.html` | TC Veeam B&R Backup | ✅ חדש |
| `backup_lifesaver.html` | Lifesaver-TC Backup | ✅ חדש |
| `admin_overview.html` | Executive Summary | ✅ חדש |
| `infinidat_tc.html` | Infinidat TC iBox-03 | ✅ |
| `infinidat_tc_old.html` | Infinidat Old-TC | ✅ |
| `infinidat_pt.html` | Infinidat PT | ✅ |
| `vcenter_tc.html` | vCenter TC | ✅ |
| `vcenter_tc8.html` | vCenter TC8 | ✅ |
| `vcenter_pt.html` | vCenter PT | ✅ |
| `vcenter_fattal.html` | vCenter Fattal | ✅ |
| `vcenter_overview.html` | vCenter — כל הסביבות | ✅ |
| `vcenter_cluster_detail.html` | vCenter — פירוט קלסטר (גאג'ים + ממצאים) | ✅ חדש |
| `vcenter_changes.html` | vCenter Change Tracking | ✅ |
| `vcenter_history.html` | vCenter — צילומי מצב + השוואת גרסאות | ✅ חדש 4.7 |
| `vcenter_vm_create.html` | vCenter — דוח תאריכי יצירת VMs לפי שנה | ✅ חדש 4.7 |
| `login.html` | דף התחברות (סיסמה מקומית / Entra SSO) | ✅ חדש 4.7 |
| `permissions.html` | ניהול הרשאות (allow-list) | ✅ חדש 4.7 |
| `billing_config.html` | הגדרות חיוב לקוחות (% פטור + מחירי משאבים) | ✅ חדש 4.9 |
| `sidebar.js` | Sidebar + Light/Dark toggle + widget עוזר AI | ✅ עודכן 4.7 |
| `auth.js` | סנכרון session מול `/api/auth/session`, CSRF helper, logout | ✅ עודכן 4.7 |
| `xlsx.full.min.js` | SheetJS vendored locally (930 KB) — קריאה בלבד, **לא תומך בכתיבת עיצוב** | ✅ חדש |
| `exceljs.min.js` | ExcelJS vendored locally (~925 KB) — ליצוא Excel מעוצב (כותרות צבעוניות, גבולות, freeze) | ✅ חדש 4.8 |
| `infinidat.js` | JS משותף Infinidat | ✅ עודכן 4.8 (badge דגם) |
| `style.css` | Global theme + Light mode CSS | ✅ עודכן |

---

## מבנה קבצים — Backend

| קובץ | תיאור | הרשאות |
|------|--------|---------|
| `app.py` | FastAPI routes + כל ה-routers | BUILTIN\Administrators (נעול) |
| `database.py` | SQLite helpers | BUILTIN\Administrators (נעול) |
| `ucs_client.py` | UCS XML API | BUILTIN\Administrators (נעול) |
| `infinidat_client.py` | Infinidat REST API | BUILTIN\Administrators (נעול) |
| `vcenter_client.py` | vCenter pyVmomi + SRM | rona_support (ניתן לכתיבה) |
| `veeam_client.py` | Veeam EM — session auth, port 9398 | rona_support (ניתן לכתיבה) |
| `veeam_br_client.py` | Veeam B&R — OAuth2, port 9419 | rona_support (ניתן לכתיבה) |
| `auth.py` | JWT (HS256) + bcrypt + אימות AD דרך LDAP | rona_support (ניתן לכתיבה) |
| `ollama_client.py` | לקוח שרת Ollama הפנימי (עוזר AI) | rona_support (ניתן לכתיבה) |
| `.env` | Credentials (נעול: Administrators + SYSTEM בלבד) | BUILTIN\Administrators (נעול) |

> **שינויים לקבצים נעולים:** יש להשתמש ב-`py script.py` דרך `Start-Process cmd -Verb RunAs`

---

## סקריפטי ניהול

| קובץ | מטרה |
|------|-------|
| `write_sidebar.py` | כותב `sidebar.js` + light mode CSS (חייב elevation) |
| `setup_veeam_pass.ps1` | מגדיר `VEEAM_PASS` ב-.env (Read-Host AsSecureString) |
| `setup_fattal_pass.ps1` | מגדיר `VEEAM_FATTAL_PASS` ב-.env (Read-Host AsSecureString) |
| `scripts/setup_vcenter_tc8_credentials.ps1` | מגדיר `VCENTER_TC8_USER`/`VCENTER_TC8_PASS` ב-.env — חדש 4.8; **ללא self-elevation** (יש להריץ מחלון PowerShell מורם ידנית — self-elevation דרך `Start-Process -Verb RunAs` גרם ל-stdin שבור ול-`Read-Host` ריק אצל המשתמש) |
| `install_service.ps1` | התקנת שירות NSSM |
| `stop_server.ps1` | עצירת שירות |

---

## Credentials — .env

```
VEEAM_PASS=<סיסמא Veeam EM + PT>
VEEAM_FATTAL_PASS=<סיסמא Fattal Backup>
VEEAM_EM_HOST=al-veeambem.allegronet.co.il:9398
VEEAM_PT_HOST=al-veeampt.allegronet.co.il:9419
VEEAM_FATTAL_HOST=ft-vbck.fattal.co.il:9419
VEEAM_USER=al-lifesaver\VeeamRO
VEEAM_FATTAL_USER=al-lifesaver\VeeamRO

# Security hardening (Round 2)
CORS_ALLOWED_ORIGINS=["https://localhost:9000"]   # origins מורשים
TRUSTED_PROXIES=127.0.0.1,::1                     # IPs של reverse proxy לXFF
INFRA_CA_BUNDLE=                                   # נתיב CA bundle / true / false
DB_ENCRYPT_KEY=                                    # מפתח הצפנת סיסמאות devices

# Authentication (4.7) — JWT_SECRET הוא חובה; בלעדיו השירות לא עולה כלל
JWT_SECRET=<random hex 64>                         # python -c "import secrets;print(secrets.token_hex(32))"
JWT_EXPIRE_HOURS=8
AD_SERVER=                                         # ריק = אימות AD מכובה
AD_DOMAIN=allegronet.co.il
AD_BASE_DN=DC=allegronet,DC=co,DC=il
AD_ADMINS_GROUP=Tatayas Admins                     # חברות בקבוצה ⇐ role=admin
AD_USERS_GROUP=Tatayas Users                       # חברות בקבוצה ⇐ role=user
LOCAL_USER_1=<username>                            # משתמש fallback מקומי (תמיד admin)
LOCAL_USER_1_HASH=<bcrypt hash>                    # scripts\setup_password.ps1
LOCAL_ONLY_USERS=rona                              # חשבונות מקומיים — רק מה-IPs שלמטה
LOCAL_LOGIN_SOURCE_IPS=127.0.0.1,::1,10.114.6.11   # מאיפה מותרת כניסה עם סיסמה
FORCED_ADMIN_IDENTITIES=rona@allegronet.co.il,rona # admin תמיד, גם ללא allow-list
PERMISSIONS_MANAGERS=rona@allegronet.co.il,rona    # מי רשאי לערוך את ה-allow-list

# Ollama AI assistant (4.7)
OLLAMA_HOST=10.114.36.10
OLLAMA_PORT=11434
OLLAMA_MODEL=                                      # ריק = בוחר אוטומטית את הדגם הראשון
OLLAMA_USER=
OLLAMA_PASS_ENC=                                   # Fernet — scripts\setup_ollama_credentials.ps1

# vCenter History (4.7)
VM_SNAPSHOT_RETENTION=100                          # כמה גרסאות רגילות (לא-מוגנות) לשמור — 4.9: 50→100
SNAPSHOT_DELETE_PASSWORD=<סיסמת מחיקת סנפשוט מוגן> # חדש 4.9 — ר' scripts להגדרה; יש גם ברירת מחדל בקוד אם לא מוגדר כאן
```

> **Entra ID SSO** לא נשמר ב-`.env` אלא בטבלת `auth_settings` ב-DB, ונערך דרך
> `/admin/overview#sso` (tenant_id, client_id, client_secret, redirect_uri, scope).

> קובץ `.env` נעול: `icacls /inheritance:r /grant:r "BUILTIN\Administrators:(R,W)" /grant:r "NT AUTHORITY\SYSTEM:(R,W)"`

---

## Routes — Backend (`app.py`)

### Static Pages
| Path | File |
|------|------|
| `/` | `index.html` |
| `/pt` | `pt.html` |
| `/fattal` | `fattal.html` |
| `/compare` | `compare.html` |
| `/devices` | `devices.html` |
| `/customers` | `customers.html` |
| `/dr` | `dr.html` |
| `/backup` | `backup.html` |
| `/backup/pt` | `backup_pt.html` |
| `/backup/fattal` | `backup_fattal.html` |
| `/backup/tc` | `backup_tc.html` |
| `/backup/lifesaver` | `backup_lifesaver.html` |
| `/admin/overview` | `admin_overview.html` |
| `/admin/permissions` | `permissions.html` — **חדש 4.7** |
| `/admin/billing` | `billing_config.html` — **חדש 4.9** (admin בלבד) |
| `/login` | `login.html` — **חדש 4.7** (הדף היחיד שפתוח ללא אימות) |
| `/management/customers` | `customers.html` (alias ל-`/customers`) |
| `/infinidat/tc` | `infinidat_tc.html` |
| `/infinidat/tc-old` | `infinidat_tc_old.html` |
| `/infinidat/pt` | `infinidat_pt.html` |
| `/vcenter/tc` | `vcenter_tc.html` |
| `/vcenter/tc8` | `vcenter_tc8.html` |
| `/vcenter/pt` | `vcenter_pt.html` |
| `/vcenter/fattal` | `vcenter_fattal.html` |
| `/vcenter/overview` | `vcenter_overview.html` |
| `/vcenter/cluster-detail` | `vcenter_cluster_detail.html` |
| `/vcenter/changes` | `vcenter_changes.html` |
| `/vcenter/history` | `vcenter_history.html` — **חדש 4.7** |
| `/vcenter/vm-create` | `vcenter_vm_create.html` — **חדש 4.7** |

### API — אימות והרשאות (חדש 4.7)
| Method | Path | הרשאה | תיאור |
|--------|------|--------|--------|
| GET | `/api/auth/login-options` | פתוח | האם מותרת כניסה עם סיסמה (לפי IP) והאם Entra פעיל |
| POST | `/api/auth/login` | פתוח, מקומי בלבד | AD → local fallback; מגדיר `auth_token` + `csrf_token` |
| POST | `/api/auth/logout` | פתוח | מוחק עוגיות |
| GET | `/api/auth/session` | cookie | `{username, role, expires_at}` — נקרא ע"י `auth.js` |
| GET | `/api/auth/microsoft/start` | פתוח | redirect ל-Entra + עוגיות `ms_state` / `ms_next` |
| GET | `/api/auth/microsoft/callback` | פתוח | חילוף code→token, בדיקת allow-list, הנפקת JWT |
| GET/PUT | `/api/auth/microsoft/config` | admin | קונפיג SSO (ה-secret מוחזר ממוסך) |
| GET | `/api/authz/users` | permissions-manager | רשימת allow-list + ספירות |
| PUT | `/api/authz/users` | permissions-manager | הוספה/עדכון זהות (`admin` / `readonly`) |
| DELETE | `/api/authz/users/{identity}` | permissions-manager | מחיקה — חסום אם זה ה-admin האחרון |

### API — vCenter History (חדש 4.7)
| Method | Path | הרשאה | תיאור |
|--------|------|--------|--------|
| POST | `/api/vcenter/history/snapshot` | admin | צילום מלאי VMs מכל הסביבות במקביל + pruning |
| GET | `/api/vcenter/history/snapshots` | cookie | רשימת גרסאות |
| GET | `/api/vcenter/history/snapshot/{id}` | cookie | גרסה + פריטיה (אפשר `?environment=`) |
| DELETE | `/api/vcenter/history/snapshot/{id}` | admin | מחיקת גרסה; **חדש 4.9** — אם `protected=1` דורש גם `{password}` ב-body התואם ל-`SNAPSHOT_DELETE_PASSWORD` (403 אם שגוי/חסר) |

### API — הגדרות חיוב (חדש 4.9)
| Method | Path | הרשאה | תיאור |
|--------|------|--------|--------|
| GET | `/api/billing/config` | admin | רשימת כל הגדרות החיוב הקיימות |
| PUT | `/api/billing/config` | admin | יצירה/עדכון (upsert) הגדרת חיוב ללקוח |
| DELETE | `/api/billing/config/{customer_name}` | admin | מחיקת הגדרת חיוב (הלקוח חוזר להיות ללא חיוב) |

### API — נוספים
| Method | Path | הרשאה | תיאור |
|--------|------|--------|--------|
| POST | `/api/ai/chat` | cookie | צ'אט מול Ollama — `{message, history, context}` |
| GET | `/api/vcenter/events/poll` | admin | הפעלת poll ידני (`hours`, מקס' 720) |
| GET | `/api/vcenter/events/export` | cookie | יצוא Excel של אירועי השינויים |
| GET | `/api/ibox/{id}/replicas/detailed` | cookie | Replicas + היסטוריית jobs + RPO |
| GET | `/health` | — | בדיקת חיות |

---

## DB Schema — עדכני

```sql
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sap_number TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE ibox_capacity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ibox_id TEXT NOT NULL,
    recorded_at INTEGER NOT NULL,
    phys_free_tb REAL, phys_total_tb REAL, phys_pct REAL
);

CREATE TABLE devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm TEXT, name TEXT, type TEXT, role TEXT,
    host TEXT, ip_address TEXT, ilo_address TEXT,
    username TEXT, password TEXT,
    port INTEGER DEFAULT 443, protocol TEXT DEFAULT 'https',
    notes TEXT, enabled INTEGER DEFAULT 1
);

CREATE TABLE manual_data (
    farm TEXT, server_key TEXT, assignment TEXT,
    cabinet TEXT, vcenter TEXT, notes TEXT,
    PRIMARY KEY (farm, server_key)
);

CREATE TABLE vm_notes (                 -- תפקיד השרת + איפיון
    environment TEXT NOT NULL, vm_name TEXT NOT NULL,
    note TEXT DEFAULT '', classification TEXT DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (environment, vm_name)
);

CREATE TABLE vcenter_events (           -- Change Tracking (append-only)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment TEXT NOT NULL, event_key INTEGER NOT NULL,
    event_type TEXT NOT NULL, vm_name TEXT, user_name TEXT,
    timestamp TEXT NOT NULL, change_info TEXT, description TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);                                      -- UNIQUE(environment, event_key)

CREATE TABLE vm_sap_cache (             -- VM → מס' פריוריטי, מתמלא מכל summary
    vm_name TEXT NOT NULL, environment TEXT NOT NULL,
    sap_number TEXT DEFAULT '', updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (vm_name, environment)
);

-- ── חדש 4.7 ──────────────────────────────────────────────────────────────

CREATE TABLE auth_settings (            -- קונפיג Entra SSO (key/value)
    key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE authz_users (              -- allow-list להתחברות SSO
    identity TEXT PRIMARY KEY,          -- מנורמל: lowercase, ללא DOMAIN\
    username TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'readonly',   -- admin | readonly
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE vm_snapshots (             -- צילומי מצב של מלאי ה-VMs
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL, taken_by TEXT, note TEXT,
    vm_count INTEGER DEFAULT 0, envs_ok TEXT DEFAULT '',
    protected INTEGER DEFAULT 0         -- חדש 4.9: 1=גיבוי חודשי אוטומטי, לא נספר ב-retention,
);                                      --          מחיקה דורשת SNAPSHOT_DELETE_PASSWORD

CREATE TABLE vm_snapshot_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL, environment TEXT NOT NULL,
    vm_name TEXT NOT NULL, sap_number TEXT, cluster TEXT, power_state TEXT,
    num_cpu INTEGER, memory_gb REAL,
    storage_committed_gb REAL, storage_uncommitted_gb REAL,
    data_json TEXT NOT NULL             -- ה-VM המלא כ-JSON
);

-- חדש 4.9
CREATE TABLE customer_billing_config (  -- % גדילה פטורה + מחיר ליחידת משאב, לפי customer_name
    customer_name TEXT PRIMARY KEY,     -- (לא sap_number — תואם למפתח הקיבוץ בדוח)
    enabled INTEGER DEFAULT 1,
    free_pct_cpu REAL DEFAULT 5, free_pct_ram REAL DEFAULT 5, free_pct_stor REAL DEFAULT 5,
    price_vcpu REAL DEFAULT 0, price_ram_gb REAL DEFAULT 0, price_storage_gb REAL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- חדש 4.9.1
CREATE TABLE vm_snapshot_env_data (     -- summary_json מלא (VMs+Hosts+Clusters+Datastores) לכל
    id INTEGER PRIMARY KEY AUTOINCREMENT, --  environment בכל snapshot; לצורך דשבורד חיצוני read-only
    snapshot_id INTEGER NOT NULL, environment TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    UNIQUE(snapshot_id, environment)
);
```

> כל הטבלאות נוצרות/עוברות מיגרציה אוטומטית ב-`init_db()` בעליית השירות.

---

## Service — NSSM

```
Service Name : UcsDashboard
Executable   : python.exe
Arguments    : -m uvicorn app:app --host 0.0.0.0 --port 9000 --ssl-keyfile key.pem --ssl-certfile cert.pem
Working Dir  : C:\Cloude\Projects\DsahBoard-UCS-Test\backend
Account      : LocalSystem
Auto-start   : Yes
```

```powershell
Start-Service   UcsDashboard
Stop-Service    UcsDashboard
Restart-Service UcsDashboard
Get-Service     UcsDashboard
```

---

## שינויים מרכזיים — גרסה 4.11.0 (08/10/2026)

### קישור מכותרת ה-vCenter
- בדפי vCenter ‏(`vcenter_tc.html`, `vcenter_tc8.html`, `vcenter_pt.html`, `vcenter_fattal.html`) באדג' שם השרת (`#vc-host`)
  הוא עכשיו קישור (`target=_blank`) ל-`https://<ping.host>/ui` — ה-vSphere Client של אותו vCenter.
  אם ה-ping לא החזיר host, הבאדג' נשאר טקסט.

### סימון זמני גיבוי בגרף ביצועי VM (`vcenter_perf.html`)
מטרה: לדעת אם אנומליה ב-CPU/RAM נגרמה מגיבוי.

- **Endpoint חדש:** `GET /api/vcenter/perf/backups?name=<VM>&days=N[&debug=true]` ב-[app.py](backend/app.py).
  מחפש את ה-VM (לפי שם, גם בלי הדומיין) ב-4 שרתי Veeam B&R — PT / Fattal / TC / Lifesaver — ומחזיר
  `points: [{server, time, kind, job, start, end}]` בשעון מקומי, `types` (ספירה לפי שרת|job|סוג), `errors`.
  מאחורי אותו אימות כמו שאר ה-API (cookie `auth_token`).
- **Veeam client** ([veeam_br_client.py](backend/veeam_br_client.py)): `get_restore_points`, `get_backups_map`,
  `get_raw_sessions`, `get_task_sessions`.
- **הפרדה בין גיבוי לרפליקציה:** ה-restore point של Veeam REST (rev1) **לא כולל `type` ולא שם job** — רק `backupId`.
  לכן השם נלקח מ-`/backups` והסיווג הוא **לפי שם ה-job** (`_REPLICA_RE` — `snap|replica|rep|target`):
  jobs כמו `FT-Rep-1` / `FT-Rep-1-target` = `replica` (נקודה שעתית של רפליקציית VM, נראית כסנאפשוט), השאר = `backup`.
  בנוסף (`_bk_mark_frequent_as_replica`): job שיש לו ≥6 נקודות והמרווח החציוני ביניהן ≤90 דק' מסווג כרפליקציה גם אם שמו לא תואם
  (הנחה: גיבויים אמיתיים רצים לכל היותר כמה פעמים ביום). נתגלה על `FTDB101 - MAINDB` שם ה-job השעתי לא כלל `rep`.
- **טווח זמן:** לנקודות `backup` — התאמה ל-session של ה-job (סטייה 3 דק') ואז `taskSessions` של ה-VM להתחלה/סיום מדויקים;
  fallback לטווח ה-session כולו; ואם אין — רק זמן יצירת הנקודה. לרפליקציה אין טווח.
- **Frontend:** שני צ'קבוקסים בסרגל — `💾 הצג זמני גיבוי בגרף` ו-`כולל רפליקציה / סנאפשוט` (שניהם כבויים כברירת מחדל,
  נשמרים ב-localStorage: `perf-bk`, `perf-bksnap`). כבוי = אין קריאה לשרתי הגיבוי בכלל.
  קו כתום = גיבוי, טורקיז דק = רפליקציה; גיבוי ארוך מצויר כפס שקוף. Tooltip: שעה (עם שניות אם <דקה) או טווח + משך, job ושרת.
- **אין גיבוי / כשל:** מוצג "⚠ לא נמצא גיבוי לשרת בטווח הזה" (עם מספר נקודות רפליקציה אם יש) או
  "לא ניתן היה לבדוק גיבויים" בשגיאה/timeout. השרתים נשאלים **במקביל** עם תקרה של 40 שנ' (`_BK_DEADLINE`);
  בצד הדפדפן ביטול אחרי 45 שנ'. Cache: אובייקטים/jobs 15 דק', נקודות/sessions 10 דק'.
- **התאמת שם VM↔Veeam** (`_bk_name_variants`): שם מלא → בלי תיאור בסוגריים (`RKT-DB (Rakuto…)` → `rkt-db`) → שם קצר בלי דומיין. אינדקס האובייקטים כולל את אותם aliases (שם מדויק תמיד קודם); `debug=true` מחזיר `tried` ו-`matched_by`. סיכון: שמות קצרים שכיחים עלולים להתאים ל-VM אחר.
- **מגבלות:** רזולוציית הגרף שעתית (בטווחים ארוכים יומית); ההתאמה בין vCenter ל-Veeam היא לפי שם VM; Enterprise Manager לא נכלל;
  סנאפשוטי Infinidat לא נכללים.
- **אימות:** לא נבדק מול נתוני Veeam ל-VM עם job גיבוי רגיל וטווחי session/task — לוודא אחרי deploy.

### ESXi ועומס רגעי בדף הביצועים (`vcenter_perf.html`)
- **מטרה:** לדעת על איזה ESXi יושב כל VM ואם ה-host עמוס — מידע רגעי למקרה של איטיות בשרת שאין לו בעיית משאבים. **לא נשמר ולא מופיע בגרף.**
- **איסוף חי:** `collect_perf_samples` מוסיף `runtime.host` לכל VM; `collect_host_live(si)` ב-[vcenter_client.py](backend/vcenter_client.py)
  שולף CPU/RAM/ליבות/מצב חיבור/Maintenance לכל ESXi (מעבר PropertyCollector קל אחד). `_update_live` ב-[perf_collector.py](backend/perf_collector.py)
  רץ בכל דגימה (דקה) ושומר ב-`perf_collector.live` (זיכרון בלבד) לכל env: `hosts` (עומס + פסק דין), `vm_host` (VM → host).
- **פסק דין לכל host** (`_host_verdict`): 🟢 תקין / 🟠 בינוני / 🔴 גבוה / ⚫ לא זמין. ספים: CPU ≥75/90%, RAM ≥85/95%,
  CPU Ready ממוצע של ה-VMs על ה-host ≥3/5% לכל vCPU, יחס vCPU:ליבה >4:1 (אזהרה). ה-reasons מוצגים בכרטיס וב-tooltip.
- **API:** `GET /api/vcenter/perf/hosts` → `{envs: {env: {age_s, hosts, vm_host}}}`.
- **UI:** צ'קבוקס `🖥 הצג ESXi (עומס רגעי)` (localStorage `perf-esxi`): עמודת ESXi בטבלה (נקודת צבע + שם host + tooltip),
  וכרטיס עומס מעל הגרף בפתיחת שרת (CPU, RAM, Ready, מספר VMs, vCPU:ליבה, 3 ה-VMs העמוסים ביותר, גיל הנתון). נוספת עמודת ESXi ביצוא Excel.
- **מגבלות:** אין נתון עד ~דקה אחרי הפעלת השירות; לא מוצג cluster; Ready ברמת host הוא ממוצע ה-VMs ולא counter של ה-host עצמו;
  RAM ה-host הוא `overallMemoryUsage` (כולל cache) ולכן הסף גבוה. **לא נבדק מול vCenter אמיתי בזמן הכתיבה.**
- **תיקון בדרך:** ב-`drawChart` ה-regex של טווח הזמן (`/^(\d+)([hd])$/`) איבד backslash, כך שימי הגיבוי תמיד היו 7; תוקן. כנ"ל ב-`exportExcel`.

### לייטנסי דיסקים ל-VM (`vcenter_perf.html`) — חלק א'
- **מטרה:** בפתיחת שרת — לייטנסי/IOPS/קצב לכל דיסק וירטואלי, כדי לברר איטיות שאינה CPU/RAM. חי, לא נשמר, לא בגרף.
- **Endpoint:** `GET /api/vcenter/perf/disks?env=&name=` ב-[app.py](backend/app.py) — פותח session קצר ל-vCenter של ה-env, cache של 30 שנ'.
  `collect_vm_disks` ב-[vcenter_client.py](backend/vcenter_client.py): מוצא את ה-VM לפי שם, ממפה דיסק↔instance (`scsi0:1`/`sata`/`nvme`/`ide`)
  ושואל `virtualDisk.totalRead/WriteLatency`, `numberRead/WriteAveraged`, `read/write` (realtime 20 שנ', 15 דגימות ≈ 5 דקות): ממוצע + שיא ללייטנסי.
- **ספים:** אזהרה ≥20ms, קריטי ≥30ms (`_DISK_LAT_WARN/_CRIT`); אזהרה גם אם השיא ב-5 דק' ≥30ms.
- **UI:** צ'קבוקס `💽 הצג לייטנסי דיסקים` (localStorage `perf-disk`); טבלת דיסקים (Datastore, גודל, Read/Write ms, IOPS, MB/s) מעל הגרף בפתיחת שרת.
- **מגבלות:** שרת כבוי = אין נתון; הלייטנסי הוא כפי שה-ESXi רואה (כולל תור ב-host), לא ערך שהאחסון מדווח; אין היסטוריה.
- **חלק ב' (לא נעשה):** לייטנסי ברמת Volume באינפינידט — דורש מיפוי datastore→LUN (`naa`)→serial של ה-volume ו-endpoint מדדי volume ב-iBox (לא נבדק אם קיים ב-v7.3/v8.1).
- **לא נבדק מול vCenter אמיתי** בזמן הכתיבה.

### לחץ זיכרון מצד ה-host בדף הביצועים (גרסה 4.11)
- **מטרה:** לזהות VM שה-host מצר לו זיכרון (שה-RAM % הרגיל — זיכרון פעיל — לא מראה). אותו מנגנון כמו CPU Ready: דגימה כל דקה, נשמר ב-roll-up שעתי/יומי.
- **מדדים (`collect_mem_pressure` ב-[vcenter_client.py](backend/vcenter_client.py), realtime 20 שנ', ממוצע ~דקה):**
  `mem.swapped` (זיכרון שנזרק לדיסק — כל ערך >0 חמור), `mem.vmmemctl` (Balloon — זיכרון שנגזל), `mem.latency` (% זמן המתנה לזיכרון בגלל דחיסה/swap).
- **DB:** עמודות חדשות ב-`vm_perf_hourly/daily` (מתווספות אוטומטית ב-`init_perf_tables`): `mp_swap_max_mb, mp_balloon_max_mb, mp_lat_max_pct, mp_lat_max_ts, mp_samples, mp_n_balloon, mp_n_swap, mp_n_lat`.
  ב-`perf_collector` ה-acc הורחב ל-25 איברים (17–24). נתונים ישנים מציגים "—" עד שנצברים.
- **ספים:** 🔴 swap>0 או Memory Latency ≥5%; 🟠 Balloon>0 או latency ≥1% (`MEM_LAT_WARN/CRIT` ב-perf_store — היוריסטיקה, לא תקן).
- **UI:** צ'קבוקס `🧠 הצג לחץ זיכרון` (localStorage `perf-mem`) — עמודה "לחץ זיכרון" (tooltip עם מקסימומים ודקות), שורת לקוח מציגה כמה שרתים בלחץ, מיון, ו"הצג רק שרתים שעברו את הסף" כולל אותה; 3 עמודות ביצוא Excel.
- **ESXi:** כרטיס ה-host מציג גם כמה VMs עם swap/balloon על אותו host (swap = קריטי, balloon = אזהרה).
- **מגבלה:** מזהה רק לחץ שה-host גורם. VM שמוגדר קטן מדי לאפליקציה (paging בתוך מערכת ההפעלה) לא נראה מ-vCenter — דורש מדדי guest (למשל PRTG).
- **לא נבדק מול vCenter אמיתי.**

### 🩺 "נתח שרת" — אבחון אוטומטי + הקשר מובנה ל-AI (גרסה 4.11)
- **מנוע כללים דטרמיניסטי** ב-[perf_diagnose.py](backend/perf_diagnose.py): ממצאים לפי חומרה (CPU, Ready, Co-Stop, Limit, לחץ זיכרון, זיכרון, ESXi, דיסק, גיבוי) עם "מה לעשות", ותשובה ל"האם צריך עוד CPU" (לא אם יש Limit / Co-Stop / תחרות על ה-host; אולי רק כשאין תחרות והעומס לגיטימי). אותם ספים/דרגות כמו הדף (מד עומס, מד Ready). כל טקסט בעברית **ובאנגלית**.
- **Endpoint:** `GET /api/vcenter/perf/diagnose?env=&name=&range=` — מאחד סיכום מה-DB (`perf_store.get_summary` עם פרמטר `vm`), ה-ESXi החי, לייטנסי דיסקים חי וגיבויים (במקביל, עד 45 שנ').
- **UI:** כפתור `🩺 נתח שרת` בראש כל שרת פתוח (`vcenter_perf.html`), מתג עברית/English (localStorage `perf-diag-lang`), וכפתור `💬 הסבר מפורט (AI, באנגלית)` ששולח את הנתונים המובנים ל-`/api/ai/chat`. ההסבר של ה-AI תמיד באנגלית (מודל מקומי — עברית לא אמינה).
- **צ'אט צף 🤖:** `sidebar.js` קורא ל-`window.aiExtraContext()` של הדף (אם קיים) ומקדים אותו כ-`STRUCTURED SERVER DATA` להקשר (נשאר תקציב ל-טקסט הדף); `_AI_SYSTEM_PROMPT` הורחב עם הספים וכללי ההחלטה. כך הצ'אט מכיר את השרת האחרון שנותח.
- **בדיקת מודל ה-AI** ([ai_benchmark.py](backend/ai_benchmark.py), endpoints ל-admin בלבד): `GET /api/ai/models` (מודל מוגדר / מותקנים / טעונים + `size_vram_gb` = כמה על ה-GPU), `GET /api/ai/benchmark/start?model=NAME` (רץ ברקע, אחד בכל פעם), `GET /api/ai/benchmark/results?format=text`.
  4 תרחישים סינתטיים עם תשובה ידועה (A תהליך תקוע, B עומס host, C swap, D שרת תקין) עוברים את מנוע הכללים ואז למודל באותו prompt; נרשמים זמן, tok/s ו**מספרים שהמודל המציא** (לא קיימים בנתונים) — את התשובות משווים ל-`EXPECTED`.
- **תיקון נוסף (FT-SENSELOAD-1):** "תחרות על ה-host" נקבעת לפי CPU/Ready של ה-host בלבד (`host_cpu_busy`); RAM גבוה ב-host הוא ממצא נפרד (ESXi) ולא מסביר CPU. נוסף ענף "עומס קופצני": ממוצע CPU <50% אבל ≥85% ב-≥5% מהזמן, בלי תחרות → "לא בהכרח, רק אם הקפיצות פוגעות" (batch/ETL), עם אזהרת NUMA לשרת גדול.
- **תיקון לוגיקה (FT-SQL-1):** "תחרות על ה-host" נקבעת רק אם ה-host באמת עמוס (`host_busy`: CPU≥75%, Ready≥3%, RAM≥85%, swap או לא מחובר) או ש-Ready של ה-VM מתמשך; אזהרת ESXi שנובעת רק מיחס vCPU:ליבה מוצגת כ-info ("תכנון קיבולת") ואינה מסבירה את ה-CPU של השרת. נוסף ענף: ממוצע CPU ≥50% ללא תחרות → "כנראה כן צריך עוד CPU" עם הערכת vCPUs (≈ vCPU×ממוצע/55, זוגי) והנחיה לבדוק קודם מי צורך CPU בתוך השרת.
- **דירוג האבחון (כיול הכללים):** בתחתית "נתח שרת" כפתורי 👍 נכון / 🤔 חלקי / 👎 לא נכון (+ בחירת ממצא והערה קצרה). נשמר בטבלה `diag_feedback` (ב-`perf_store.py`) יחד עם צילום האבחון והנתונים שראה. `POST /api/vcenter/perf/diagnose/feedback` (כל משתמש מחובר, מוגבל ל-40KB), `GET /api/vcenter/perf/diagnose/feedback?format=text` (admin) — תקציר לסקירה: ספירה לפי דירוג ולפי תחום, וכל רשומה עם facts. **תהליך הכיול:** מפעילים, אוספים דירוגים, ומתקנים ספים/כללים ב-`perf_diagnose.py` לפי הדפוסים (לא אימון מודל ולא שינוי אוטומטי של ספים).
- **מודל ה-AI (תוצאות benchmark 09/10/2026):** `aya-expanse:8b` (71 tok/s) מהיר אך מגזים ו**המציא סיבה לשרת תקין**; `qwen2.5:14b` (~50 tok/s, 5-6 שנ') נאמן יותר ומדויק יותר; `qwen2.5:32b` (4.9 tok/s, 50-80 שנ') לא טוב יותר. לכן `ollama_client.OLLAMA_PREFERRED_MODEL=qwen2.5:14b` הוא ברירת המחדל כש-`OLLAMA_MODEL` ב-`.env` ריק (ואם מותקן); `.env` עדיין גובר. `OLLAMA_KEEP_ALIVE` (ברירת מחדל 60m) משאיר את המודל טעון נגד cold start של ~1 דקה. ה-system prompt הורחב: לא להגזים, ולשרת תקין — "אין צורך בפעולה" בלי המצאת סיבה / רשימת בדיקות כלליות.
- **מגבלות:** מסנן ראשוני, לא מחליף בדיקה בתוך השרת; איכות הסבר ה-AI תלויה במודל ה-Ollama (לא נבדק איזה מודל מוגדר); לא נבדק מול נתוני אמת (הלוגיקה נבדקה על נתוני דוגמה).

### מד Ready — בעיה מתמשכת ולא פיק (גרסה 4.11)
- תג (🟢 ⚪ 🟠 🔴) ראשון בקבוצת עמודות Ready (`readyLevel` ב-`vcenter_perf.html`), מבוסס **דקות מעל סף** ולא על פיק: 🔴 = ≥10% ביותר מ-1% מהזמן, או ≥5% ביותר מ-5% מהזמן, או Ready מתמשך (`ready_hot_buckets`: ≥5 דק'/שעה או ≥10 דק'/יום מעל 5%) בלפחות 3 שעות/ימים שמהווים ≥20% מהטווח; 🟠 = ≥5% ביותר מ-1% מהזמן או בשעתיים/יומיים; ⚪ = נגע ב-5% בלבד.
- ללא נתונים חדשים: משתמש ב-`ready_n_warn/crit` ו-`ready_samples` הקיימים + שדה חדש `ready_hot_buckets` ב-`perf_store.get_summary`. הספים הם הצעה ראשונית, לא כוילו.
- ה-KPI "CPU Ready חריג", הסינון "עברו סף", מיון, שורת לקוח, Excel וחלון ההסבר עודכנו ל-מד Ready (מתמשך) ולא ל-פיק.
- **מגבלה:** אורך הרצף הרציף הארוך ביותר לא נשמר (רק סכומים לשעה), ולכן "מתמשך" נמדד בסכום דקות ובמספר שעות/ימים.

### CPU Co-Stop ו-CPU Limit + שילוב ב-Right-Sizing (גרסה 4.11)
- **איסוף:** `collect_cpu_extra` ב-[vcenter_client.py](backend/vcenter_client.py) — `cpu.costop.summation` ו-`cpu.maxlimited.summation` (realtime 20 שנ', אותה נוסחה כמו Ready: ms / (20000 × vCPU) × 100).
  **Co-Stop** = זמן ש-vCPUs ממתינים לאחיהם (≥3% = יותר מדי vCPUs; `COSTOP_WARN/CRIT`). **Limit** = השרת נחסם ע"י CPU Limit שהוגדר עליו (`LIMITED_MIN`=1%).
- **DB:** עמודות `cs_max_pct, cs_max_ts, cs_sum, cs_samples, cs_n_warn, lim_max_pct, lim_n` ב-roll-ups (acc 25–31; migration אוטומטי). מצטבר מרגע ההפעלה.
- **דף ביצועים:** תחת צ'קבוקס `הצג CPU Ready / Co-Stop` נוספו עמודות Co-Stop ו-Limit (+ Excel, סינון "עברו סף", שורת לקוח, חלון ההסבר).
- **Right-Sizing** ([perf_rightsizing.py](backend/perf_rightsizing.py), `_cpu_contention`) — פועל רק על המלצת CPU מהימנה (≥ `min_days`), ורק כשיש ≥3 ימי נתוני Co-Stop:
  - **Limit** על ≥2 ימים → פעולה `limited` ("להסיר Limit לפני כל שינוי"), בלי המלצת vCPU.
  - **Co-Stop חוזר** (P95 של שיא יומי ≥3%) על VM עם ≥3 vCPU: אם ה-CPU אמר "להוסיף" → `contention` (הוספה תחמיר; לבדוק את ה-host); אחרת → **להפחית** כ-25% (מספר זוגי), או מחזק המלצת הפחתה קיימת.
  - ב-UI ([vcenter_rightsizing.html](frontend/vcenter_rightsizing.html)) שתי הפעולות מוצגות כ-`לבדוק (Co-Stop / Limit)` (כתום) עם הסיבה מתחת, ויש אופציה בסינון.
  - Co-Stop לא משנה כלום עד שיש 3 ימים; ביחס ל-14 ימי ה-CPU הנדרשים, הוא יהיה מוכן באותו זמן.
- **לא נבדק מול vCenter אמיתי** (נבדקה הלוגיקה של ה-right-sizing בבדיקה מבודדת בלבד).

### חלון הסבר על המדדים (גרסה 4.11)
- כפתור `❓ הסבר על המדדים` בסרגל דף הביצועים פותח חלון (HTML סטטי ב-`vcenter_perf.html`, `#help-back`; נסגר ב-Esc / לחיצה בחוץ) עם הסבר פשוט בעברית לכל המדדים:
  CPU/RAM/פיק/ממוצע/מד עומס, CPU Ready, לחץ זיכרון, ESXi, דיסקים, הגרף וסימוני הגיבוי, ו"איך מגלים למה שרת איטי".
  **כשמשנים סף או מוסיפים מדד — לעדכן גם את החלון.**
  החלון כולל גם סעיף "🛠 מה לעשות כשמדד חריג" (מה לבדוק ומה מומלץ לכל מדד), וסעיף על Co-Stop/Limit ב-Right-Sizing.

### Deploy
- אחרי שינוי backend צריך `Restart-Service UcsDashboard` כמנהל; אחרי ההפעלה מחדש יש להתחבר מחדש לדשבורד.

---

## שינויים מרכזיים — גרסה 4.10.0 (06/10/2026)

### CPU Ready בדף הביצועים

- **איסוף** — `collect_cpu_ready()` ב-[vcenter_client.py](backend/vcenter_client.py) קורא `cpu.ready.summation`
  (instance ריק = סכום כל ה-vCPUs) דרך `perfManager.QueryPerf`, interval ריאלטיים של 20 שניות, ממוצע 3 הדגימות
  האחרונות (~דקה), בקבוצות של 150 VMs. **אחוז לכל vCPU** = `ready_ms / (20000 × numCPU) × 100`.
  כשל באיסוף Ready לא משבית את איסוף CPU/RAM (נתפס ונרשם ל-log: `[perf] <env> cpu-ready error`).
  `collect_perf_samples` מחזיר כעת גם `_obj` (ה-managed object) לצורך השאילתה.
- **צבירה ואחסון** — ה-accumulator ב-[perf_collector.py](backend/perf_collector.py) הורחב ל-17 שדות; ב-
  [perf_store.py](backend/perf_store.py) נוספו לשתי הטבלאות (`vm_perf_hourly`, `vm_perf_daily`) העמודות
  `ready_max_pct`, `ready_max_ts`, `ready_sum`, `ready_samples`, `ready_n_warn`, `ready_n_crit`
  (מיגרציית `ALTER TABLE` אוטומטית ב-`init_perf_tables()`). `get_summary` / `get_series` מחזירים
  `ready_max_pct`, `ready_max_ts`, `ready_avg_pct`, `ready_samples`, `ready_n_warn`, `ready_n_crit`.
- **ספים** (`READY_WARN=5`, `READY_CRIT=10` ב-`perf_store.py`; לפי הנחיות VMware, לכל vCPU):
  פחות מ-5% תקין · 5–10% ⚠️ אזהרה · 10% ומעלה 🔴 קריטי.
- **UI** — צ'קבוקס `⏱ הצג CPU Ready` בסרגל הכלים (נשמר ב-`localStorage['perf-ready']`): מוסיף עמודות פיק + ממוצע
  (ממיינות), אייקון אזהרה/קריטי עם tooltip, כרטיס KPI "CPU Ready חריג", סיכום ברמת לקוח, הכללה בפילטר "עברו את
  הסף", ו-4 עמודות Ready ביצוא Excel.
- ⚠️ **אין היסטוריה לאחור** — הנתונים מתחילים להצטבר רק אחרי הפעלה מחדש של השירות עם הגרסה הזו.
- ⚠️ הקוד נכתב בלי אפשרות הרצה מקומית (אין Python בסביבת הפיתוח) — **נדרש אימות בפרודקשן** אחרי restart:
  `Restart-Service UcsDashboard`, ולבדוק שעמודות Ready מתמלאות אחרי כמה דקות.

---

## שינויים מרכזיים — גרסה 4.9.1 (22/09/2026)

### 1. גיבוי יומי מלא (VMs + Hosts + Clusters + Datastores) — לצורך גישת דשבורד חיצוני

- **Thread רקע חדש** `daily-snapshot` ([app.py](backend/app.py)) — רץ מדי יום ב-01:15
  (`_seconds_until_next_daily_run(hour=1, minute=15)`), קורא ל-`_take_vm_snapshot(taken_by=
  "system-daily", protected=False)`. מוגן מפני כפילות thread בעליית שירות חוזרת (בדיקת שם
  thread קיים, כמו ה-thread החודשי).
- **טבלת DB חדשה** `vm_snapshot_env_data` — לכל סנפשוט, שומרת את ה-`summary_json` **המלא** של
  `get_summary()` לכל אחת מ-4 סביבות ה-vCenter (VMs, Hosts, Clusters, Datastores, Affinity
  Rules), לא רק VMs כמו שהיה עד כה ב-`vm_snapshot_items`. פונקציות חדשות ב-
  [database.py](backend/database.py): `insert_snapshot_env_data()` (upsert לפי
  `snapshot_id+environment`), `get_snapshot_env_data()`, `has_snapshot_today_by()`.
  `delete_snapshot()` ו-`prune_old_snapshots()` עודכנו למחוק בקסקדה גם מהטבלה החדשה (בלי
  orphans).
- **הסיבה:** דשבורד חיצוני (של מפתח אחר על אותו שרת) צריך גישת קריאה-בלבד לכל הנתונים כולל
  Hosts/Clusters, שלא היו נשמרים ב-DB בעבר (רק ב-cache זמני של 180 שניות בזיכרון). הוחלט
  (בתיאום מול המפתח השני) על **סנאפשוטים יומיים דרך קריאת קובץ SQLite ישירה**, לא API רשת חדש
  — ראו מסמך ייעודי מתחת.
- **נבדק**: 9 תרחישי unit-test על שכבת ה-DB האמיתית (round-trip VMs/Hosts/Clusters/Datastores,
  סינון לפי environment, upsert, `has_snapshot_today_by`, מחיקה בקסקדה ללא orphans) + אימות
  הפעלה חיה בלוג הפרודקשן אחרי restart שירות (`[daily-snapshot] sleeping 10.4h until next run`).

### 2. מסמך הוראות לדשבורד חיצוני — גישת קריאה בלבד

- **[EXTERNAL_DASHBOARD_ACCESS.md](EXTERNAL_DASHBOARD_ACCESS.md)** (חדש) + עותק Word תואם RTL
  `External_Dashboard_Access_Instructions.docx` — הוראות מלאות למפתח דשבורד חיצוני: מיקום קובץ
  ה-DB (+ קבצי WAL/SHM נלווים), פקודת `icacls` להרשאת קריאה-בלבד ברמת NTFS, חיבור
  `sqlite3` ב-`mode=ro`, טבלה מלאה של כל ה-tables הרלוונטיים ותפקידם, שאילתות SQL לדוגמה
  (מציאת הגרסה היומית האחרונה, שליפת `summary_json`, מיפוי לקוחות, רשימת התקנים **בלי עמודת
  password**), וכללי אצבע (never write, אין נתונים חיים, retention 100 ימים).
- **לא נכלל בכוונה**: `auth_settings`, `authz_users` (קונפיגורציית SSO/הרשאות של המערכת עצמה),
  ועמודת `devices.password`.
- **פתוח להשלמה** לפני מסירה למפתח השני: שם חשבון השירות האמיתי (placeholder כרגע
  `DOMAIN\svc-otherdash`) ואישור שתקופת השמירה (100 ימים) מספיקה לצרכיו.

### 3. סנכרון רשימת לקוחות מול קובץ ERP מעודכן

- הושוותה טבלת `customers` (543 רשומות) מול קובץ Excel חיצוני `לקוחות מעודכן.xlsx`
  (ייצוא ERP מלא, 530 שורות, 161 עמודות) לפי `sap_number`. **המדיניות: רק הוספה, אף פעם לא
  מחיקה/שינוי** של לקוח קיים — גם כשנמצא הבדל שם (לקוח 2100062 נשאר ללא שינוי, רק דווח).
- **5 לקוחות חדשים נוספו** (2100531–2100535) דרך `create_customer()` הקיימת ב-
  [database.py](backend/database.py) — ישירות ל-DB החי, בלי restart לשירות. רשומה שישית
  שזוהתה כ-placeholder גנרי של ה-ERP (`2100001` / "לקוח כללי", לא לקוח אמיתי) נוספה ואז נמחקה
  לפי בקשה מפורשת.
- סה"כ לקוחות כעת: **548**.

---

## שינויים מרכזיים — גרסה 4.9.0 (21/09/2026)

### 1. סנפשוטים מוגנים + גיבוי חודשי אוטומטי

- **Retention הוגדל 50→100** — `VM_SNAPSHOT_RETENTION`.
- **עמודת `protected`** נוספה ל-`vm_snapshots` (מיגרציה אוטומטית ב-`init_db()`).
  `prune_old_snapshots()` ([database.py](backend/database.py)) עכשיו מסנן `WHERE protected = 0` —
  סנפשוטים מוגנים **לא נספרים** במגבלת ה-retention ו**לעולם לא נמחקים אוטומטית**, לא משנה כמה
  סנפשוטים רגילים נוצרים אחריהם.
- **Thread רקע חדש** `monthly-snapshot` ([app.py](backend/app.py)) — מחשב את הזמן עד ל-1 לחודש
  הבא בשעה 00:01 (`_seconds_until_next_month_start()`), ישן, ואז קורא ל-`_take_vm_snapshot(...,
  protected=True)`. יש הגנה מפני כפילות (`has_protected_snapshot_today()`) אם השירות עולה מחדש
  יותר מפעם אחת בתוך אותה דקה. **נבדק עם 10 תרחישי תאריך/שעה** (אמצע חודש, גבול מדויק לפני/אחרי
  00:01, מעבר דצמבר→ינואר, שנה מעוברת) — לא ניתן היה לחכות בפועל ל-1 לחודש.
- **מחיקת סנפשוט מוגן דורשת סיסמה** — `SNAPSHOT_DELETE_PASSWORD` (משתנה env, יש גם ברירת מחדל
  בקוד). `DELETE /api/vcenter/history/snapshot/{id}` בודק `snap.protected` ודורש `{password}`
  תואם ב-body; 403 אם שגוי/חסר. סנפשוטים רגילים ממשיכים להימחק כרגיל (הרשאת admin בלבד, בלי סיסמה).
- **אזהרת מחיקה משופרת** בדף History — מציגה במפורש איזו גרסה תימחק (תאריך, VM count, מי שמר,
  הערה) ושהפעולה סופית ולא ניתנת לשחזור, לפני בקשת אישור; לגרסה מוגנת מוצגת גם דרישת הסיסמה
  ומופיע `prompt()` נפרד להקלדתה.

### 2. הגדרות חיוב לקוחות — גדילת משאבים מעל % פטור

- **מסך ניהול חדש** `/admin/billing` (admin בלבד, קישור בסיידבר "💰 הגדרות חיוב") — לכל לקוח בנפרד:
  % גדילה פטורה מחיוב ל-vCPU / RAM / Storage (0–100%, לא נעול לטווח קבוע) + מחיר ₪ אופציונלי
  ליחידת משאב. לקוח ללא הגדרה ממשיך להיות מוצג בדוח **בדיוק כמו קודם**, ללא שום חיוב.
- **טבלת DB חדשה** `customer_billing_config`, מפתוחה לפי `customer_name` (תואם למפתח הקיבוץ
  בדוח, לא `sap_number`) + 3 endpoints חדשים תחת `/api/billing/config`.
- **נוסחת החיוב** (`computeBilling()` ב-[vcenter_history.html](frontend/vcenter_history.html)),
  מחושבת **בנפרד לכל משאב** (vCPU/RAM/Storage כל אחד עם % פטור משלו):
  `לחיוב = max(0, גדילה בפועל − (סה"כ "לפני" × % הפטור / 100))`.
  הבסיס הוא ה"לפני" של **ההשוואה הספציפית** שנבחרה בדוח — לא שנה קלנדרית קבועה, כלומר עובד
  זהה בלי קשר אם משווים בין שתי גרסאות שיומיים או שנתיים הפרש ביניהן. התכווצות משאבים
  (delta שלילי) לעולם לא הופכת לחיוב.
- **מוצג בדוח** — עמודה "💰 לחיוב" בטבלת "לפי לקוח" על המסך + כרטיסיית KPI "סה"כ לחיוב"
  (מוסתרת אם אין אף לקוח מוגדר) + עמודות מקבילות בטאב "By Customer" ביצוא ה-Excel המלא, וגם
  בטאב "Summary" של יצוא "לקוח זה" (`exportReportCustomerExcel`) — **נמצא ותוקן** חוסר בגרסה
  הראשונה של הפיצ'ר שבו יצוא "לקוח זה" לא כלל את נתוני החיוב בכלל.
- **נבדק עם 18 תרחישי חישוב** (בלי הגדרה, מתחת/בדיוק-על/מעל הסף, אחוזים שונים לכל משאב
  בו-זמנית, התכווצות, תמחור, אדישות לפרק הזמן) + **15 בדיקות על שכבת ה-DB** האמיתית
  (`database.py`, לא חיקוי) — יצירה, עדכון (upsert), מיון, מחיקה, לקוח מושבת.

---

## שינויים מרכזיים — גרסה 4.8.0 (20–21/09/2026)

סקירת אבטחה מלאה של הקוד (auth/session/CSRF, injection/SSRF בבקאנד, XSS בפרונטאנד) העלתה כמה
ממצאים אמיתיים שתוקנו, ובמקביל נוספו כמה שיפורי UX לדפי vCenter/Infinidat/History.

### 1. אבטחה — CSRF, Open Redirect, admin-gating

- **`_CSRFMiddleware` הופעל בפועל** ([app.py:125-142](backend/app.py#L125)) — עד עכשיו היה
  pass-through ריק (מגדיר `_MUTATING`/`_EXEMPT` אבל לא משתמש בהם בכלל). עכשיו משווה את עוגיית
  `csrf_token` מול header `X-CSRF-Token` עם `secrets.compare_digest` (הגנה מפני timing attack)
  לכל בקשת POST/PUT/DELETE/PATCH ל-`/api/*` שמזוהה דרך cookie — למעט login/logout ובקשות
  Bearer-token (לא CSRF-able כי לא נשלחות אוטומטית ע"י הדפדפן).
  **תופעת לוואי:** רוב הפרונטאנד לא שלח את ה-header הזה כלל. נדרש לעדכן ידנית כל קריאת
  fetch מסוג POST/PUT/DELETE שהייתה חסרה אותו — `app.js`, `customers.html` (גם נוסף `auth.js`
  שהיה חסר לגמרי מהדף!), `devices.html`, `permissions.html`, `vcenter_history.html`,
  ודפי `vcenter_tc/tc8/pt/fattal.html` (שמירת VM notes/classification).
- **Open Redirect אחרי SSO תוקן** — `next.startswith("/")` היה מקבל גם `//evil.com`
  (URL יחסי-לפרוטוקול). נוספה `_safe_next_path()` ([app.py:107-117](backend/app.py#L107)) שדוחה
  גם `//` וגם `/\`, מיושמת ב-`microsoft/start` וב-`microsoft/callback`. תוקן גם
  ב-`frontend/login.html` — שם **לא הייתה שום ולידציה בצד הקליינט** על `?next=` בכלל.
- **`/health` מחזיר 200** — היה מוגדר ב-`_API_OPEN` אבל הסט הזה נבדק רק לנתיבי `/api/`;
  `/health` לא מתחיל ב-`/api/` אז קיבל 302 ל-login. הועבר ל-`_PAGE_OPEN`.
- **`?refresh=true` בדפי vCenter דורש admin** ([app.py:1038,1061](backend/app.py#L1038)) —
  `summary`/`hosts` לא קראו ל-`_check_admin_refresh()` כמו כל שאר ה-routers (Veeam/DR).
  **השפעה על UX:** כפתור "Refresh" למשתמשי readonly בדפי vCenter מחזיר עכשיו 403 —
  זהה בדיוק להתנהגות שכבר קיימת בדפי Veeam.
- **4 ממצאי XSS תוקנו** — `vcenter_overview.html` (שם VM/לקוח ללא escaping), `backup_lifesaver.html`
  (שם VM/נתיב ללא escaping — רגרסיה מול 3 האחיות), `vcenter_changes.html` (VM name ב-`title`
  attribute), ו-`_fmtNTP()` בארבעת דפי vCenter (שרתי NTP).

### 2. תפקיד שרת + איפיון — רשימות בחירה עם אופציית טקסט חופשי

- **איפיון** — נוספה רשומה **"אלגרונט החדשה"**, ונוספה אופציית **"✏️ אחר (הקלדה חופשית)"**
  שבבחירתה הופך את התפריט לשדה טקסט חופשי (input) שנשמר כרגיל דרך `PUT /vm-classification`.
- **תפקיד שרת** — היה שדה טקסט חופשי בלבד (`<input>`); הפך לרשימת בחירה (`<select>`) עם 21
  ערכים קבועים (DC, SQL, פריוריטי, סאפ, טרמינל, קבצים, מדפסות, ברוקר, ווב, רישיונות, קוקפיט,
  ניהול קוקפיט, סייבס, G4, GOC, FTP, FSlogix, דואר, Entra connect, DB Cache, ממשקים, TSG,
  אפליקציות) + אותה אופציית "✏️ אחר (הקלדה חופשית)".
- שרתים עם ערך קיים שלא נמצא ברשימה (טקסט חופשי שהוזן בעבר) מוצגים אוטומטית כשדה טקסט
  בכניסה הבאה לעריכה — לא נמחקים ולא נדרסים.
- מיושם בכל ארבעת דפי vCenter (`vcenter_tc/tc8/pt/fattal.html`); שיתוף לוגיקה מלא בין
  `handleClassSelect()`/`handleRoleSelect()`, ששניהם קוראים ל-`saveVmClass()`/`saveVmNote()`
  הקיימות (עובדות גנרית על `<select>` וגם `<input>`).

### 3. Infinidat — באדג' דגם (Model)

- שדה `model` נוסף ל-`get_summary()` ([infinidat_client.py:591-594](backend/infinidat_client.py#L591))
  — נשלף מ-`components/nodes`, אותו endpoint ששימש כבר את טאב ה-Health, ללא קריאת API נוספת.
  מוצג כבאדג' חדש בכותרת כל שלושת דפי ה-Infinidat, ליד גרסת התוכנה.

### 4. vCenter History — בדיקת קישוריות, ייחוס שינויים, Excel מעוצב

- **בדיקת קישוריות לפני שמירת גרסה** — כפתור "שמור מצב נוכחי" בודק עכשיו `/ping` מול כל 4
  vCenters במקביל לפני השמירה. אם אחד נכשל, מוצגת אזהרה באנגלית עם שם הסביבה שנכשלה,
  והמלצה לתקן לפני שמירה — עם אפשרות להמשיך ולשמור בכל זאת (OK) או לבטל (Cancel).
- **מי שינה ומתי** — כל שרת "שונה" בדוח ההשוואה מוצג עכשיו עם ייחוס: שם משתמש + תאריך,
  נשלף מ-Change Tracking (`vcenter_events`, `VmReconfiguredEvent`) **בדיוק בטווח הזמן שבין
  שתי הגרסאות שנבחרו להשוואה** — לא "האירוע האחרון אי-פעם", כדי לא לייחס שינוי לאדם/תאריך
  לא נכונים. אם לא נמצא אירוע תואם — "מי/מתי לא ידוע" במקום לנחש.
- **יצוא Excel מעוצב** — הספרייה הקיימת (`xlsx.full.min.js`, SheetJS Community) אומתה כלא-תומכת
  בכתיבת עיצוב תאים (רק קריאה) — נבדק ישירות: workbook עם `.s` styles נכתב, נפתח כ-ZIP,
  ואין שום `<b/>`/`fill` ב-`styles.xml`. נוספה ספריית **ExcelJS** (`frontend/exceljs.min.js`,
  מותקנת מקומית — לא CDN, כדי לשמור על CSP `script-src 'self'`) במיוחד לצורך זה.
  - כותרות מודגשות לבן-על-צבע (צבע שונה לכל סוג טאב: כחול ל-Summary/By Customer, ירוק ל-Added,
    אדום ל-Removed, כתום ל-Changed, אפור ל-Unchanged, כחול-בהיר ל-All Servers), מסגרות דקות,
    פסים מוצללים (zebra) בין שורות, שורת כותרת קפואה (freeze), RTL.
  - **טאב חדש "All Servers"** — שונו + ללא שינוי יחד, עם עמודת סטטוס.
  - **בלוק סיכום בתחתית** אותו טאב (וגם ב-Summary) — לפני/אחרי/Δ/% שינוי לכל משאב, מחושב על
    **כלל** השרתים **כולל שרתים שנוספו/הוסרו** (מסוכם מתוך `totalBeforeCpu`/`totalAfterCpu` של
    כל קבוצות הלקוחות — בדיוק כמו הכרטיסיות שבמסך). ⚠️ בגרסה הראשונה של התכונה הסיכום חושב
    בטעות רק מתוך שרתים ששונו/לא-שונו, בלי שרתים שנוספו/הוסרו — תוקן באותו יום לפני שיצא לשימוש.
  - `exportReportCustomerExcel()` (יצוא ללקוח בודד) עודכן באותו אופן, לעקביות.
  - וּודא ב-Node.js ישירות (לא רק קריאת קוד): כתיבת workbook אמיתי, פתיחה כ-ZIP, ובדיקת
    `styles.xml`/`sheet.xml` — אישר שמות טאבים נכונים, freeze panes פעיל, צבעים אכן נכתבים,
    וחישוב האחוזים מדויק מתמטית.

### 5. תיקון קרדנציאלס TC8 vCenter

- שרת TC8 (`vcenter-tc.allegronet.co.il`) נכשל בכל בקשה עם `vim.fault.InvalidLogin` (שגיאת
  אימות אמיתית, לא בעיית רשת/קוד — TCP:443 נגיש, החשבון פשוט נדחה). אותר ע"י הוספת לוגינג
  קבוע ל-`_run()` בראוטר ה-vCenter ([app.py](backend/app.py) —
  `print(f"[vcenter:{env_key}] {type(e).__name__}: {e}")`, אותו דפוס שכבר קיים ל-endpoints
  של Infinidat) — קודם לכן שגיאות חיבור ל-vCenter הוחזרו כ-502 גנרי בלי שום פירוט בלוג.
- נוצר [`scripts/setup_vcenter_tc8_credentials.ps1`](scripts/setup_vcenter_tc8_credentials.ps1)
  לעדכון `VCENTER_TC8_USER`/`VCENTER_TC8_PASS` — **ללא self-elevation** (גרסה ראשונה שניסתה
  לפתוח חלון PowerShell מורם בעצמה נתקלה ב-`Read-Host` שמחזיר ריק מיד, כנראה עקב stdin שבור
  שעבר בירושה לחלון החדש; יש להריץ מחלון מורם שנפתח ידנית).
- לאחר עדכון הקרדנציאלס + restart לשירות — `/api/vcenter/tc8/summary` חוזר 200 OK.

---

## שינויים מרכזיים — גרסה 4.7.0 (ספטמבר 2026)

### 1. החזרת האימות + Microsoft Entra ID SSO

גרסה 4.4.3 הפכה את הדשבורד לגישה פתוחה. **4.7 מבטלת את זה** ומחזירה אכיפה מלאה.

**זרימת הכניסה:**
1. כל בקשה עוברת ב-`_AuthMiddleware` ([app.py:61](backend/app.py#L61)) — קורא JWT מעוגיית `auth_token`
   (ואם אין — מ-`Authorization: Bearer`).
2. בקשת `/api/*` ללא טוקן תקין → **401**. בקשת דף רגיל → **302 ל-`/login?next=...`**.
3. פתוחים ללא אימות: `/login`, `/static/*`, ו-`_API_OPEN` = login / logout / login-options /
   microsoft-start / microsoft-callback.

**שתי דרכי כניסה:**

| דרך | מי | איך |
|------|-----|-----|
| שם משתמש + סיסמה | **רק מ-IP מקומי** (`LOCAL_LOGIN_SOURCE_IPS`) | AD דרך LDAP bind → קבוצות `Tatayas Admins`/`Tatayas Users`; אם נכשל — משתמש local fallback (bcrypt, תמיד admin) |
| Entra ID SSO | כל השאר | OAuth2 Authorization Code מול `login.microsoftonline.com` |

`/api/auth/login-options` מחזיר לדף ההתחברות מה מותר לפונה — כך `login.html` מציג רק את
הכפתורים הרלוונטיים. ניסיון login עם סיסמה מ-IP לא-מקומי מוחזר ב-**403**.

**קונפיג ה-SSO נשמר ב-DB** (`auth_settings`), לא ב-`.env`, ונערך מהדפדפן ב-`/admin/overview#sso`:
`tenant_id`, `client_id`, `client_secret`, `redirect_uri`, `scope`, `ssl_mode`.
ה-secret מוחזר ממוסך (`********`); שמירה עם שדה ריק **משמרת** את הערך הקודם.

**הגנת CSRF ב-SSO:** `ms_state` (HttpOnly, 10 דק') מושווה ל-`state` שחוזר מ-Entra;
`ms_next` שומר את היעד המקורי. שתיהן נמחקות בסיום.

### 2. מודל הרשאות — allow-list

טבלת `authz_users`. **משתמש Entra שאינו ברשימה לא נכנס** — מוחזר ל-`/login?error=unauthorized_user`.

| מושג | משמעות |
|------|---------|
| `FORCED_ADMIN_IDENTITIES` | זהויות שתמיד מקבלות `admin`, גם ללא רשומה ב-allow-list |
| `PERMISSIONS_MANAGERS` | מי רשאי לערוך את ה-allow-list (`require_permissions_manager`) |
| `LOCAL_ONLY_USERS` | חשבונות שמותר להם להתחבר **רק** מהשרת עצמו |
| תפקידים | `admin` (עריכה) / `readonly` — כל ערך אחר מנורמל ל-`readonly` |

- נרמול זהות: lowercase + הסרת `DOMAIN\`; ההשוואה בודקת גם את החלק שלפני ה-`@`
- מחיקת ה-admin האחרון חסומה (**400**) — כדי לא לנעול את כולם בחוץ
- UI: `/admin/permissions` (דף `permissions.html`) — טבלה, הוספה, שינוי תפקיד, מחיקה, ספירות

### 3. עוזר AI (Ollama)

- `ollama_client.py` — לקוח לשרת Ollama פנימי (`10.114.36.10:11434`), ללא חשיפה לאינטרנט
- **עובד ב-streaming** מול Ollama למרות שהוא מחזיר מחרוזת אחת: הדגמים המקומיים (32B) מייצרים
  ~2 tok/s, ובקשה לא-streamed לא שולחת בייט עד סוף התשובה — מה שחרג מ-read timeout.
  streaming שומר על הזרימה. `num_predict=600` תוקע תקרה לאורך התשובה.
- אימות אופציונלי: `OLLAMA_USER` + `OLLAMA_PASS_ENC` (Fernet, אותו `DB_ENCRYPT_KEY` של ה-DB)
- `POST /api/ai/chat` בונה system prompt + עד 20 הודעות היסטוריה + **טקסט העמוד הנוכחי**
  (`aiGatherContext()` — עד 6000 תווים מ-`main`/`#content`/`.container`)
- כשל בשרת ה-AI מוחזר כ-**502** עם הודעה גנרית (הפרטים נכתבים ללוג בלבד)
- ה-widget נבנה ב-`sidebar.js` ומופיע רק למשתמש מזוהה

### 4. vCenter History — צילומי מצב והשוואת גרסאות

- `POST /api/vcenter/history/snapshot` (admin) — מושך במקביל (`ThreadPoolExecutor`) את מלאי
  ה-VMs מכל הסביבות ושומר גרסה. כל VM נשמר גם כ-`data_json` מלא.
- שמירת `VM_SNAPSHOT_RETENTION=50` גרסאות; ישנות יותר נמחקות אוטומטית (`prune_old_snapshots`)
- הדף `/vcenter/history` משווה **שתי נקודות זמן** — גרסה↔גרסה או גרסה↔מצב חי:
  - **נוספו** (עם תאריך יצירה מהאירועים), **הוסרו** (עם `VmRemovedEvent`), **שינוי משאבים**
  - דלתות CPU / RAM / דיסק, מקובצות **לפי לקוח**
  - `DISK_NOISE_THRESHOLD_GB` — thin provisioning זוחל בשברירי GB מעצמו; שינוי קטן מהסף
    לא נספר כשינוי אמיתי
  - רפליקות DR (`is_dr_replica`) מסוננות מההשוואה

### 5. vCenter VM Create — דוח תאריכי יצירה

- `/vcenter/vm-create` — **דוח, לא כלי הקמה.** מציג מתי כל VM נוצר, מקובץ לפי שנה
- מקור ראשי: `config.createDate` (קיים רק מ-vSphere 6.7U2 ומעלה)
- נפילה אחורה: אירוע היצירה המוקדם ביותר מ-`vcenter_events`; העמודה מסמנת מקור (`live`/`event`)
- יצוא Excel לכל שנה בנפרד או להכל

### 6. Event polling daemon

- thread רקע בשם `vc-events-poll` ([app.py:1136](backend/app.py#L1136)) עולה עם השירות
- משיכה ראשונית **30 יום** (720h) אחרי 10 שניות, ואז מחזור של **שעתיים** (25h חפיפה)
- `_events_poll_lock` מונע חפיפת ריצות; guard על שם ה-thread מונע כפילות ב-`uvicorn --reload`
- `GET /api/vcenter/events/poll?hours=` (admin) להפעלה ידנית

### 7. שינויים נוספים

- `auth.js` נכתב מחדש — מסנכרן session מול `/api/auth/session` בכל טעינת דף, מפיץ אירוע
  `cockpit-auth-updated`, ומפנה ל-`/login` כשה-session פג
- `upsert_vm_sap_batch()` — כל קריאת `summary` של vCenter מרעננת את `vm_sap_cache`
- Infinidat: `get_replicas_detailed()`, `get_performance()`, `get_hardware()` + endpoint
  `/replicas/detailed`
- vCenter: שדות `created_date` ו-`is_dr_replica` נוספו ל-`_props_to_vm()`
- `/management/customers` נוסף כ-alias ל-`/customers`

---

## שינויים מרכזיים — גרסה 4.6.0 (22/07/2026)

### מצב רשת + כרטיסי רשת — עמודות NIC בדפי vCenter

**Backend — `vcenter_client.py`:**
- `nic_total = len(nics)` — ספירת כל כרטיסי הרשת ב-VM
- `nic_connected = sum(1 for n in nics if getattr(n.connectable, "connected", False))` — ספירת NICs מחוברים כרגע
- שני שדות חדשים ב-`_props_to_vm()`: `nic_total`, `nic_connected`

**Frontend — 4 דפי vCenter (TC / TC8 / PT / Fattal):**
- **מצב רשת** — עמודה ב-columns picker; ברירת מחדל: גלויה; מציגה "מחובר" (ירוק) / "לא מחובר" (אפור)
- **כרטיסי רשת** — ספירת `nic_connected / nic_total`; ניתן למיין לפי `net_status` ו-`nic_count`
- יצוא Excel כולל עמודות: `מצב רשת` + `כרטיסי רשת (מחוברים/סה"כ)`
- תחילה נוספו כעמודות עצמאיות (`deploy_nic_status_feature.ps1`) → אחר כך הועברו לתוך picker (`deploy_nic_columns_toggle.ps1`)

### Overview — עמודות תפקיד ואיפיון בטאב "לפי לקוח"

- `vcenter_overview.html` — עמודת **תפקיד השרת** נוספה לטאב "לפי לקוח" (שורות הורה + שורות VM מפורטות) — `deploy_overview_role_column.ps1`
- עמודת **איפיון** כבר הייתה בטאב "כל המכונות"; כעת מוצגת גם בטאב "לפי לקוח"
- שני הערכים נשלפים מ-API: `role_note` מ-`/vm-notes`, `classification` מ-`/vm-classification`

### Classification Backend — פריסה מלאה (19/07/2026)

- `app.py` עודכן עם endpoints `/vm-classification` (GET + PUT) לכל 4 סביבות vCenter
- `VM_CLASSIFICATIONS` — רשימה ב-`app.py` (11 ערכים + `""` לניקוי)
- `database.py` — עמודה `classification TEXT DEFAULT ''` ב-`vm_notes` + `get_vm_classifications()` / `save_vm_classification()`
- Migration: `ALTER TABLE vm_notes ADD COLUMN classification` רץ אוטומטית ב-`init_db()`

### Veeam — דפים נוספים

- **TC Backup** (`/backup/tc`) — `backup_tc.html` — Veeam B&R TC-FARM (`al-veeamcc.allegronet.co.il:9419`)
- **Lifesaver Backup** (`/backup/lifesaver`) — `backup_lifesaver.html` — `al-lifesaver.allegronet.co.il:9419`
- שניהם OAuth2 Bearer, `x-api-version: 1.0-rev1` (זהה ל-PT/Fattal)
- `tc_backup_router` + `lifesaver_backup_router` ב-`app.py`

### Executive Summary (`/admin/overview`)

- `admin_overview.html` — דף סיכום להנהלה (Executive Summary)
- מציג KPI cards + מצב סביבות בפורמט תמציתי
- ניגש לאותם API endpoints כמו שאר הדפים

### כלי עזר — Firewall Rules Generator (22/07/2026)

- `scripts/gen_firewall_rules.py` — מייצר Excel מסודר של חוקי חומת אש לצורך מיגרציה
- שרת Dashboard IP חדש: `10.114.6.11/24`, שרתי AD חדשים: `10.114.32.1`, `10.114.32.2`
- כולל 3 קטגוריות: Outbound → Infrastructure, Outbound → AD, Inbound → Dashboard
- פלט: `UCS_Dashboard_Firewall_Rules.xlsx` (צבעוני, מעוצב, Freeze Panes)

---

## שינויים מרכזיים — גרסה 4.5.x (יולי 2026)

### Veeam Backup Integration
- **Veeam EM** (`veeam_client.py`): session auth על פורט 9398. Jobs נגזרים מ-BackupJobSessions כי `/api/jobs` מחזיר 403 ל-VeeamRO. response structure: `{"Entities": {"BackupJobSessions": {"BackupJobSessions": [...]}}}`
- **Veeam B&R** (`veeam_br_client.py`): OAuth2 Bearer על פורט 9419. Header: `x-api-version: 1.0-rev1` (ללא 'v'!). pagination: `pageSize=N`
- שני דפים חדשים: `/backup/pt` ו-`/backup/fattal`
- סיסמאות: `setup_veeam_pass.ps1` / `setup_fattal_pass.ps1` — Read-Host AsSecureString → plain text בקובץ נעול

### Light/Dark Mode
- כפתור ☽/☀ בסרגל העליון (header), `sbThemeToggle()` ב-`sidebar.js`
- CSS: `body.light-mode` עם `!important` על כל המשתנים ורכיבי ה-UI
- `write_sidebar.py` — Python script (חייב elevation) שכותב `sidebar.js` + CSS

### Sidebar — תיקון Encoding
- עברית "תא הטייס" עודכנה ל-JavaScript unicode escapes (`תא...`)
- סמלי ☽/☀ כ-`☽`/`☀` — לא יושחתו ע"י PowerShell encoding
- `write_sidebar.py` כותב ישירות ב-UTF-8 (עוקף את בעיית הencoding של PS 5.1)

### vCenter TC8
- דף חדש `vcenter_tc8.html` עבור TC-vCenter8

---

## ידוע ומוגבל

- **vCenter cache:** TTL=180s. אחרי restart — cache ריק, טעינה ראשונה איטית.
- **app.py נעול:** שינויים דורשים UAC elevation. Pattern: `Start-Process cmd -Verb RunAs -ArgumentList "/c py.exe script.py"`.
- **Veeam B&R Repos:** שמות שדות capacity/freeSpace משתנים לפי גרסת API — `_norm_repo()` מנסה מספר וריאנטים.
- **SRM REST API:** `ft-tc-srm.allegronet.co.il` — SRM ישן (SOAP-only, לפני 8.3). REST לא זמין.
- **sidebar.js encoding:** כל תיקון חייב להיעשות דרך `write_sidebar.py` (Python elevation) ולא דרך PowerShell here-string.
- **JWT_SECRET חובה (4.7):** `auth.py` זורק `RuntimeError` בעלייה אם המשתנה חסר — השירות כלל לא יעלה.
- **Ollama איטי (4.7):** דגם 32B מייצר ~2 tok/s; ה-read timeout הוגדר ל-240 שניות.
- **snapshot סינכרוני (4.7):** `POST /history/snapshot` מושך את כל הסביבות בבקשה אחת — לוקח זמן.

### ממצאים פתוחים מסקירת קוד (19/09/2026)

| # | קובץ | הממצא | סטטוס |
|---|------|--------|--------|
| 1 | [pt.html:78](frontend/pt.html#L78) | תג `<nav class="farm-nav">` הפותח נמחק — נשאר `</nav>` יתום; ניווט ה-farms שבור | ⬜ פתוח |
| 2 | [fattal.html:78](frontend/fattal.html#L78) | אותה רגרסיה | ⬜ פתוח |
| 3 | [style.css:476](frontend/style.css#L476) | סלקטור `body.sb-collapsed` ללא בלוק — מתמזג עם חוק ה-Light Mode ומבטל אותו **לגמרי** | ⬜ פתוח |
| 4 | [sidebar.js:90](frontend/sidebar.js#L90) | `nav`/`user`/`badge` נבנים פעם אחת בטעינת הסקריפט; `cockpit-auth-updated` מרנדר מחדש את אותן מחרוזות → משתמש SSO לא רואה תפריט Admin בטעינה ראשונה | ⬜ פתוח |
| 5 | [app.py:62-71](backend/app.py#L62) | `/health` ב-`_API_OPEN`, אבל הסט נבדק רק על נתיבי `/api/` → probe לא מאומת מקבל 302 | ✅ **תוקן 4.8** — הועבר ל-`_PAGE_OPEN` |
| 6 | [app.py:125-142](backend/app.py#L125) | `_CSRFMiddleware.dispatch` הוא pass-through ריק — ה-`csrf_token` שה-frontend שולח **לא נבדק** | ✅ **תוקן 4.8** — נבדק בפועל עם `secrets.compare_digest`; כל בקשות ה-POST/PUT/DELETE בפרונטאנד עודכנו לשלוח `X-CSRF-Token` |
| 7 | [app.py:474,566](backend/app.py#L474) | `next.startswith("/")` מקבל גם `//evil.com` → open redirect אחרי SSO | ✅ **תוקן 4.8** — `_safe_next_path()` דוחה `//` ו-`/\`; תוקן גם ב-`login.html` (לא היה שם אימות בכלל בצד הקליינט) |
| 8 | [infinidat_client.py:292](backend/infinidat_client.py#L292) | `job_dur_s` עושה `None - None` כשג'וב רפליקציה עדיין רץ → TypeError ו-502 | ⬜ פתוח |
| 9 | [infinidat_client.py:319](backend/infinidat_client.py#L319) | `sync_interval_ms == 0` נחשב סינכרוני → התרעות RPO שגויות על רפליקות async | ⬜ פתוח |
| 10 | [app.py:1038,1061](backend/app.py#L1038) | `summary`/`hosts` של vCenter מקבלים `?refresh=true` בלי `_check_admin_refresh` | ✅ **תוקן 4.8** — נוסף `_check_admin_refresh(refresh, request)`; **השפעה:** כפתור Refresh בדפי vCenter מחזיר 403 למשתמשי readonly, זהה להתנהגות הקיימת בדפי Veeam |
| 11 | [app.py:1197](backend/app.py#L1197) | היצוא קורא `event_label` ש-`insert_vcenter_events` לא שומר → Excel באנגלית מול UI בעברית | ⬜ פתוח |
| 12 | [index.html:61](frontend/index.html#L61) | `בקרוב` הוחלף בקודפוינטים לא מוקצים (Ethiopic) → מוצג כריבועים; גם ב-`pt.html` | ⬜ פתוח |

### ממצאי XSS נוספים — נמצאו ותוקנו ב-4.8 (סקירת אבטחה מלאה, 20/09/2026)

| קובץ | הממצא | סטטוס |
|------|--------|--------|
| [vcenter_overview.html](frontend/vcenter_overview.html#L574) | שם VM ושם לקוח נכנסים ל-`innerHTML` בלי `escapeHtml` (רגרסיה — דפי vCenter הבודדים כן מטהרים) | ✅ תוקן |
| [backup_lifesaver.html](frontend/backup_lifesaver.html#L181) | שם VM ונתיב backup בלי escaping (רגרסיה — 3 האחיות `backup_tc/pt/fattal.html` כן מטהרות) | ✅ תוקן |
| [vcenter_changes.html:485](frontend/vcenter_changes.html#L485) | שם VM לא מטוהר בתוך `title="..."` attribute (הטקסט הגלוי כן מטוהר) | ✅ תוקן |
| `_fmtNTP()` ב-4 דפי vCenter | שרתי NTP מוצגים בלי escaping | ✅ תוקן |

---

## שינויים מרכזיים — גרסה 4.4.1 (יוני 2026)

### עמודות אופציונליות בדפי vCenter
כפתור `📋 עמודות` נוסף לסרגל הכלים בכל 4 דפי רשימת VM (TC, TC8, PT, Fattal).

**Frontend (`vcenter_tc/tc8/pt/fattal.html`):**
- CSS: `.col-opt-hide { display:none !important }` — מסתיר עמודות בברירת מחדל
- Dropdown panel עם checkbox לכל עמודה; נסגר בלחיצה מחוץ לפאנל
- `_colVis` — אובייקט state; `initColVis()` IIFE טוען העדפות מ-`localStorage` בטעינת עמוד
- `setOptCol(key, on)` — מעדכן `classList.toggle('col-opt-hide')` ב-`<th>` ו-`<td>` ומרנדר מחדש
- `vmRow()` מוסיף 3 `<td>` אופציונליים בכל שורה; `_fmtTools()` מצבע VMtools סטטוס
- יצוא Excel כולל את 3 העמודות תמיד (גם כשמוסתרות בתצוגה)
- העדפות נשמרות ב-`localStorage('vc-col-TC/TC8/PT/Fattal')` — נפרד לכל סביבה

**Backend (`vcenter_client.py`):**
- נוספו לـ`pathSet`: `summary.guest.toolsVersionStatus2`, `config.version`
- `_props_to_vm` מחזיר: `vmtools_status` (מחרוזת כמו `toolsOk`/`toolsOld`/`toolsNotInstalled`), `hw_version` (`vmx-19` וכו')
- `hostname` (DNS Name) כבר היה קיים — ממשיך לעבוד

**עמודות:**
| עמודה | מקור | הערות |
|-------|------|--------|
| DNS Name | `summary.guest.hostName` | עובד — FQDN של VM |
| VMtools סטטוס | `summary.guest.toolsVersionStatus2` | עדכני/ישן/לא רץ/לא מותקן, בצבעים |
| HW Version | `config.version` | `vmx-19`, `vmx-20` וכו' |

---

## שינויים מרכזיים — גרסה 4.4 (יוני 2026)

### vCenter Cluster Detail Page (`vcenter_cluster_detail.html`)
דף פירוט קלסטר חדש עם שלושה גאג'ים (CPU, RAM, vCPU), ממצאים ומלצות, ו-hosts table:

**גאג'ים (SVG):**
- צורת חצי עיגול (180°), טבעת דקה SW=22, `stroke-linecap="round"` על arc הרקע (מונע groove)
- שלוש אזורי צבע: אדום/צהוב/ירוק עם מפרידים חשוכים (קווי "חיתוך")
- מחט מחושבת לפי factor + pivot + zone label
- vCPU gauge — factor הפוך: יחס גבוה = אדום; תוויות מסדר הפוך `['>8:1','4-8:1','2-4:1','<2:1']`

**ממצאים (`buildRecs()`):**
- N+X status, מגבלה (CPU/RAM), יחס vCPU, הקצאת RAM, המלצת שדרוג
- כל פריט כולל **טקסט הסבר** (`.cd-rec-explain`) לקוראים שאינם טכניים
- צבע-קידוד: אדום/צהוב/ירוק/כחול עם גבול ימני 4px

### תיקון יתירות N+X — אחידות בכל vCenters
`calcRedundancy()` עודכן בכל 4 דפי רשימת vCenter (`vcenter_tc.html`, `vcenter_tc8.html`, `vcenter_pt.html`, `vcenter_fattal.html`):
- **לפני:** בדיקה מפורשת N+1/N+2 עם ספי RAM/CPU נפרדים
- **אחרי:** `Math.floor(Math.min(freeCpu/refCpu, freeRam/refRam))` — זהה לנוסחת cluster-detail
- Badge בדף הרשימה תואם כעת לערך בדף הפירוט

### תיקון TC-vCenter8
- `VCENTER_TC8_HOST=vcenter-tc.allegronet.co.il` (10.10.15.70) — **שרת שונה** מ-`al-vcenter6` (10.10.15.100)
- ה-`.env` היה נכון; שירות רץ עם config ישן → Restart-Service UcsDashboard תיקן

### תיקון תוויות vCPU Gauge
- תוויות היו בסדר הפוך ביחס לאזורי הצבע → badge הראה "4-8:1" בעוד היחס היה 3.9:1
- תוקן ב-call: `makeGauge(vcpuGaugeFactor, 'vCPU', '', ['>8:1', '4-8:1', '2-4:1', '<2:1'])`

---

## שינויים מרכזיים — גרסה 4.4.2 (יולי 2026)

### Security Hardening — Round 1 + Round 2

**Round 1 (מיושם לפני סקירת Round 2):**
- `_AuthMiddleware`: קורא `auth_token` cookie (HttpOnly) לפני Bearer header
- Login מגדיר `auth_token` (HttpOnly, Secure, SameSite=Lax)
- `_SecurityHeadersMiddleware`: CSP, X-Frame-Options, X-Content-Type-Options
- `_DEVICE_COLS`: רשימת עמודות מפורשת ב-SQL — לא מחזיר `password`
- `POST /api/auth/logout` מוחק את ה-cookie
- Rate limiting: `_LOGIN_ATTEMPTS` — 10 ניסיונות ב-60 שניות לכל IP
- `require_admin` על endpoint `/api/events`
- Excel upload: 5MB limit, `.xlsx`/`.xls` בלבד, `read_only=True`
- `_safe()`: formula injection protection בexport Excel של vCenter events
- Error messages: `detail=str(e)` הוחלף ב-generic messages ב-backup endpoints

**Round 2 Phase 1:**
- `_CSRFMiddleware`: `X-CSRF-Token` header חובה ב-POST/PUT/DELETE (חוץ מlogin)
- Login: מחזיר `{username, role, expires_at}` בלבד — ללא `access_token`
- `csrf_token` cookie (non-HttpOnly) לJavaScript
- `_get_client_ip()`: XFF מאומת רק מ-`TRUSTED_PROXIES` env var
- `_check_admin_refresh()`: HTTP 403 לmon-admin שמבקש `?refresh=true` ב-8 endpoints

**Round 2 Phase 2:**
- SheetJS vendored locally: `frontend/xlsx.full.min.js` (930 KB)
- 12 קבצי HTML עודכנו מ-CDN URL ל-`/static/xlsx.full.min.js`
- ניקוי: כל `.patched`/`.reverted`/`.clean` הוסרו מ-`frontend/`
- `.gitignore` עודכן עם `*.patched`, `*.bak`, `*_done.txt`, `*_out.txt`

**Round 2 Phase 3 — XSS:**
- `escapeHtml()` על כל שדות API ב-innerHTML ב-9 קבצי HTML:
  - `vcenter_tc8/pt/tc/fattal.html`: vmRow, hostRow, bad-host rows, error handlers
  - `backup.html`: renderJobs, renderRepos, renderServers
  - `backup_pt/tc/fattal/lifesaver.html`: renderJobs, renderRepos, renderSessions, filterVMs

**Round 2 Phase 4a — TLS:**
- `_TLS_VERIFY` constant מ-`INFRA_CA_BUNDLE` env var בכל 5 infra clients
- `vcenter_client.py`, `veeam_client.py`, `veeam_br_client.py`: כתיבה ישירה (לא נעולים)
- `infinidat_client.py`, `ucs_client.py`: `.patched` + elevated Copy-Item

**Round 2 Phase 4b — הצפנת סיסמאות:**
- `_pw_fernet()` / `_encrypt_pw()` / `_decrypt_pw()` הוספו ל-`database.py`
- Fernet (AES-128-CBC + HMAC-SHA256), מפתח = SHA-256(`DB_ENCRYPT_KEY`) → base64
- `create_device()` ו-`update_device()` מצפינים password לפני שמירה
- backward-compatible: plaintext אם `DB_ENCRYPT_KEY` לא מוגדר

**ממתין — CSP:**
- `unsafe-inline` נשאר ב-CSP — דורש refactor מלא של ה-frontend

---

## שינויים מרכזיים — גרסה 4.4.4 (יולי 2026)

### vCenter Change Tracking — תיקון TC + הוספת TC8

**תיקון TC vCenter (קריטי):**
- הדשבורד היה מושך events מ-`vcenter-tc.allegronet.co.il` (TC8) — vCenter שלמשתמש `VSPHERE.TC\CockpitDash` אין הרשאות לראות VM events
- ה-TC האמיתי הוא `al-vcenter6.allegronet.co.il` עם `cockpitdash@VSphere.local`
- `app.py` עודכן: `_VC_ENVS_FOR_EVENTS` עבר מ-`VCENTER_TC8_*` ל-`VCENTER_TC_*`
- תוצאה: TC עלה מ-0 events חדשים ל-**27 אירועים** ב-30 יום האחרונים (כולל `TEMP-ERANV-01`, `ICH-TEMP--02`, `lab-fs-01` ועוד)
- TC8 (`vcenter-tc.allegronet.co.il`) נוסף כ-environment **נפרד** — ימולא כאשר permissions יתוקנו ב-vSphere

**הוספת TC8 כ-environment נוסף:**
- `app.py`: הוסף `("TC8", lambda: (VCENTER_TC8_HOST, VCENTER_TC8_USER, VCENTER_TC8_PASS))` ל-`_VC_ENVS_FOR_EVENTS`
- `vcenter_changes.html`: קטע TC8 חדש (badge כחול-בהיר `#79c0ff`)
- כל ה-JS מעודכן: `_data`, `_collapsed`, `filterAll`, `populateDropdowns`, לולאות render

**שיפורי UX — Change Tracking:**
- **מיון לפי אירוע**: עמודת "אירוע" הפכה sortable (הייתה static)
- **פילטר אירוע**: dropdown `🎯 אירוע` נוסף לשורת הפילטרים — מאוכלס אוטומטית מהנתונים
- כל 4 הפילטרים פועלים ביחד: חיפוש + חברה + משתמש + אירוע + Administrator toggle + מיון

**אבחון TC vCenter:**
- `QueryEvents` על TC8 החזיר 1000 אירועים בלבד — כולם Login/Logout sessions (899) + EventEx (92)
- סיבה: `CockpitDash@VSPHERE.TC` אינו ב-Global Permissions של TC8; `VSPHERE.LOCAL\CockpitDash` כן קיים אך בוויסנטר אחר
- פתרון ארוך-טווח: להוסיף `VSPHERE.TC\CockpitDash` ב-Global Permissions → Read-only + Propagate to children ב-`vcenter-tc.allegronet.co.il`

---

## שינויים מרכזיים — גרסה 4.4.3 (יולי 2026)

### הסרת אימות משתמשים — גישה פתוחה
- **`auth.js`** הוחלף לחלוטין — מגדיר `cockpit_auth_role=admin` ב-localStorage ללא login
- **`app.py`** — `_AuthMiddleware` ו-`_CSRFMiddleware` הפכו ל-passthrough (middleware קיים אך לא אוכף)
- **`auth.py`** — `require_admin()` מחזיר `""` (pass-through) במקום לאמת JWT
- הדשבורד נגיש ישירות ללא שם משתמש / סיסמא

### vCenter Change Tracking — שיפורי UX
**סינון אוטומטי VSPHERE.LOCAL\Administrator:**
- ברירת מחדל: שורות עם `user_name == VSPHERE.LOCAL\Administrator` (case-insensitive) מוסתרות
- כפתור toggle בשורת הכלים — `👁 הצג Administrator` / `🔒 רק משתמשים אמיתיים`
- כשמסתיר — counter מציג `(X מסונן / Y | +Z מערכת)`

**מיון לפי עמודות:**
- כותרות VM, לקוח, אירוע, משתמש, תאריך — ניתנות ללחיצה
- ⇅ ניטרלי / ▲ עולה / ▼ יורד — ברירת מחדל: תאריך יורד (חדש ביותר למעלה)
- לחיצה כפולה על אותה עמודה — הפיכת כיוון

**פילטרים dropdown:**
- שורה שנייה מתחת ל-ctrl-bar עם שני `<select>`:
  - 🏢 **חברה** — מאוכלס אוטומטית מהנתונים הטעונים (sorted לפי שם עברי)
  - 👤 **משתמש** — כל המשתמשים הייחודיים בתוצאות
- כפתור **✕ נקה פילטרים** מופיע רק כשיש פילטר פעיל
- כל הפילטרים פועלים ביחד: חיפוש חופשי + חברה + משתמש + סינון Administrator + מיון

---

## שינויים מרכזיים — גרסה 4.5.0 (17/07/2026)

### עמודות רשת חדשות בדפי vCenter (TC / TC8 / PT / Fattal)

**Backend — `vcenter_client.py`:**
- נוספה `_fetch_dvportgroup_map(content)` — שולף כל ה-DVPortgroups בבנייה `portgroup_key → {name, vlan_id}`
- נוספה `_parse_vlan(vlan)` — ממיר `VlanIdSpec` (מספר שלם) ו-`TrunkVlanSpec` (מחרוזת `trunk:100-200`)
- נוספה `_extract_vm_port_groups(nics, dvpg_map)` — עובר על NICs ומחלץ portgroup + VLAN (standard vSwitch ו-DVS)
- כל VM מחזיר שדות חדשים: `port_groups: [str]` ו-`vlan_ids: [int|str|None]`
- `config` נוסף ל-pathSet של DVPortgroup query

**Frontend — כפתור 📋 עמודות (3 עמודות חדשות, מוסתרות בברירת מחדל):**

| עמודה | מקור | הערות |
|--------|------|--------|
| **Port Group** | `vm.port_groups` (API) | שם ה-portgroup לפי NIC; רשתים מרובות מופרדות \` \| \` |
| **VLAN** | `vm.vlan_ids` (API) | מספר VLAN (כחול); `trunk:100-200` ל-trunk; `—` ל-std vSwitch |
| **סוג רשת** | `vm.vlan_ids` (מיפוי JS) | VLAN→שם רשת בכתום (צהוב): 3=DMZ Bezeqint, 9=לקוחות, 11=פנימית, 13=DMZ, 15=ניהול, 34=גיבוי |

- פונקציות JS חדשות: `_fmtVlan()`, `_VLAN_NET_NAMES`, `_fmtNetworkType()`
- כל שינויים ב-`vcenter_tc.html`, `vcenter_tc8.html`, `vcenter_pt.html`, `vcenter_fattal.html`

### עמודת דומיין — מיון + סינון

**חישוב הדומיין:**
- `_getDomain(hostname)`: חתיכת כל מה שאחרי הנקודה הראשונה; שרת ללא `.` או DNS ריק נתחם כ-`WorkGroup`
- `_fmtDomain(hostname)` עודכן לשתמש ב-`_getDomain`

**מיון:**
- עמודת דומיין הפכה sortable: `data-col="domain"` + `onclick="sortBy('domain')"`
- נוסף `case 'domain'` ל-`vmSortVal()`

**סינון:**
- Dropdown **דומיין:** ב-toolbar (מחרי DR filter), מתמלא אוטומטית אחרי טעינת הנתונים
- `populateDomains(vms)` — נקראת אחרי `populateClusters()`
- שדה החיפוש הכללי (🔍) שולף כעת גם על שם דומיין
- `_getDomain()` נוספ ל-`getFilteredVMs()`

### עמודת איפיון ב-Overview

- `vcenter_overview.html` שולף כעת `/vm-classification` לכל סביבה (TC/PT/Fattal) בנוסף ל-notes
- עמודת **איפיון** נוספה לטאב "כל המכונות" (אחרי תפקיד השרת)
- הערך מגיע מה-dropdown בדפי vCenter הבודדים
- נוסף גם ל-`vmExcelRow()` ביצוא Excel

### עדכון רשימת איפיון (`VM_CLASSIFICATIONS`)

רשימה מלאה נכונה (`backend/app.py` + 4 דפי frontend):

```
שרת אלגרונט בלבד
שרת בשימוש אלגרונט + לקוחות
שרת לקוחות תחת דומיין אלגרונט
שרת אלגרונט אבטחת מידע
שרת אלגרונט ניטור
שרת אלגרונט גיבוי
שרת לוגים
שרת דומיין פרטי
מרכזיה                          ← חדש
שרת לניהול סטוראג אלגרונט  ← חדש
שרת VMware אלגרונט           ← חדש
```

---

## Next Steps (פתוח)

### עדיפות ראשונה — רגרסיות פעילות בפרודקשן
- [ ] **תיקון `<nav>` שבור** ב-`pt.html` + `fattal.html` (ממצאים 1-2)
- [ ] **תיקון ה-CSS שהורג את ה-Light Mode** — `style.css:476` (ממצא 3)
- [ ] **תיקון תפריט ה-Admin למשתמשי SSO** — `sidebar.js` בונה את ה-nav לפני שה-session מגיע (ממצא 4)
- [ ] **`infinidat_client.py` — TypeError על ג'וב רפליקציה רץ** + **סיווג RPO שגוי ל-`sync_interval_ms=0`** (ממצאים 8-9)
- [ ] **`event_label` חסר ביצוא Excel** של Change Tracking (ממצא 11)
- [ ] **קודפוינטים לא מוקצים** ב-`index.html`/`pt.html` ("בקרוב" מוצג כריבועים, ממצא 12)
- [x] ~~אכיפת CSRF בפועל~~ — **תוקן 4.8**
- [x] ~~Open redirect אחרי SSO login~~ — **תוקן 4.8**
- [x] ~~`/health` מחזיר 302 במקום 200~~ — **תוקן 4.8**
- [x] ~~`?refresh=true` בדפי vCenter בלי admin-gate~~ — **תוקן 4.8**

### שוטף
- [ ] **בדיקת תצוגת ESXi מול vCenter אמיתי** — עמודה/כרטיס, ספי העומס, ופורמט ה-host ב-`runtime.host` (גרסה 4.11)
- [ ] **בדיקת סימון גיבויים מול VM עם גיבוי רגיל** — לוודא טווחי זמן (task sessions) ואת סיווג הרפליקציה לפי שם job (גרסה 4.11)
- [ ] **ניקוי הריפו** — קבצי `.clean*` / `.fixed` / `.patched` / `.bak` ב-`backend/` ו-`frontend/`
- [ ] **Port Group VLAN ל-standard vSwitch** — עדיין `vlan_id=None` ל-std vSwitch portgroups (אין מידע ב-API ללא query נוסף ל-HostVirtualSwitch)
- [ ] **סינון סוג רשת** — הוספת dropdown סינון לפי סוג רשת (כמו domain filter)
- [ ] **סינון דומיין ב-Overview** — הוספת עמודת דומיין בדף Overview ואפשרות סינון
- [ ] **SRM REST API** — שדרוג SRM לגרסה 8.3+ לנתוני protection groups
- [ ] **DR Drill-down לקוח** — פירוט VM-רמה עם RPO היסטורי
- [ ] **Auto-refresh** עם countdown בדפי vCenter ו-Infinidat
- [ ] **Alerts badge** בסיידבר לאירועי ERROR/WARNING
- [ ] **Veeam PT/Fattal Sessions** — לבדוק param name נכון ב-API אם מציג 0
- [ ] **VMtools גרסה** — `summary.guest.toolsVersion` עדיין ריק; לשקול אם שווה להוסיף
- [ ] **CSP unsafe-inline** — הוצאת כל `<script>` inline לקבצי JS חיצוניים + `addEventListener` במקום `onclick`
- [ ] **TC8 Global Permissions** — להוסיף `VSPHERE.TC\CockpitDash` ב-Global Permissions → Read-only + Propagate ב-`vcenter-tc.allegronet.co.il` (כדי לקבל VM events)
- [ ] **מיגרציה לשרת חדש** — `10.114.6.11/24`; כללי חומת אש נוצרו ב-`UCS_Dashboard_Firewall_Rules.xlsx`
