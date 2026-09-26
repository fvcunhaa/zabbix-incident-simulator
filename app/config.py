import os
from dotenv import load_dotenv

load_dotenv()


def as_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    zabbix_url = os.getenv("ZABBIX_URL", "http://zabbix-web/zabbix/api_jsonrpc.php")
    zabbix_api_token = os.getenv("ZABBIX_API_TOKEN", "")
    zabbix_verify_ssl = as_bool("ZABBIX_VERIFY_SSL", False)
    trapper_allowed_hosts = os.getenv("ZABBIX_TRAPPER_ALLOWED_HOSTS", "0.0.0.0/0")

    auto_start = as_bool("AUTO_START", True)
    events_per_hour = float(os.getenv("EVENTS_PER_HOUR", "20"))
    ack_min = int(os.getenv("ACK_MIN_MINUTES", "3"))
    ack_max = int(os.getenv("ACK_MAX_MINUTES", "25"))
    resolution_min = int(os.getenv("RESOLUTION_MIN_MINUTES", "30"))
    resolution_max = int(os.getenv("RESOLUTION_MAX_MINUTES", "180"))
    max_active = int(os.getenv("MAX_ACTIVE_INCIDENTS", "60"))
    one_active_per_host = as_bool("ONE_ACTIVE_INCIDENT_PER_HOST", True)

    client_count = int(os.getenv("CLIENT_COUNT", "20"))
    hosts_per_client = int(os.getenv("HOSTS_PER_CLIENT", "10"))
    host_group = os.getenv("HOST_GROUP", "LAB - Incident Simulator")

    http_port = int(os.getenv("HTTP_PORT", "8080"))
    api_key = os.getenv("API_KEY", "change-me")
    sqlite_path = os.getenv("SQLITE_PATH", "/data/simulator.db")
    log_level = os.getenv("LOG_LEVEL", "INFO")
