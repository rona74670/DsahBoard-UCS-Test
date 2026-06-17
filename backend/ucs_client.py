"""
Cisco UCS Manager XML API Client
Connects to UCSM via the /nuova endpoint using XML API.
"""

import re
import requests
import xml.etree.ElementTree as ET
import urllib3
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class UCSMClient:
    def __init__(self, host: str, username: str, password: str):
        self.host = host
        self.username = username
        self.password = password
        self.base_url = f"https://{host}/nuova"
        self.cookie: Optional[str] = None
        self.session = requests.Session()
        self.session.verify = False  # Self-signed cert on lab/UCS gear

    def _post(self, xml_body: str) -> ET.Element:
        response = self.session.post(
            self.base_url,
            data=xml_body,
            headers={"Content-Type": "application/xml"},
            timeout=15,
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        error_code = root.attrib.get("errorCode")
        if error_code and error_code != "0":
            raise RuntimeError(
                f"UCSM API Error {error_code}: {root.attrib.get('errorDescr', 'Unknown error')}"
            )
        return root

    def login(self) -> dict:
        xml = f'<aaaLogin inName="{self.username}" inPassword="{self.password}"/>'
        root = self._post(xml)
        self.cookie = root.attrib.get("outCookie")
        if not self.cookie:
            raise RuntimeError("Login failed: no cookie returned")
        return {
            "cookie": self.cookie,
            "refresh_period": root.attrib.get("outRefreshPeriod"),
            "privilege": root.attrib.get("outPriv"),
            "domains": root.attrib.get("outDomains"),
        }

    def logout(self):
        if self.cookie:
            xml = f'<aaaLogout inCookie="{self.cookie}"/>'
            try:
                self._post(xml)
            except Exception:
                pass
            self.cookie = None

    def _require_login(self):
        if not self.cookie:
            raise RuntimeError("Not logged in. Call login() first.")

    def _resolve_class(self, class_id: str, in_filter: str = "") -> list[dict]:
        """Generic method to query any UCSM managed object class."""
        self._require_login()
        filter_block = f"<inFilter>{in_filter}</inFilter>" if in_filter else "<inFilter/>"
        xml = (
            f'<configResolveClass cookie="{self.cookie}" classId="{class_id}" inHierarchical="false">'
            f"{filter_block}"
            f"</configResolveClass>"
        )
        root = self._post(xml)
        objects = []
        out_configs = root.find("outConfigs")
        if out_configs is not None:
            for child in out_configs:
                objects.append(child.attrib)
        return objects

    # ------------------------------------------------------------------ #
    #  High-level resource queries                                         #
    # ------------------------------------------------------------------ #

    def get_system_info(self) -> dict:
        """Return top-level UCS domain info."""
        self._require_login()
        xml = f'<configResolveClass cookie="{self.cookie}" classId="topSystem" inHierarchical="false"><inFilter/></configResolveClass>'
        root = self._post(xml)
        out_configs = root.find("outConfigs")
        if out_configs is not None and len(out_configs):
            return out_configs[0].attrib
        return {}

    def get_fabric_interconnects(self) -> list[dict]:
        return self._resolve_class("networkElement")

    def get_chassis(self) -> list[dict]:
        return self._resolve_class("equipmentChassis")

    def get_blade_servers(self) -> list[dict]:
        return self._resolve_class("computeBlade")

    def get_rack_servers(self) -> list[dict]:
        return self._resolve_class("computeRackUnit")

    def get_service_profiles(self) -> list[dict]:
        return self._resolve_class("lsServer")

    def get_faults(self, min_severity: str = "warning") -> list[dict]:
        """
        Fetch active faults. min_severity can be: critical, major, minor, warning, info.
        """
        severity_map = {"critical": 0, "major": 1, "minor": 2, "warning": 3, "info": 4}
        all_faults = self._resolve_class("faultInst")
        cutoff = severity_map.get(min_severity, 3)
        return [
            f for f in all_faults
            if severity_map.get(f.get("severity", "info"), 99) <= cutoff
        ]

    def get_vhbas(self) -> list[dict]:
        return self._resolve_class("vnicFc")

    def get_vnics(self) -> list[dict]:
        return self._resolve_class("vnicEther")

    # ------------------------------------------------------------------ #
    #  Detailed hardware queries (for enriched blade view)                 #
    # ------------------------------------------------------------------ #

    def get_processors(self) -> list[dict]:
        return self._resolve_class("processorUnit")

    def get_memory_units(self) -> list[dict]:
        return self._resolve_class("memoryUnit")

    def get_local_disks(self) -> list[dict]:
        return self._resolve_class("storageLocalDisk")

    def get_flex_flash_cards(self) -> list[dict]:
        """FlexFlash SD cards installed in blades."""
        return self._resolve_class("storageFlexFlashCard")

    def get_virtual_drives(self) -> list[dict]:
        """RAID virtual drives from hardware RAID controllers."""
        return self._resolve_class("storageVirtualDrive")

    def get_blades_enriched(self) -> list[dict]:
        """Return blade list enriched with CPU, memory, storage, and RAID details."""
        import re

        def _safe_int(v):
            try: return int(v)
            except (ValueError, TypeError): return 0

        def blade_dn_from(dn: str):
            m = re.match(r'(sys/chassis-\d+/blade-\d+)', dn)
            return m.group(1) if m else None

        blades = self.get_blade_servers()

        buckets: dict[str, dict] = {
            b['dn']: {**b, '_cpus': [], '_mems': [], '_disks': [], '_sds': [], '_vds': []}
            for b in blades
        }

        for obj in self.get_processors():
            bdn = blade_dn_from(obj.get('dn', ''))
            if bdn and bdn in buckets:
                buckets[bdn]['_cpus'].append(obj)

        for obj in self.get_memory_units():
            bdn = blade_dn_from(obj.get('dn', ''))
            if bdn and bdn in buckets:
                buckets[bdn]['_mems'].append(obj)

        for obj in self.get_local_disks():
            bdn = blade_dn_from(obj.get('dn', ''))
            if bdn and bdn in buckets:
                buckets[bdn]['_disks'].append(obj)

        for obj in self.get_flex_flash_cards():
            bdn = blade_dn_from(obj.get('dn', ''))
            if bdn and bdn in buckets:
                buckets[bdn]['_sds'].append(obj)

        for obj in self.get_virtual_drives():
            bdn = blade_dn_from(obj.get('dn', ''))
            if bdn and bdn in buckets:
                buckets[bdn]['_vds'].append(obj)

        result = []
        for bdn, data in buckets.items():

            # --- CPU ---
            cpus = [c for c in data['_cpus'] if c.get('operability', '') != 'removed']
            if cpus:
                model = cpus[0].get('model', '').strip()
                try:
                    ghz = float(cpus[0].get('speed', 0)) / 1000
                    if ghz > 0 and 'ghz' not in model.lower() and '@' not in model:
                        model += f" @ {ghz:.2f} GHz"
                except (ValueError, TypeError):
                    pass
                cores = cpus[0].get('cores', '')
                if cores:
                    model += f" ({cores}C)"
                cpu_summary = model or '–'
            else:
                cpu_summary = '–'

            # --- Memory ---
            mems = [m for m in data['_mems']
                    if m.get('operability') == 'operable' and _safe_int(m.get('capacity', 0)) > 0]
            total_mb = _safe_int(data.get('totalMemory', 0))
            total_gb = total_mb // 1024
            if mems:
                try:
                    clock = _safe_int(mems[0].get('clock', 0))
                    ddr = 'DDR4' if clock >= 2133 else 'DDR3' if clock >= 1066 else 'DRAM'
                    mem_summary = f"{total_gb} GB | {ddr} @ {clock} MHz"
                except (ValueError, TypeError):
                    mem_summary = f"{total_gb} GB"
            else:
                mem_summary = f"{total_gb} GB" if total_gb else '–'

            # --- Storage ---
            disks = [d for d in data['_disks']
                     if d.get('diskState', 'good') not in ('removed', 'absent', '')]
            sds = data['_sds']
            storage_parts = []
            if disks:
                storage_parts.append(f"{len(disks)}x HDD/SSD")
            if sds:
                storage_parts.append(f"{len(sds)}x SD")
            storage_summary = ' + '.join(storage_parts) if storage_parts else 'None'

            # --- RAID ---
            vds = data['_vds']
            if vds:
                levels = sorted({vd.get('raidLevel', '?') for vd in vds})
                raid_summary = 'RAID ' + ' / '.join(levels)
            elif disks:
                raid_summary = 'No RAID / JBOD'
            else:
                raid_summary = '–'

            rec = {k: v for k, v in data.items() if not k.startswith('_')}
            rec['cpu_summary'] = cpu_summary
            rec['mem_summary'] = mem_summary
            rec['storage_summary'] = storage_summary
            rec['raid_summary'] = raid_summary
            result.append(rec)

        def sort_key(x):
            sid = x.get('serverId', '0/0')
            parts = sid.split('/')
            try:
                return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except ValueError:
                return (0, 0)

        result.sort(key=sort_key)
        return result

    def get_psus(self) -> list[dict]:
        return self._resolve_class("equipmentPsu")

    def get_fan_modules(self) -> list[dict]:
        return self._resolve_class("equipmentFanModule")

    def get_mgmt_controllers(self) -> list[dict]:
        return self._resolve_class("mgmtController")

    def get_hardware_summary(self) -> dict:
        """Return detailed CPU, memory, PSU, fan, and blade IP data for summary tables."""

        def _safe_int(v):
            try: return int(v)
            except (ValueError, TypeError): return 0

        def _bdn(dn: str):
            m = re.match(r'(sys/chassis-\d+/blade-\d+)', dn)
            return m.group(1) if m else None

        def _chassis(dn: str):
            m = re.match(r'sys/chassis-(\d+)', dn)
            if m: return m.group(1)
            m2 = re.match(r'sys/(switch-\w+|fex-\d+)', dn)
            return m2.group(1) if m2 else None

        def _sp_short(dn: str):
            if not dn: return ''
            m = re.search(r'ls-(.+)$', dn)
            return m.group(1) if m else dn.split('/')[-1]

        # ── Fetch all data in one session ──────────────────────────────
        blades   = self.get_blade_servers()
        cpus_raw = self.get_processors()
        mems_raw = self.get_memory_units()
        psus_raw = self.get_psus()
        fans_raw = self.get_fan_modules()
        mgmt_raw = self.get_mgmt_controllers()

        # blade DN → metadata
        blade_lut: dict[str, dict] = {}
        for b in blades:
            m = re.match(r'sys/chassis-(\d+)/blade-(\d+)', b.get('dn', ''))
            if m:
                blade_lut[b['dn']] = {
                    'chassis':  m.group(1),
                    'blade':    m.group(2),
                    'model':    b.get('model', ''),
                    'sp':       _sp_short(b.get('assignedToDn', '')),
                }

        # ── CPUs ───────────────────────────────────────────────────────
        cpus = []
        for c in cpus_raw:
            if c.get('operability') == 'removed':
                continue
            info = blade_lut.get(_bdn(c.get('dn', '')) or '', {})
            spd  = _safe_int(c.get('speed', 0))
            # speed=0 on some firmware — try to extract from model string
            if not spd:
                sm = re.search(r'@\s*([\d.]+)\s*GHz', c.get('model', ''), re.I)
                if sm:
                    try: spd = int(float(sm.group(1)) * 1000)
                    except (ValueError, TypeError): pass
            cpus.append({
                'chassis':     info.get('chassis', '?'),
                'blade':       info.get('blade', '?'),
                'blade_model': info.get('model', ''),
                'socket':      c.get('id', ''),
                'cpu_model':   c.get('model', '').strip(),
                'cores':       c.get('cores', ''),
                'threads':     c.get('threads', ''),
                'speed_ghz':   f"{spd/1000:.2f}" if spd else '',
                'status':      c.get('operability', ''),
            })
        cpus.sort(key=lambda x: (_safe_int(x['chassis']), _safe_int(x['blade']), _safe_int(x['socket'])))

        # ── Memory ────────────────────────────────────────────────────
        memory_units = []
        for mem in mems_raw:
            cap = _safe_int(mem.get('capacity', 0))
            if cap <= 0:
                continue
            info  = blade_lut.get(_bdn(mem.get('dn', '')) or '', {})
            clock = _safe_int(mem.get('clock', 0))
            cap_gb = cap // 1024
            ddr = 'DDR4' if clock >= 2133 else 'DDR3' if clock >= 1066 else 'DRAM'
            loc = mem.get('location', '') or mem.get('id', '')
            memory_units.append({
                'chassis':    info.get('chassis', '?'),
                'blade':      info.get('blade', '?'),
                'blade_model': info.get('model', ''),
                'slot':       loc,
                'capacity_gb': cap_gb,
                'type':       ddr,
                'clock_mhz':  clock,
                'mem_model':  mem.get('model', '').strip(),
                'status':     mem.get('operability', ''),
            })
        memory_units.sort(key=lambda x: (_safe_int(x['chassis']), _safe_int(x['blade']), str(x['slot'])))

        # ── PSUs ──────────────────────────────────────────────────────
        psus = []
        for p in psus_raw:
            dn  = p.get('dn', '')
            ch  = _chassis(dn) or '?'
            pm  = re.search(r'/psu-(\d+)', dn)
            pwr = ''
            for f in ('outputPower', 'power', 'inputPower'):
                try:
                    v = float(p.get(f, 0) or 0)
                    if v > 0:
                        pwr = f"{v:.0f} W"; break
                except (ValueError, TypeError):
                    pass
            psus.append({
                'chassis':  ch,
                'psu_id':   pm.group(1) if pm else p.get('id', ''),
                'model':    p.get('model', '').strip(),
                'status':   p.get('operState', ''),
                'power':    pwr,
                'voltage':  p.get('voltage', ''),
                'serial':   p.get('serial', ''),
            })
        psus.sort(key=lambda x: (_safe_int(x['chassis']), _safe_int(x['psu_id'])))

        # ── Fan modules ───────────────────────────────────────────────
        fans = []
        for f in fans_raw:
            dn = f.get('dn', '')
            fans.append({
                'chassis': _chassis(dn) or '?',
                'module':  f.get('id', ''),
                'model':   f.get('model', '').strip(),
                'status':  f.get('operState', ''),
            })
        fans.sort(key=lambda x: (_safe_int(x['chassis']), str(x['module'])))

        # ── Blade management IPs ──────────────────────────────────────
        blade_mgmt = []
        for mg in mgmt_raw:
            bdn = _bdn(mg.get('dn', ''))
            if not bdn:
                continue
            info = blade_lut.get(bdn, {})
            if not info:
                continue
            blade_mgmt.append({
                'chassis':         info.get('chassis', '?'),
                'blade':           info.get('blade', '?'),
                'blade_model':     info.get('model', ''),
                'mgmt_ip':         mg.get('oobIfIp', ''),
                'service_profile': info.get('sp', ''),
            })
        blade_mgmt.sort(key=lambda x: (_safe_int(x['chassis']), _safe_int(x['blade'])))

        return {
            'cpus':         cpus,
            'memory_units': memory_units,
            'psus':         psus,
            'fans':         fans,
            'blade_mgmt':   blade_mgmt,
        }

    # ------------------------------------------------------------------ #
    #  Firmware, Power, Network, Pools                                    #
    # ------------------------------------------------------------------ #

    def get_firmware_running(self) -> list[dict]:
        return self._resolve_class("firmwareRunning")

    def get_adapters(self) -> list[dict]:
        return self._resolve_class("adaptorUnit")

    def get_chassis_stats(self) -> list[dict]:
        return self._resolve_class("equipmentChassisStats")

    def get_firmware_summary(self) -> list[dict]:
        """Per-blade BIOS, CIMC and adapter firmware versions."""
        blades = self.get_blade_servers()
        fw_all = self.get_firmware_running()

        blade_lut: dict[str, dict] = {}
        for b in blades:
            m = re.match(r'sys/chassis-(\d+)/blade-(\d+)', b.get('dn', ''))
            if m:
                blade_lut[b['dn']] = {
                    'chassis':   m.group(1),
                    'blade':     m.group(2),
                    'server_id': b.get('serverId', ''),
                    'model':     b.get('model', ''),
                    'bios':      '',
                    'cimc':      '',
                    'adapter':   '',
                }

        for fw in fw_all:
            dn  = fw.get('dn', '')
            bm  = re.match(r'(sys/chassis-\d+/blade-\d+)/', dn)
            if not bm:
                continue
            bdn = bm.group(1)
            if bdn not in blade_lut:
                continue
            ver = fw.get('version', '') or fw.get('deployedVersion', '')
            if not ver:
                continue
            if re.search(r'/bios/fw-boot-loader$', dn):
                blade_lut[bdn]['bios'] = ver
            elif re.search(r'^sys/chassis-\d+/blade-\d+/mgmt/fw-system$', dn):
                blade_lut[bdn]['cimc'] = ver
            elif re.search(r'/adaptor-\d+/mgmt/fw-system$', dn) and not blade_lut[bdn]['adapter']:
                blade_lut[bdn]['adapter'] = ver

        result = list(blade_lut.values())

        def _si(v):
            try: return int(v)
            except: return 0

        result.sort(key=lambda x: (_si(x['chassis']), _si(x['blade'])))
        return result

    def get_power_stats(self) -> list[dict]:
        """Input/output power (W) and temperature (°C) per chassis."""
        chassis_raw = self.get_chassis()
        stats_raw   = self.get_chassis_stats()

        ch_model: dict[str, str] = {}
        for ch in chassis_raw:
            m = re.search(r'chassis-(\d+)', ch.get('dn', ''))
            if m:
                ch_model[m.group(1)] = ch.get('model', '').strip()

        def _f(v):
            try:
                f = float(v or 0)
                return f if f != 0 else None
            except (ValueError, TypeError):
                return None

        result = []
        for s in stats_raw:
            m = re.search(r'chassis-(\d+)', s.get('dn', ''))
            if not m:
                continue
            ch   = m.group(1)
            inp  = _f(s.get('inputPower'))
            outp = _f(s.get('outputPower'))
            amb  = _f(s.get('ambientTemp'))
            frt  = _f(s.get('frontTemp'))
            rr   = _f(s.get('rearTemp'))
            result.append({
                'chassis':   ch,
                'model':     ch_model.get(ch, ''),
                'input_w':   f"{inp:.0f} W"  if inp  is not None else '-',
                'output_w':  f"{outp:.0f} W" if outp is not None else '-',
                'ambient_c': f"{amb:.1f}C"   if amb  is not None else '-',
                'front_c':   f"{frt:.1f}C"   if frt  is not None else '-',
                'rear_c':    f"{rr:.1f}C"    if rr   is not None else '-',
            })
        result.sort(key=lambda x: int(x['chassis']) if x['chassis'].isdigit() else 0)
        return result

    def get_network_summary(self) -> dict:
        """Physical adapters (VIC), vNIC Ethernet (MAC), vHBA FC (WWPN) per blade."""
        blades     = self.get_blade_servers()
        adapters_r = self.get_adapters()
        vnics_r    = self._resolve_class("adaptorHostEthIf")
        vhbas_r    = self._resolve_class("adaptorHostFcIf")

        blade_lut: dict[str, dict] = {}
        for b in blades:
            m = re.match(r'sys/chassis-(\d+)/blade-(\d+)', b.get('dn', ''))
            if m:
                blade_lut[b['dn']] = {
                    'chassis':   m.group(1),
                    'blade':     m.group(2),
                    'model':     b.get('model', ''),
                    'server_id': b.get('serverId', ''),
                }

        def bdn(dn: str):
            m = re.match(r'(sys/chassis-\d+/blade-\d+)', dn)
            return m.group(1) if m else None

        def si(v):
            try: return int(v)
            except: return 0

        adapters = []
        for a in adapters_r:
            bd   = bdn(a.get('dn', ''))
            info = blade_lut.get(bd, {}) if bd else {}
            if not info:
                continue
            am = re.search(r'adaptor-(\d+)', a.get('dn', ''))
            adapters.append({
                'chassis':     info['chassis'],
                'blade':       info['blade'],
                'server_id':   info['server_id'],
                'blade_model': info['model'],
                'adapter':     am.group(1) if am else a.get('id', ''),
                'model':       a.get('model', '').strip(),
                'serial':      a.get('serial', ''),
                'pci_slot':    a.get('pciSlot', '') or a.get('id', ''),
            })
        adapters.sort(key=lambda x: (si(x['chassis']), si(x['blade'])))

        vnics = []
        for v in vnics_r:
            bd   = bdn(v.get('dn', ''))
            info = blade_lut.get(bd, {}) if bd else {}
            if not info:
                continue
            am = re.search(r'adaptor-(\d+)', v.get('dn', ''))
            vnics.append({
                'chassis':     info['chassis'],
                'blade':       info['blade'],
                'server_id':   info['server_id'],
                'blade_model': info['model'],
                'adapter':     am.group(1) if am else '',
                'interface':   v.get('name', '') or v.get('id', ''),
                'mac':         v.get('mac', ''),
                'mtu':         v.get('mtu', ''),
            })
        vnics.sort(key=lambda x: (si(x['chassis']), si(x['blade']), str(x['interface'])))

        vhbas = []
        for v in vhbas_r:
            bd   = bdn(v.get('dn', ''))
            info = blade_lut.get(bd, {}) if bd else {}
            if not info:
                continue
            am = re.search(r'adaptor-(\d+)', v.get('dn', ''))
            vhbas.append({
                'chassis':     info['chassis'],
                'blade':       info['blade'],
                'server_id':   info['server_id'],
                'blade_model': info['model'],
                'adapter':     am.group(1) if am else '',
                'interface':   v.get('name', '') or v.get('id', ''),
                'wwpn':        v.get('wwpn', ''),
                'node_wwn':    v.get('nodeWwn', '') or v.get('nodewwn', ''),
            })
        vhbas.sort(key=lambda x: (si(x['chassis']), si(x['blade']), str(x['interface'])))

        return {'adapters': adapters, 'vnics': vnics, 'vhbas': vhbas}

    def get_pool_data(self) -> list[dict]:
        """UUID, IP, MAC and WWPN pool availability."""
        pools = []
        for class_id, pool_type in [
            ('uuidpoolPool', 'UUID'), ('ippoolPool', 'IP'),
            ('macpoolPool',  'MAC'),  ('wwpnpoolPool', 'WWPN'),
        ]:
            try:
                for p in self._resolve_class(class_id):
                    name = p.get('name', '')
                    if not name:
                        continue
                    try:
                        size     = int(p.get('size', 0) or 0)
                        assigned = int(p.get('assigned', 0) or 0)
                    except (ValueError, TypeError):
                        size, assigned = 0, 0
                    pools.append({
                        'type':      pool_type,
                        'name':      name,
                        'size':      size,
                        'assigned':  assigned,
                        'available': size - assigned,
                        'pct_used':  f"{assigned/size*100:.0f}%" if size > 0 else '–',
                    })
            except Exception:
                pass
        return sorted(pools, key=lambda x: (x['type'], x['name']))

    def get_summary(self) -> dict:
        """Return a combined summary of the UCS domain."""
        info = self.get_system_info()
        fi_list = self.get_fabric_interconnects()
        chassis_list = self.get_chassis()
        blades = self.get_blade_servers()
        racks = self.get_rack_servers()
        sps = self.get_service_profiles()
        faults = self.get_faults(min_severity="warning")

        fault_counts = {"critical": 0, "major": 0, "minor": 0, "warning": 0}
        for f in faults:
            sev = f.get("severity", "")
            if sev in fault_counts:
                fault_counts[sev] += 1

        return {
            "system": info,
            "fabric_interconnects": fi_list,
            "chassis": chassis_list,
            "blade_servers": blades,
            "rack_servers": racks,
            "service_profiles": sps,
            "faults": faults,
            "fault_summary": fault_counts,
            "counts": {
                "fabric_interconnects": len(fi_list),
                "chassis": len(chassis_list),
                "blade_servers": len(blades),
                "rack_servers": len(racks),
                "service_profiles": len(sps),
                "total_servers": len(blades) + len(racks),
            },
        }
