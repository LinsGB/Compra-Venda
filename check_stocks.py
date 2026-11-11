"""Check Brazilian stocks against COMPRA (buy) and VENDA (sell) targets.

Reads targets from stocks.json:
    {"PETR4": {"COMPRA": 20, "VENDA": 30, "PREMIO_MINIMO_PCT": 2, "QUANTIDADE": 100}}

PREMIO_MINIMO_PCT (required): minimum NET return of selling the option, as a
percentage of the exercised volume (strike x QUANTIDADE), assuming the option
is exercised. Net = premium - exercise costs - income tax on the profit.
QUANTIDADE (required): number of options sold.

When a target is hit, a second message lists options to sell, for every
expiration between DIAS_MIN and DIAS_MAX days from today:
    VENDA  -> CALLs with strike at or above the current price
    COMPRA -> PUTs with strike at or below the current price

Usage:
    python check_stocks.py           # print the result for each stock
    python check_stocks.py --notify  # also send alerts through Telegram
"""

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import yfinance as yf

import list_options

STOCKS_FILE = Path(__file__).parent / "stocks.json"
REQUEST_PAUSE = 2  # seconds between opcoes.net.br requests
# Costs when an option is exercised
CUSTO_MINIMO = 50.00  # R$ minimum exercise fee...
CUSTO_PCT = 0.5  # ...or this % of the exercised volume, whichever is higher
CUSTO_FIXO = 25.21  # R$ fixed fee added on top
IMPOSTO_PCT = 15.0  # income tax on the profit
DIAS_MIN = 30  # only expirations at least this many days from today
DIAS_MAX = 45  # ...and at most this many days from today


def load_targets() -> dict:
    with open(STOCKS_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_price(symbol: str) -> float:
    """Get the latest price. B3 stocks need the .SA suffix on Yahoo Finance."""
    ticker = symbol if symbol.endswith(".SA") else f"{symbol}.SA"
    return float(yf.Ticker(ticker).fast_info["last_price"])


def check(symbol: str, targets: dict, price: float) -> tuple[str, str] | None:
    """Return (kind, message) if a target was hit, otherwise None."""
    compra = targets.get("COMPRA")
    venda = targets.get("VENDA")

    if compra is not None and price <= compra:
        return "COMPRA", f"🟢 COMPRA: {symbol} está em R$ {price:.2f} (alvo ≤ R$ {compra:.2f})"
    if venda is not None and price >= venda:
        return "VENDA", f"🔴 VENDA: {symbol} está em R$ {price:.2f} (alvo ≥ R$ {venda:.2f})"

    print(f"⚪ {symbol}: R$ {price:.2f} — entre COMPRA {compra} e VENDA {venda}")
    return None


def net_return_pct(premio: float, strike: float, quantidade: int) -> float:
    """Net return (%) of selling `quantidade` options at `premio` if exercised.

    exercise cost = max(CUSTO_MINIMO, CUSTO_PCT% of volume) + CUSTO_FIXO
    net profit    = (premium received - exercise cost), minus IMPOSTO_PCT if positive
    return        = net profit / exercised volume (strike x quantidade)
    """
    volume = strike * quantidade
    custo = max(CUSTO_MINIMO, volume * CUSTO_PCT / 100) + CUSTO_FIXO
    lucro = premio * quantidade - custo
    if lucro > 0:
        lucro *= 1 - IMPOSTO_PCT / 100
    return lucro / volume * 100


def options_message(
    symbol: str, price: float, tipo: str, premio_pct: float, quantidade: int
) -> str:
    """List options to sell for every expiration (weekly and monthly)
    DIAS_MIN to DIAS_MAX days away, with net return >= premio_pct%
    (see net_return_pct).

    tipo="CALL": strike >= current price (sell a call when VENDA is hit).
    tipo="PUT":  strike <= current price (sell a put when COMPRA is hit).
    """
    today = date.today()
    start = today + timedelta(days=DIAS_MIN)
    end = today + timedelta(days=DIAS_MAX)
    vencimentos = [
        v for v in list_options.list_vencimentos(list_options.fetch(symbol))
        if start <= date.fromisoformat(v) <= end
    ]

    header = (
        f"📋 {tipo}s de {symbol} (ação em R$ {price:.2f})\n"
        f"Vencimentos entre {DIAS_MIN} e {DIAS_MAX} dias "
        f"({start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}) · "
        f"Retorno líquido mínimo {premio_pct:g}% · {quantidade} opções\n"
        f"(já descontando taxas de exercício e {IMPOSTO_PCT:g}% de IR)\n"
    )
    if not vencimentos:
        return header + "\nNenhum vencimento nesse intervalo."

    sections = []
    for vencimento in vencimentos:
        time.sleep(REQUEST_PAUSE)  # avoid opcoes.net.br rate limit
        df = list_options.to_dataframe(list_options.fetch(symbol, vencimento))
        if df.empty:
            continue
        strike_ok = df["Strike"] >= price if tipo == "CALL" else df["Strike"] <= price
        df = df[(df["Tipo"] == tipo) & strike_ok & df["Último"].notna()].copy()
        df["Líquido"] = [
            net_return_pct(premio, strike, quantidade)
            for premio, strike in zip(df["Último"], df["Strike"])
        ]
        df = df[df["Líquido"] >= premio_pct]
        if df.empty:
            continue
        if tipo == "PUT":
            df = df.sort_values("Strike", ascending=False)  # closest to the price first
        lines = [
            f"{row['Ticker']} · Strike R$ {row['Strike']:.2f} · "
            f"Prêmio R$ {row['Último']:.2f} "
            f"(bruto {row['Último'] / row['Strike'] * 100:.1f}% · "
            f"líquido {row['Líquido']:.1f}%) · "
            f"{row['Modelo']}"
            for row in df.to_dict("records")
        ]
        venc_br = date.fromisoformat(vencimento).strftime("%d/%m/%Y")
        sections.append(f"📅 Vencimento {venc_br}\n" + "\n".join(lines))

    if not sections:
        lado = "acima" if tipo == "CALL" else "abaixo"
        return header + f"\nNenhuma {tipo} com strike {lado} da cotação e retorno mínimo."
    return header + "\n" + "\n\n".join(sections)


def main() -> None:
    notify = "--notify" in sys.argv
    if notify:
        from telegram_notify import send_message

    for symbol, targets in load_targets().items():
        try:
            price = get_price(symbol)
        except Exception as e:
            print(f"⚠️  {symbol}: não foi possível obter o preço ({e})")
            continue

        result = check(symbol, targets, price)
        if not result:
            continue

        kind, alert = result
        print(alert)
        if notify:
            send_message(alert)

        tipo = "CALL" if kind == "VENDA" else "PUT"
        premio_pct = targets.get("PREMIO_MINIMO_PCT")
        quantidade = targets.get("QUANTIDADE")
        if premio_pct is None or quantidade is None:
            print(f"⚠️  {symbol}: defina PREMIO_MINIMO_PCT e QUANTIDADE no stocks.json")
            continue
        try:
            message = options_message(symbol, price, tipo, premio_pct, quantidade)
        except Exception as e:
            print(f"⚠️  {symbol}: não foi possível obter as {tipo}s ({e})")
            continue
        print(message, end="\n\n")
        if notify:
            send_message(message)


if __name__ == "__main__":
    main()
