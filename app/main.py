import logging
import os

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from app.bootstrap import Bootstrapper
from app.config import Settings
from app.db import Database
from app.simulator import Simulator
from app.zabbix import ZabbixClient

load_dotenv()
settings = Settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger(__name__)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
scenarios = load_yaml(os.path.join(BASE, "config", "scenarios.yaml"))["scenarios"]
analysts = load_yaml(os.path.join(BASE, "config", "analysts.yaml"))["analysts"]

db = Database(settings.sqlite_path)
zbx = ZabbixClient(settings.zabbix_url, settings.zabbix_api_token, settings.zabbix_verify_ssl)
bootstrapper = Bootstrapper(zbx, db, settings, scenarios)
simulator = Simulator(zbx, db, settings, scenarios, analysts)

app = Flask(__name__)


def require_key():
    if settings.api_key and request.headers.get("X-API-Key") != settings.api_key:
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.get("/health")
def health():
    try:
        version = zbx.version()
        return jsonify({"status": "ok", "zabbix": version})
    except Exception as exc:
        return jsonify({"status": "degraded", "error": str(exc)}), 503


@app.get("/status")
def status():
    return jsonify(simulator.status())


@app.post("/bootstrap")
def bootstrap():
    auth = require_key()
    if auth:
        return auth
    try:
        result = bootstrapper.run()
        return jsonify({"ok": True, **result})
    except Exception as exc:
        log.exception("Bootstrap falhou")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/simulation/start")
def simulation_start():
    auth = require_key()
    if auth:
        return auth
    return jsonify(simulator.start())


@app.post("/simulation/stop")
def simulation_stop():
    auth = require_key()
    if auth:
        return auth
    return jsonify(simulator.stop())


@app.post("/incident/generate")
def incident_generate():
    auth = require_key()
    if auth:
        return auth
    body = request.get_json(silent=True) or {}
    try:
        inc = simulator.generate_incident(body.get("host"), body.get("scenario"))
        return jsonify(inc), 201
    except Exception as exc:
        log.exception("Geração manual falhou")
        return jsonify({"error": str(exc)}), 400


@app.get("/incidents")
def incidents():
    active = request.args.get("active", "false").lower() in {"1", "true", "yes"}
    limit = min(int(request.args.get("limit", "100")), 1000)
    return jsonify(db.list_incidents(active_only=active, limit=limit))


@app.get("/scenarios")
def list_scenarios():
    return jsonify(scenarios)


def startup():
    if not settings.zabbix_api_token:
        log.warning("ZABBIX_API_TOKEN não configurado; aguardando configuração antes do bootstrap.")
        simulator.start_scheduler()
        return
    try:
        bootstrapper.run()
    except Exception:
        log.exception("Bootstrap automático falhou. A API continuará disponível para nova tentativa via /bootstrap.")
    simulator.start_scheduler()


startup()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.http_port, threaded=True)
