"""Check Brazilian stocks against COMPRA (buy) and VENDA (sell) targets.

Reads targets from stocks.json:
    {"PETR4": {"COMPRA": 20, "VENDA": 30, "PREMIO_MINIMO_PCT": 2,
               "QUANTIDADE": 100, "PRECO_MEDIO": 38.50}}

PREMIO_MINIMO_PCT (required): minimum NET return of selling the option, as a
percentage of the exercised volume (strike x QUANTIDADE), assuming the option
is exercised. Net = premium - exercise costs - income tax on the profit.
QUANTIDADE (required): number of options sold.
PRECO_MEDIO (optional): your average purchase price of the stock. When set,
each CALL also shows the total profit if exercised (premium + gain on the
shares sold at the strike, minus costs and income tax).

When a target is hit, a second message lists options to sell, for every
expiration between DIAS_MIN and DIAS_MAX days from today:
    VENDA  -> CALLs with strike at or above the current price
    COMPRA -> PUTs with strike at or below the current price

Usage:
    python check_stocks.py           # print the result for each stock
    python check_stocks.py --notify  # also send alerts through Telegram

With --notify, each alert is sent once per day per type (COMPRA/VENDA):
stocks already alerted are recorded in informados.json.
"""

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import yfinance as yf

import informados
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
ULTIMO_NEGOCIO_MAX_DIAS = 5  # ignore options whose last trade is older (stale premium)


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


def exercise_profit(
    premio: float, strike: float, quantidade: int, preco_medio: float
) -> tuple[float, float]:
    """Total net profit if a sold CALL is exercised: you keep the premium and
    sell `quantidade` shares bought at `preco_medio` for `strike`.

    profit = premium received - exercise cost + (strike - preco_medio) x quantidade,
             minus IMPOSTO_PCT if positive
    Returns (profit in R$, profit as % of the shares' cost preco_medio x quantidade).
    """
    volume = strike * quantidade
    custo = max(CUSTO_MINIMO, volume * CUSTO_PCT / 100) + CUSTO_FIXO
    lucro = premio * quantidade - custo + (strike - preco_medio) * quantidade
    if lucro > 0:
        lucro *= 1 - IMPOSTO_PCT / 100
    return lucro, lucro / (preco_medio * quantidade) * 100


def format_brl(value: float) -> str:
    """1234.5 -> '1.234,50'"""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def options_message(
    symbol: str,
    price: float,
    tipo: str,
    premio_pct: float,
    quantidade: int,
    preco_medio: float | None = None,
) -> str:
    """List options to sell for every expiration (weekly and monthly)
    DIAS_MIN to DIAS_MAX days away, whose EXTRINSIC value (premium minus
    intrinsic value) gives a net return >= premio_pct% (see net_return_pct).
    For OTM options the extrinsic value is the whole premium.

    tipo="CALL": any strike, ITM or OTM (sell a call when VENDA is hit).
    tipo="PUT":  strike <= current price, OTM only (sell a put when COMPRA is hit).
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
        f"(sobre o valor extrínseco, já descontando taxas de exercício e {IMPOSTO_PCT:g}% de IR)\n"
        f"Só opções negociadas nos últimos {ULTIMO_NEGOCIO_MAX_DIAS} dias\n"
    )
    show_profit = tipo == "CALL" and preco_medio is not None
    if show_profit:
        header += f"Preço médio R$ {preco_medio:.2f}\n"
    if not vencimentos:
        return header + "\nNenhum vencimento nesse intervalo."

    sections = []
    for vencimento in vencimentos:
        time.sleep(REQUEST_PAUSE)  # avoid opcoes.net.br rate limit
        df = list_options.to_dataframe(list_options.fetch(symbol, vencimento))
        if df.empty:
            continue
        recente = (today - timedelta(days=ULTIMO_NEGOCIO_MAX_DIAS)).isoformat()
        df = df[
            (df["Tipo"] == tipo) & df["Último"].notna() & (df["Data"].fillna("") >= recente)
        ].copy()
        if tipo == "PUT":
            df = df[df["Strike"] <= price]
        intrinseco = (price - df["Strike"]) if tipo == "CALL" else (df["Strike"] - price)
        df["Extrínseco"] = df["Último"] - intrinseco.clip(lower=0)
        df["Líquido"] = [
            net_return_pct(extrinseco, strike, quantidade)
            for extrinseco, strike in zip(df["Extrínseco"], df["Strike"])
        ]
        df = df[df["Líquido"] >= premio_pct]
        if df.empty:
            continue
        if tipo == "PUT":
            df = df.sort_values("Strike", ascending=False)  # closest to the price first
        lines = []
        for row in df.to_dict("records"):
            itm = row["Extrínseco"] < row["Último"]
            premio = f"Prêmio R$ {row['Último']:.2f} "
            if itm:
                premio += f"· Extrínseco R$ {row['Extrínseco']:.2f} "
            line = (
                f"{row['Ticker']} · {'ITM' if itm else 'OTM'} · "
                f"Strike R$ {row['Strike']:.2f} · {premio}"
                f"(bruto {row['Extrínseco'] / row['Strike'] * 100:.1f}% · "
                f"líquido {row['Líquido']:.1f}%) · "
                f"{row['Modelo']}"
            )
            if show_profit:
                lucro, lucro_pct = exercise_profit(
                    row["Último"], row["Strike"], quantidade, preco_medio
                )
                emoji = "💰" if lucro >= 0 else "🔻"
                line += f"\n   {emoji} Se exercida: R$ {format_brl(lucro)} ({lucro_pct:+.1f}%)"
            lines.append(line)
        venc_br = date.fromisoformat(vencimento).strftime("%d/%m/%Y")
        sections.append(f"📅 Vencimento {venc_br}\n" + "\n".join(lines))

    if not sections:
        return header + f"\nNenhuma {tipo} com o retorno mínimo."
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
        if notify and informados.already_informed(symbol, kind):
            print(f"🔕 {symbol}: alerta de {kind} já enviado hoje")
            continue
        print(alert)
        if notify:
            send_message(alert)
            informados.mark_informed(symbol, kind)

        tipo = "CALL" if kind == "VENDA" else "PUT"
        premio_pct = targets.get("PREMIO_MINIMO_PCT")
        quantidade = targets.get("QUANTIDADE")
        if premio_pct is None or quantidade is None:
            print(f"⚠️  {symbol}: defina PREMIO_MINIMO_PCT e QUANTIDADE no stocks.json")
            continue
        try:
            message = options_message(
                symbol, price, tipo, premio_pct, quantidade, targets.get("PRECO_MEDIO")
            )
        except Exception as e:
            print(f"⚠️  {symbol}: não foi possível obter as {tipo}s ({e})")
            continue
        print(message, end="\n\n")
        if notify:
            send_message(message)


if __name__ == "__main__":
    main()
