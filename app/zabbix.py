import itertools
import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)


class ZabbixAPIError(RuntimeError):
    pass


class ZabbixClient:
    def __init__(self, url: str, token: str, verify_ssl: bool = False, timeout: int = 20):
        self.url = url
        self.token = token
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._ids = itertools.count(1)
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json-rpc"})
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    def call(self, method: str, params: Any = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": {} if params is None else params,
            "id": next(self._ids),
        }
        try:
            response = self.session.post(
                self.url,
                json=payload,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise ZabbixAPIError(f"Falha HTTP/JSON chamando {method}: {exc}") from exc

        if "error" in data:
            err = data["error"]
            raise ZabbixAPIError(
                f"Zabbix API {method}: {err.get('message')} - {err.get('data')}"
            )
        return data.get("result")

    def version(self) -> str:
        return self.call("apiinfo.version")

    def push_value(self, host: str, key: str, value: float | int) -> dict:
        return self.call("history.push", [{"host": host, "key": key, "value": value}])

    def find_problem_event(self, triggerid: str, retries: int = 10, delay: float = 1.0) -> str | None:
        for _ in range(retries):
            events = self.call(
                "event.get",
                {
                    "output": ["eventid", "clock", "name", "acknowledged", "value"],
                    "source": 0,
                    "object": 0,
                    "objectids": [triggerid],
                    "value": 1,
                    "sortfield": ["eventid"],
                    "sortorder": "DESC",
                    "limit": 1,
                },
            )
            if events:
                return events[0]["eventid"]
            time.sleep(delay)
        return None

    def acknowledge(self, eventid: str, message: str) -> dict:
        # 2 = acknowledge, 4 = add message. 6 = both.
        return self.call(
            "event.acknowledge",
            {"eventids": [eventid], "action": 6, "message": message},
        )

    def add_event_message(self, eventid: str, message: str) -> dict:
        return self.call(
            "event.acknowledge",
            {"eventids": [eventid], "action": 4, "message": message},
        )
