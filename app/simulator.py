import logging
import math
import random
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

log = logging.getLogger(__name__)


class Simulator:
    def __init__(self, zbx, db, settings, scenarios, analysts):
        self.zbx = zbx
        self.db = db
        self.settings = settings
        self.scenarios = scenarios
        self.analysts = analysts
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.running = False

    def start_scheduler(self):
        if not self.scheduler.running:
            self.scheduler.start()
        self.restore_active_jobs()
        if self.settings.auto_start:
            self.start()

    def start(self):
        self.running = True
        if not self.scheduler.get_job("next_generation"):
            self._schedule_next_generation(initial=True)
        return self.status()

    def stop(self):
        self.running = False
        job = self.scheduler.get_job("next_generation")
        if job:
            job.remove()
        return self.status()

    def status(self):
        return {
            "running": self.running,
            "events_per_hour": self.settings.events_per_hour,
            "active_incidents": self.db.active_count(),
            "max_active_incidents": self.settings.max_active,
            "assets": len(self.db.list_assets()),
        }

    def _next_delay_seconds(self):
        # Poisson-like arrivals: varied intervals while preserving the configured mean.
        rate = max(self.settings.events_per_hour, 0.1)
        mean = 3600.0 / rate
        delay = random.expovariate(1.0 / mean)
        return int(max(20, min(delay, mean * 4)))

    def _schedule_next_generation(self, initial=False):
        if not self.running:
            return
        delay = random.randint(2, 10) if initial else self._next_delay_seconds()
        run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        self.scheduler.add_job(
            self._generation_job,
            trigger=DateTrigger(run_date=run_at),
            id="next_generation",
            replace_existing=True,
            max_instances=1,
        )

    def _generation_job(self):
        try:
            if self.running:
                self.generate_incident()
        except Exception:
            log.exception("Falha ao gerar incidente automático")
        finally:
            self._schedule_next_generation()

    def _choose_target(self, requested_host=None, requested_scenario=None):
        assets = self.db.list_assets()
        if requested_host:
            assets = [a for a in assets if a["host"] == requested_host]
        if self.settings.one_active_per_host:
            active_hosts = self.db.active_hosts()
            assets = [a for a in assets if a["host"] not in active_hosts]
        random.shuffle(assets)

        candidates = []
        for asset in assets:
            valid = [
                sid for sid, s in self.scenarios.items()
                if asset["device_type"] in s["allowed_types"]
                and (requested_scenario is None or sid == requested_scenario)
            ]
            for sid in valid:
                candidates.append((asset, sid))
        if not candidates:
            raise RuntimeError("Nenhum host/cenário elegível disponível")
        return random.choice(candidates)

    @staticmethod
    def _rand_value(low, high):
        if float(low).is_integer() and float(high).is_integer():
            return random.randint(int(low), int(high))
        return round(random.uniform(float(low), float(high)), 2)

    def generate_incident(self, host=None, scenario_id=None):
        if self.db.active_count() >= self.settings.max_active:
            raise RuntimeError("Limite de incidentes ativos atingido")

        asset, sid = self._choose_target(host, scenario_id)
        scenario = self.scenarios[sid]
        binding = self.db.get_binding(asset["host"], sid)
        if not binding:
            raise RuntimeError(f"Binding ausente para {asset['host']} / {sid}")

        now = datetime.now(timezone.utc)
        ack_minutes = random.randint(self.settings.ack_min, self.settings.ack_max)
        resolution_minutes = random.randint(self.settings.resolution_min, self.settings.resolution_max)
        if resolution_minutes <= ack_minutes:
            resolution_minutes = ack_minutes + 5

        ack_due = now + timedelta(minutes=ack_minutes)
        resolve_due = now + timedelta(minutes=resolution_minutes)
        available_between = max(2, resolution_minutes - ack_minutes)
        treatment_offset = max(1, int(available_between * random.uniform(0.25, 0.65)))
        treatment_due = ack_due + timedelta(minutes=treatment_offset)
        if treatment_due >= resolve_due:
            treatment_due = resolve_due - timedelta(minutes=1)

        problem_value = self._rand_value(scenario["problem_min"], scenario["problem_max"])
        recovery_value = self._rand_value(scenario["recovery_min"], scenario["recovery_max"])
        analyst = random.choice(self.analysts)

        incident_id = self.db.insert_incident(
            {
                "host": asset["host"],
                "client": asset["client"],
                "device_type": asset["device_type"],
                "scenario_id": sid,
                "scenario_name": scenario["name"],
                "eventid": None,
                "triggerid": binding["triggerid"],
                "item_key": binding["item_key"],
                "analyst": analyst["name"],
                "state": "opening",
                "problem_value": problem_value,
                "recovery_value": recovery_value,
                "opened_at": now.isoformat(),
                "ack_due_at": ack_due.isoformat(),
                "treatment_due_at": treatment_due.isoformat(),
                "resolve_due_at": resolve_due.isoformat(),
            }
        )

        try:
            self.zbx.push_value(asset["host"], binding["item_key"], problem_value)
            eventid = self.zbx.find_problem_event(binding["triggerid"])
            if not eventid:
                raise RuntimeError("Trigger não gerou evento PROBLEM dentro do tempo esperado")
            self.db.update_incident(incident_id, eventid=eventid, state="problem")

            self._schedule_lifecycle(incident_id, ack_due, treatment_due, resolve_due)
            log.info(
                "Incidente #%s aberto: %s / %s eventid=%s ACK=%smin RES=%smin",
                incident_id, asset["host"], sid, eventid, ack_minutes, resolution_minutes,
            )
            return self.db.get_incident(incident_id)
        except Exception as exc:
            self.db.update_incident(incident_id, state="failed", last_error=str(exc))
            raise

    def _schedule_lifecycle(self, incident_id, ack_due, treatment_due, resolve_due):
        self.scheduler.add_job(
            self.ack_incident, DateTrigger(run_date=ack_due), args=[incident_id],
            id=f"ack-{incident_id}", replace_existing=True, misfire_grace_time=3600,
        )
        self.scheduler.add_job(
            self.treat_incident, DateTrigger(run_date=treatment_due), args=[incident_id],
            id=f"treat-{incident_id}", replace_existing=True, misfire_grace_time=3600,
        )
        self.scheduler.add_job(
            self.resolve_incident, DateTrigger(run_date=resolve_due), args=[incident_id],
            id=f"resolve-{incident_id}", replace_existing=True, misfire_grace_time=7200,
        )

    def ack_incident(self, incident_id):
        inc = self.db.get_incident(incident_id)
        if not inc or inc["state"] in {"resolved", "failed"}:
            return
        s = self.scenarios[inc["scenario_id"]]
        message = f"[{inc['analyst']}] {random.choice(s['ack_messages'])}"
        try:
            self.zbx.acknowledge(inc["eventid"], message)
            self.db.update_incident(incident_id, state="acknowledged", ack_at=datetime.now(timezone.utc).isoformat())
            log.info("Incidente #%s reconhecido", incident_id)
        except Exception as exc:
            self.db.update_incident(incident_id, last_error=str(exc))
            log.exception("Falha no ACK do incidente #%s", incident_id)

    def treat_incident(self, incident_id):
        inc = self.db.get_incident(incident_id)
        if not inc or inc["state"] in {"resolved", "failed"}:
            return
        s = self.scenarios[inc["scenario_id"]]
        message = f"[{inc['analyst']}] TRATATIVA: {random.choice(s['treatment_messages'])}"
        try:
            self.zbx.add_event_message(inc["eventid"], message)
            self.db.update_incident(incident_id, state="in_treatment", treatment_at=datetime.now(timezone.utc).isoformat())
            log.info("Incidente #%s recebeu tratativa", incident_id)
        except Exception as exc:
            self.db.update_incident(incident_id, last_error=str(exc))
            log.exception("Falha na tratativa do incidente #%s", incident_id)

    def resolve_incident(self, incident_id):
        inc = self.db.get_incident(incident_id)
        if not inc or inc["state"] in {"resolved", "failed"}:
            return
        s = self.scenarios[inc["scenario_id"]]
        message = f"[{inc['analyst']}] SOLUÇÃO: {random.choice(s['solution_messages'])}"
        try:
            self.zbx.add_event_message(inc["eventid"], message)
            self.zbx.push_value(inc["host"], inc["item_key"], inc["recovery_value"])
            self.db.update_incident(incident_id, state="resolved", resolved_at=datetime.now(timezone.utc).isoformat())
            log.info("Incidente #%s resolvido", incident_id)
        except Exception as exc:
            self.db.update_incident(incident_id, last_error=str(exc))
            log.exception("Falha na resolução do incidente #%s", incident_id)

    def restore_active_jobs(self):
        now = datetime.now(timezone.utc)
        for inc in self.db.list_incidents(active_only=True, limit=5000):
            if not inc.get("eventid"):
                continue
            ack_due = datetime.fromisoformat(inc["ack_due_at"])
            treatment_due = datetime.fromisoformat(inc["treatment_due_at"])
            resolve_due = datetime.fromisoformat(inc["resolve_due_at"])
            self._schedule_lifecycle(
                inc["id"],
                max(ack_due, now + timedelta(seconds=2)),
                max(treatment_due, now + timedelta(seconds=4)),
                max(resolve_due, now + timedelta(seconds=6)),
            )
