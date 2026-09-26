import logging
from collections import defaultdict

log = logging.getLogger(__name__)


DEVICE_PATTERN = [
    ("SRV", "server", 5),
    ("DB", "database", 1),
    ("SW", "switch", 2),
    ("FW", "firewall", 1),
    ("WEB", "web", 1),
]


def chunks(seq, size=100):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class Bootstrapper:
    def __init__(self, zbx, db, settings, scenarios):
        self.zbx = zbx
        self.db = db
        self.settings = settings
        self.scenarios = scenarios

    def expected_hosts(self):
        result = []
        for client_no in range(1, self.settings.client_count + 1):
            client = f"CLIENTE-{client_no:02d}"
            ordinal = defaultdict(int)
            created = 0
            for prefix, device_type, count in DEVICE_PATTERN:
                for _ in range(count):
                    if created >= self.settings.hosts_per_client:
                        break
                    ordinal[prefix] += 1
                    host = f"{client}-{prefix}-{ordinal[prefix]:03d}"
                    result.append((host, client, device_type))
                    created += 1
            while created < self.settings.hosts_per_client:
                ordinal["SRV"] += 1
                host = f"{client}-SRV-{ordinal['SRV']:03d}"
                result.append((host, client, "server"))
                created += 1
        return result

    def ensure_group(self):
        groups = self.zbx.call("hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": [self.settings.host_group]}})
        if groups:
            return groups[0]["groupid"]
        result = self.zbx.call("hostgroup.create", {"name": self.settings.host_group})
        return result["groupids"][0]

    def run(self):
        version = self.zbx.version()
        log.info("Conectado ao Zabbix %s", version)
        groupid = self.ensure_group()
        expected = self.expected_hosts()

        existing = self.zbx.call(
            "host.get",
            {"output": ["hostid", "host"], "groupids": [groupid], "selectTags": ["tag", "value"]},
        )
        by_name = {h["host"]: h for h in existing}

        missing_payload = []
        missing_meta = []
        for host, client, device_type in expected:
            if host not in by_name:
                missing_payload.append(
                    {
                        "host": host,
                        "groups": [{"groupid": groupid}],
                        "tags": [
                            {"tag": "simulator", "value": "true"},
                            {"tag": "client", "value": client},
                            {"tag": "device_type", "value": device_type},
                        ],
                    }
                )
                missing_meta.append((host, client, device_type))

        for payload_chunk in chunks(missing_payload, 100):
            self.zbx.call("host.create", payload_chunk)
        if missing_payload:
            log.info("Criados %d hosts", len(missing_payload))

        hosts = self.zbx.call(
            "host.get",
            {"output": ["hostid", "host"], "groupids": [groupid], "selectTags": ["tag", "value"]},
        )
        by_name = {h["host"]: h for h in hosts}
        expected_meta = {h: (c, t) for h, c, t in expected}
        selected_hosts = []
        for host, (client, device_type) in expected_meta.items():
            obj = by_name[host]
            self.db.upsert_asset(host, obj["hostid"], client, device_type)
            selected_hosts.append({"host": host, "hostid": obj["hostid"], "client": client, "device_type": device_type})

        hostids = [h["hostid"] for h in selected_hosts]
        current_items = self.zbx.call(
            "item.get",
            {"output": ["itemid", "hostid", "key_", "name"], "hostids": hostids, "search": {"key_": "sim."}},
        )
        items_index = {(i["hostid"], i["key_"]): i for i in current_items}

        item_payloads = []
        item_refs = []
        for h in selected_hosts:
            for sid, s in self.scenarios.items():
                if h["device_type"] not in s["allowed_types"]:
                    continue
                if (h["hostid"], s["key"]) not in items_index:
                    item_payloads.append(
                        {
                            "name": f"SIM | {s['name']}",
                            "key_": s["key"],
                            "hostid": h["hostid"],
                            "type": 2,
                            "value_type": 0,
                            "units": s.get("units", ""),
                            "delay": "0",
                            "trapper_hosts": self.settings.trapper_allowed_hosts,
                            "tags": [{"tag": "simulator", "value": "true"}, {"tag": "scenario", "value": sid}],
                        }
                    )
                    item_refs.append((h["hostid"], s["key"]))

        for payload_chunk in chunks(item_payloads, 100):
            self.zbx.call("item.create", payload_chunk)
        if item_payloads:
            log.info("Criados %d itens trapper", len(item_payloads))

        current_items = self.zbx.call(
            "item.get",
            {"output": ["itemid", "hostid", "key_", "name"], "hostids": hostids, "search": {"key_": "sim."}},
        )
        items_index = {(i["hostid"], i["key_"]): i for i in current_items}

        current_triggers = self.zbx.call(
            "trigger.get",
            {"output": ["triggerid", "description", "expression"], "hostids": hostids, "search": {"description": "SIM |"}},
        )
        trigger_by_desc = {t["description"]: t for t in current_triggers}

        trigger_payloads = []
        expected_trigger_desc = {}
        for h in selected_hosts:
            for sid, s in self.scenarios.items():
                if h["device_type"] not in s["allowed_types"]:
                    continue
                desc = f"SIM | {h['host']} | {sid} | {s['name']}"
                expected_trigger_desc[(h["host"], sid)] = desc
                if desc in trigger_by_desc:
                    continue
                expression = f"last(/{h['host']}/{s['key']}){s['operator']}{s['threshold']}"
                trigger_payloads.append(
                    {
                        "description": desc,
                        "expression": expression,
                        "priority": int(s["severity"]),
                        "manual_close": 1,
                        "tags": [
                            {"tag": "simulator", "value": "true"},
                            {"tag": "scenario", "value": sid},
                            {"tag": "client", "value": h["client"]},
                        ],
                    }
                )

        for payload_chunk in chunks(trigger_payloads, 100):
            self.zbx.call("trigger.create", payload_chunk)
        if trigger_payloads:
            log.info("Criados %d triggers", len(trigger_payloads))

        current_triggers = self.zbx.call(
            "trigger.get",
            {"output": ["triggerid", "description", "expression"], "hostids": hostids, "search": {"description": "SIM |"}},
        )
        trigger_by_desc = {t["description"]: t for t in current_triggers}

        for h in selected_hosts:
            for sid, s in self.scenarios.items():
                if h["device_type"] not in s["allowed_types"]:
                    continue
                item = items_index[(h["hostid"], s["key"])]
                trig = trigger_by_desc[expected_trigger_desc[(h["host"], sid)]]
                self.db.upsert_binding(h["host"], sid, item["itemid"], trig["triggerid"], s["key"])

        log.info("Bootstrap concluído: %d hosts preparados", len(selected_hosts))
        return {"zabbix_version": version, "hosts": len(selected_hosts), "groupid": groupid}
