"""Lista as opções (CALL e PUT) de uma ação da B3.

O Yahoo Finance não tem opções da B3, por isso os dados vêm do opcoes.net.br
(endpoint público, não oficial).

Uso:
    python list_options.py PETR4                        # próximo vencimento mensal
    python list_options.py PETR4 --vencimentos          # lista os vencimentos disponíveis
    python list_options.py PETR4 -v 2026-12-18          # vencimento específico
    python list_options.py PETR4 -t call                # só CALLs (ou: -t put)
    python list_options.py PETR4 --com-negocios         # só opções negociadas
"""

import argparse
import time

import pandas as pd
import requests

URL = "https://opcoes.net.br/listaopcoes/completa"
HEADERS = {"User-Agent": "Mozilla/5.0"}

COLUMNS = {
    0: "Ticker",
    2: "Tipo",
    3: "Modelo",
    4: "Moneyness",
    5: "Strike",
    8: "Último",
    9: "Negócios",
    10: "Volume",
    11: "Data",
}


def fetch(symbol: str, vencimento: str | None = None, retries: int = 4) -> dict:
    params = {"idAcao": symbol.upper(), "listarVencimentos": "true", "cotacoes": "true"}
    if vencimento:
        # The site ignores `vencimentos` unless listarVencimentos is false
        params["listarVencimentos"] = "false"
        params["vencimentos"] = vencimento
    for attempt in range(retries + 1):
        response = requests.get(URL, params=params, headers=HEADERS, timeout=15)
        if response.status_code != 429 or attempt == retries:
            break
        time.sleep(5 * (attempt + 1))  # rate limited: wait 5s, 10s, 15s...
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"Não foi possível obter as opções de {symbol}")
    return data["data"]


def list_vencimentos(data: dict) -> list[str]:
    return [v["value"] for v in data.get("vencimentos") or []]


def to_dataframe(data: dict) -> pd.DataFrame:
    rows = [{name: row[i] for i, name in COLUMNS.items()} for row in data["cotacoesOpcoes"]]
    df = pd.DataFrame(rows, columns=list(COLUMNS.values()))
    if df.empty:
        return df
    df["Ticker"] = df["Ticker"].str.split("_").str[0]  # "PETRK600_2026" -> "PETRK600"
    df["Modelo"] = df["Modelo"].map({"A": "Americana", "E": "Europeia"}).fillna(df["Modelo"])
    return df.sort_values(["Tipo", "Strike"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lista opções de uma ação da B3")
    parser.add_argument("acao", help="Código da ação, ex.: PETR4")
    parser.add_argument("-v", "--vencimento", help="Data do vencimento (AAAA-MM-DD)")
    parser.add_argument("-t", "--tipo", choices=["call", "put"], help="Filtrar por tipo")
    parser.add_argument("--vencimentos", action="store_true", help="Listar vencimentos")
    parser.add_argument("--com-negocios", action="store_true", help="Só opções negociadas")
    args = parser.parse_args()

    data = fetch(args.acao, args.vencimento)

    if args.vencimentos:
        print(f"Vencimentos de {args.acao.upper()}:")
        for v in list_vencimentos(data):
            print(f"  {v}")
        return

    df = to_dataframe(data)
    if args.tipo:
        df = df[df["Tipo"] == args.tipo.upper()]
    if args.com_negocios:
        df = df[df["Negócios"].fillna(0) > 0]

    vencimento = args.vencimento or next(
        (v["value"] for v in data.get("vencimentos") or [] if v.get("selected")), "?"
    )
    print(f"Opções de {args.acao.upper()} — vencimento {vencimento} — {len(df)} encontradas\n")
    if df.empty:
        print("Nenhuma opção encontrada.")
        return
    with pd.option_context("display.max_rows", None, "display.width", 200):
        print(df.to_string(index=False, na_rep="-"))


if __name__ == "__main__":
    main()
