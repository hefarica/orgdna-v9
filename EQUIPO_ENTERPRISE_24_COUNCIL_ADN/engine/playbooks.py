"""Playbooks: conocimiento de dominio como DATO. No ejecuta."""
SCHEMA_VERSION = "playbook-1.0"
_REQUIRED = ("id", "title", "roles", "tool_needs", "workflows", "loop", "risk", "evidence", "market")

BETFAIR_VALUE_LAY = {
    "id": "betfair_value_lay",
    "title": "Valor en vivo en Betfair: lay sobre cuota sobrevalorada",
    "objective": "Utilidad diaria con apuestas de valor; el equipo no descansa (24/7/365).",
    "market": {"platform": "betfair", "credential": "BETFAIR_API_KEY", "mode": "live", "side": "lay",
               "max_odds": 2.0, "risk_reward_min": 1.0,
               "prefer": "la cuota mas baja por debajo de 2.0, que mejora el valor por peso"},
    "risk": {"max_loss_per_losing_bet_usd": 2.0, "daily_target_usd": None,
             "stop_when_target_reached": True, "reset": "daily"},
    "loop": {"learn_from_every_loss": True, "reevaluate_each_bet": True,
             "cycle": "continuo", "halt_on": ["target_diario_alcanzado"]},
    "evidence": {"live_sources_min": 30, "scrape_live": True, "keep_history": True,
                 "metrics": ["cuota", "probabilidad_implicita", "resultado", "beneficio"]},
    "roles": (
        {"code": "VALUE", "title": "Buscador de valor", "mission": "Detectar lay sobrevalorado en vivo."},
        {"code": "LAYEXEC", "title": "Ejecutor de lay", "mission": "Apostar en contra con cuota <2.0 y riesgo/retorno >=1:1."},
        {"code": "BANKROLL", "title": "Gobernador de banca", "mission": "Maximo 2 USD por perdida; parar al llegar al objetivo diario."},
        {"code": "LIVESTATS", "title": "Datos en vivo", "mission": "Scraping y consolidacion de >=30 fuentes en tiempo real."},
        {"code": "LEARNLOSS", "title": "Aprendiz de perdidas", "mission": "Registrar cada perdida y mejorar el analisis siguiente."},
        {"code": "ORCH", "title": "Orquestador", "mission": "Concatenar al equipo y sostener el ciclo."},
    ),
    "tool_needs": ("ops_plan", "ops_status", "run_search", "evidence_add", "research_report", "why_find"),
    "workflows": ("scrape_live_30_sources", "rank_overvalued_lay", "size_bet_risk_2usd",
                  "execute_lay", "record_result", "learn_from_loss", "check_daily_target"),
}

PLAYBOOKS = {"betfair_value_lay": BETFAIR_VALUE_LAY}


def validate_playbook(playbook):
    if not isinstance(playbook, dict):
        raise ValueError("playbook: se requiere objeto.")
    missing = [key for key in _REQUIRED if key not in playbook]
    if missing:
        raise ValueError("playbook: faltan campos: " + ", ".join(missing))
    codes = [role["code"] for role in playbook["roles"]]
    if len(set(codes)) != len(codes):
        raise ValueError("playbook.roles: codigos duplicados.")
    if not playbook["tool_needs"]:
        raise ValueError("playbook.tool_needs: vacío.")
    if not 0 < float(playbook["market"]["max_odds"]) <= 100:
        raise ValueError("playbook.market.max_odds fuera de rango.")
    if float(playbook["risk"]["max_loss_per_losing_bet_usd"]) <= 0:
        raise ValueError("playbook.risk.max_loss_per_losing_bet_usd debe ser > 0.")
    return True


def preflight_playbook(playbook, catalog_names):
    """Convierte el playbook en la lista de tool_needs que la puerta exigirá por rol."""
    validate_playbook(playbook)
    known = set(catalog_names)
    return {"roles": [role["code"] for role in playbook["roles"]],
            "tool_needs": list(playbook["tool_needs"]),
            "unknown_in_catalog": sorted(set(playbook["tool_needs"]) - known),
            "workflows": list(playbook["workflows"])}
