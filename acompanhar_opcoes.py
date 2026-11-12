"""Acompanha as opções que você comprou ou vendeu e mostra o resultado de
encerrar a posição agora (vender o que comprou / recomprar o que vendeu).

Lê as posições de posicoes.json:
    {
      "BBASX181": {"ACAO": "BBAS3", "OPERACAO": "COMPRA", "PREMIO": 0.57, "QUANTIDADE": 600},
      "CSMGL562": {"ACAO": "CSMG3", "OPERACAO": "VENDA",  "PREMIO": 1.48, "QUANTIDADE": 100}
    }

OPERACAO: "COMPRA" (você comprou a opção) ou "VENDA" (você vendeu a opção).
PREMIO:   valor pago (COMPRA) ou recebido (VENDA) por opção.

Uso:
    python acompanhar_opcoes.py           # mostra o resultado no terminal
    python acompanhar_opcoes.py --notify  # também envia pelo Telegram
"""

import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import list_options
from check_stocks import IMPOSTO_PCT, REQUEST_PAUSE, format_brl, get_price

POSICOES_FILE = Path(__file__).parent / "posicoes.json"
TZ = ZoneInfo("America/Sao_Paulo")
CORRETAGEM_POR_ORDEM = 0.00  # R$ cobrado pela corretora para encerrar a posição

# B3 option tickers: 4-letter root + month letter + strike code (+ W1..W5 if weekly)
CALL_MONTHS = "ABCDEFGHIJKL"  # A=Jan ... L=Dec
PUT_MONTHS = "MNOPQRSTUVWX"  # M=Jan ... X=Dec


def load_posicoes() -> dict:
    with open(POSICOES_FILE, encoding="utf-8") as f:
        return json.load(f)


def find_vencimento(ticker: str, vencimentos: list[dict]) -> str:
    """Find the expiration date of an option from its ticker."""
    letter = ticker[4]
    if letter in CALL_MONTHS:
        month = CALL_MONTHS.index(letter) + 1
    elif letter in PUT_MONTHS:
        month = PUT_MONTHS.index(letter) + 1
    else:
        raise ValueError(f"código de opção inválido: {ticker}")
    weekly = re.search(r"(W\d)$", ticker)

    for v in vencimentos:  # sorted by date, so the first match is the nearest
        venc = date.fromisoformat(v["value"])
        attrs = v.get("dataAttributes") or {}
        same_kind = attrs.get("w") == weekly.group(1) if weekly else attrs.get("m") == "1"
        if venc.month == month and venc >= date.today() and same_kind:
            return v["value"]
    raise ValueError(f"vencimento de {ticker} não encontrado")


def fetch_option(ticker: str, acao: str) -> dict:
    """Return the option's current row (Último, Data, Strike, Tipo...)."""
    vencimento = find_vencimento(ticker, list_options.fetch(acao).get("vencimentos") or [])
    time.sleep(REQUEST_PAUSE)  # avoid opcoes.net.br rate limit
    df = list_options.to_dataframe(list_options.fetch(acao, vencimento))
    rows = df[df["Ticker"] == ticker]
    if rows.empty:
        raise ValueError(f"{ticker} não encontrada no vencimento {vencimento}")
    return {**rows.iloc[0].to_dict(), "Vencimento": vencimento}


def resultado(operacao: str, premio: float, atual: float, quantidade: int) -> float:
    """Net result (R$) of closing the position now, after costs and income tax."""
    if operacao == "COMPRA":  # close by selling
        lucro = (atual - premio) * quantidade
    else:  # VENDA: close by buying back
        lucro = (premio - atual) * quantidade
    lucro -= CORRETAGEM_POR_ORDEM
    if lucro > 0:
        lucro *= 1 - IMPOSTO_PCT / 100
    return lucro


def describe(ticker: str, pos: dict) -> str:
    acao, operacao = pos["ACAO"], pos["OPERACAO"].upper()
    premio, quantidade = pos["PREMIO"], pos["QUANTIDADE"]

    opt = fetch_option(ticker, acao)
    atual = opt["Último"]
    cotacao = get_price(acao)
    venc = date.fromisoformat(opt["Vencimento"])
    dias = (venc - date.today()).days

    acao_txt = "vendida" if operacao == "VENDA" else "comprada"
    lines = [
        f"{'🟢' if operacao == 'COMPRA' else '🔵'} {ticker} ({opt['Tipo']} {acao_txt}) · "
        f"{quantidade} × R$ {premio:.2f}",
        f"   {acao} R$ {cotacao:.2f} · Strike R$ {opt['Strike']:.2f} · "
        f"Vence {venc:%d/%m} ({dias} dias)",
    ]
    if atual is None or atual != atual:  # None or NaN: never traded
        lines.append("   ⚠️ Sem negócios registrados para essa opção")
        return "\n".join(lines)

    variacao = (atual / premio - 1) * 100
    ultimo = date.fromisoformat(opt["Data"]).strftime("%d/%m") if opt.get("Data") else "?"
    lines.append(f"   Prêmio agora R$ {atual:.2f} ({variacao:+.1f}%) · último negócio {ultimo}")

    r = resultado(operacao, premio, atual, quantidade)
    base = premio * quantidade
    acao_fechar = "vender" if operacao == "COMPRA" else "recomprar"
    emoji = "💰" if r >= 0 else "🔻"
    lines.append(
        f"   {emoji} Se {acao_fechar} agora: R$ {format_brl(r)} ({r / base * 100:+.1f}%)"
    )
    return "\n".join(lines)


def build_message() -> str | None:
    posicoes = load_posicoes()
    if not posicoes:
        return None
    agora = datetime.now(TZ)
    blocks = []
    for ticker, pos in posicoes.items():
        try:
            blocks.append(describe(ticker.upper(), pos))
        except Exception as e:
            blocks.append(f"⚠️ {ticker}: não foi possível atualizar ({e})")
    header = (
        f"📊 Suas opções · {agora:%d/%m %H:%M}\n"
        f"(resultado líquido de {IMPOSTO_PCT:g}% de IR se encerrar agora)"
    )
    return header + "\n\n" + "\n\n".join(blocks)


def main() -> None:
    message = build_message()
    if not message:
        print("Nenhuma posição em posicoes.json")
        return
    print(message)
    if "--notify" in sys.argv:
        from telegram_notify import send_message

        send_message(message)


if __name__ == "__main__":
    main()
