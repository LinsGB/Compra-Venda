"""Remember which stocks were already alerted today, so each alert is sent
only once per day per target type.

File format (informados.json):
    {"COMPRA": {"JA_INFORMADO": ["BBAS3"]}, "VENDA": {"JA_INFORMADO": ["CSMG3"]}}
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

INFORMADOS_FILE = Path(
    os.getenv("INFORMADOS_FILE", Path(__file__).parent / "informados.json")
)
TIPOS = ("COMPRA", "VENDA")


def empty() -> dict:
    return {tipo: {"JA_INFORMADO": []} for tipo in TIPOS}


def load() -> dict:
    try:
        with open(INFORMADOS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return empty()
    # Make sure both keys exist even if the file was edited by hand
    for tipo in TIPOS:
        data.setdefault(tipo, {}).setdefault("JA_INFORMADO", [])
    return data


def save(data: dict) -> None:
    with open(INFORMADOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def already_informed(symbol: str, tipo: str) -> bool:
    return symbol in load()[tipo]["JA_INFORMADO"]


def mark_informed(symbol: str, tipo: str) -> None:
    data = load()
    if symbol not in data[tipo]["JA_INFORMADO"]:
        data[tipo]["JA_INFORMADO"].append(symbol)
        save(data)


def reset() -> None:
    save(empty())


def reset_if_new_day(today: date) -> bool:
    """Clear the file on the first run of the day (file missing or last
    changed before today). Returns True if it was cleared."""
    if INFORMADOS_FILE.exists():
        changed = datetime.fromtimestamp(INFORMADOS_FILE.stat().st_mtime).date()
        if changed >= today:
            return False
    reset()
    return True
