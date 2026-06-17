"""
FastAPI backend for UCS Manager Dashboard  v3.0
Multi-farm: TC-FARM · PT-FARM · FATTAL
Database: SQLite (dashboard.db)
"""

import os
import shutil
from typing import Optional
from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from ucs_client import UCSMClient
from database import (
    init_db, migrate_json_if_needed,
    load_manual, save_manual,
    list_devices, get_device, create_device, update_device, delete_device,
)

load_dotenv()

app = FastAPI(title="UCS Dashboard API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BACKEND_DIR  = os.path.dirname(__file__)
FRONTEND_DIR = os.path.normpath(os.path.join(BACKEND_DIR, "..", "frontend"))

# Init DB + migrate any existing JSON files
init_db()


# ------------------------------------------------------------------ #
#  Pydantic models                                                     #
# ------------------------------------------------------------------ #

class ManualEntry(BaseModel):
    server_key: str
    assignment: str = ""
    cabinet:    str = ""
    vcenter:    str = ""
    notes:      str = ""


class DeviceIn(BaseModel):
    farm:     str = "ALL"
    name:     str
    type:     str = "Generic"
    host:     str = ""
    username: str = ""
    password: str = ""
    port:     int = 443
    protocol: str = "https"
    notes:    str = ""
    enabled:  bool = True


# ------------------------------------------------------------------ #
#  Farm router factory                                                 #
# ------------------------------------------------------------------ #

def build_farm_router(prefix: str, host: str, user: str, pwd: str, farm_id: str) -> APIRouter:
    """Return a complete set of UCSM API routes for one farm."""
    router = APIRouter(prefix=prefix)

    def _client():
        return UCSMClient(host=host, username=user, password=pwd)

    def _run(func):
        client = _client()
        try:
            client.login()
            return func(client)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
        finally:
            client.logout()

    @router.get("/ping")
    def ping():
        client = _client()
        try:
            info = client.login()
            client.logout()
            return {"status": "ok", "host": host, "user": user, "session": info}
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Connection failed: {e}")

    @router.get("/summary")
    def get_summary():
        return _run(lambda c: c.get_summary())

    @router.get("/system")
    def get_system():
        return _run(lambda c: c.get_system_info())

    @router.get("/fabric-interconnects")
    def get_fis():
        return _run(lambda c: c.get_fabric_interconnects())

    @router.get("/chassis")
    def get_chassis():
        return _run(lambda c: c.get_chassis())

    @router.get("/blades")
    def get_blades():
        return _run(lambda c: c.get_blade_servers())

    @router.get("/racks")
    def get_racks():
        return _run(lambda c: c.get_rack_servers())

    @router.get("/service-profiles")
    def get_sps():
        return _run(lambda c: c.get_service_profiles())

    @router.get("/faults")
    def get_faults(min_severity: str = "warning"):
        return _run(lambda c: c.get_faults(min_severity=min_severity))

    @router.get("/blades/enriched")
    def get_blades_enriched():
        return _run(lambda c: c.get_blades_enriched())

    @router.get("/hardware-summary")
    def get_hardware_summary():
        return _run(lambda c: c.get_hardware_summary())

    @router.get("/firmware")
    def get_firmware():
        return _run(lambda c: c.get_firmware_summary())

    @router.get("/power-stats")
    def get_power_stats():
        return _run(lambda c: c.get_power_stats())

    @router.get("/network-adapters")
    def get_network_adapters():
        return _run(lambda c: c.get_network_summary())

    @router.get("/pools")
    def get_pools():
        return _run(lambda c: c.get_pool_data())

    @router.get("/manual-data")
    def get_manual_data():
        return load_manual(farm_id)

    @router.put("/manual-data")
    def update_manual_data(entry: ManualEntry):
        save_manual(
            farm_id, entry.server_key,
            assignment=entry.assignment,
            cabinet=entry.cabinet,
            vcenter=entry.vcenter,
            notes=entry.notes,
        )
        return {"status": "saved", "key": entry.server_key}

    return router


# ------------------------------------------------------------------ #
#  Register farms                                                      #
# ------------------------------------------------------------------ #

TC_HOST   = os.getenv("TC_HOST",     "10.10.140.100")
TC_USER   = os.getenv("TC_USER",     os.getenv("UCS_USER", ""))
TC_PASS   = os.getenv("TC_PASS",     os.getenv("UCS_PASS", ""))

PT_HOST   = os.getenv("PT_HOST",     "10.20.140.100")
PT_USER   = os.getenv("PT_USER",     os.getenv("UCS_USER", ""))
PT_PASS   = os.getenv("PT_PASS",     os.getenv("UCS_PASS", ""))

FATTAL_HOST   = os.getenv("FATTAL_HOST", "10.8.0.160")
FATTAL_USER   = os.getenv("FATTAL_USER", os.getenv("UCS_USER", ""))
FATTAL_PASS   = os.getenv("FATTAL_PASS", os.getenv("UCS_PASS", ""))

# Migrate any surviving JSON files → SQLite
migrate_json_if_needed("tc",     os.path.join(BACKEND_DIR, "manual_data_tc.json"))
migrate_json_if_needed("pt",     os.path.join(BACKEND_DIR, "manual_data_pt.json"))
migrate_json_if_needed("fattal", os.path.join(BACKEND_DIR, "manual_data_fattal.json"))
# legacy
_old = os.path.join(BACKEND_DIR, "manual_data.json")
if os.path.exists(_old):
    migrate_json_if_needed("tc", _old)

app.include_router(build_farm_router("/api/tc",     TC_HOST,     TC_USER,     TC_PASS,     "tc"))
app.include_router(build_farm_router("/api/pt",     PT_HOST,     PT_USER,     PT_PASS,     "pt"))
app.include_router(build_farm_router("/api/fattal", FATTAL_HOST, FATTAL_USER, FATTAL_PASS, "fattal"))


# ------------------------------------------------------------------ #
#  Device registry (global — not per-farm)                             #
# ------------------------------------------------------------------ #

@app.get("/api/devices")
def api_list_devices(farm: Optional[str] = None):
    return list_devices(farm)

@app.post("/api/devices", status_code=201)
def api_create_device(d: DeviceIn):
    return create_device(
        farm=d.farm, name=d.name, dtype=d.type,
        host=d.host, username=d.username, password=d.password,
        port=d.port, protocol=d.protocol,
        notes=d.notes, enabled=d.enabled,
    )

@app.put("/api/devices/{device_id}")
def api_update_device(device_id: int, d: DeviceIn):
    result = update_device(
        device_id,
        farm=d.farm, name=d.name, type=d.type,
        host=d.host, username=d.username, password=d.password,
        port=d.port, protocol=d.protocol,
        notes=d.notes, enabled=1 if d.enabled else 0,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Device not found")
    return result

@app.delete("/api/devices/{device_id}")
def api_delete_device(device_id: int):
    if not delete_device(device_id):
        raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "deleted", "id": device_id}


# ------------------------------------------------------------------ #
#  Serve frontend static files                                         #
# ------------------------------------------------------------------ #

if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def serve_tc():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/pt")
    def serve_pt():
        return FileResponse(os.path.join(FRONTEND_DIR, "pt.html"))

    @app.get("/fattal")
    def serve_fattal():
        return FileResponse(os.path.join(FRONTEND_DIR, "fattal.html"))

    @app.get("/compare")
    def serve_compare():
        return FileResponse(os.path.join(FRONTEND_DIR, "compare.html"))

    @app.get("/devices")
    def serve_devices():
        return FileResponse(os.path.join(FRONTEND_DIR, "devices.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=9000, reload=True)
