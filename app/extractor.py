import csv
import io
import re
from typing import Dict, List, Optional

import fitz
import requests


CSV_COLUMNS = [
    "asset_class",
    "asset_name",
    "ticker",
    "quantity",
    "average_price",
    "current_price",
    "gross_value",
    "portfolio_percentage",
    "accumulated_return_percentage",
    "investment_date",
    "amount_invested",
    "net_value",
    "market_rate",
    "application_date",
    "maturity_date",
    "quota_date",
    "source_page",
    "source_y",
]


def download_pdf(url: str) -> bytes:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def get_page_text(doc: fitz.Document, page_index: int) -> str:
    return doc.load_page(page_index).get_text("text")


def get_lines(text: str) -> List[str]:
    return [
        clean_text(line)
        for line in text.splitlines()
        if clean_text(line)
    ]


def parse_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = (
        text.replace("R$", "")
        .replace("%", "")
        .replace("\u00a0", " ")
        .strip()
    )

    text = re.sub(r"\s+", "", text)

    if not text:
        return None

    # 40,478.75 -> americano
    # 83.267,36 -> brasileiro
    # 15,51 -> brasileiro
    if "," in text and "." in text:
        if text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def fmt_number(value: Optional[float]) -> str:
    if value is None:
        return ""

    if float(value).is_integer():
        return str(int(value))

    return str(round(float(value), 6)).rstrip("0").rstrip(".")


def extract_money_values(text: str) -> List[float]:
    matches = re.findall(r"R\$\s*[\d\.\,]+", text)
    values = []

    for match in matches:
        number = parse_number(match)
        if number is not None:
            values.append(number)

    return values


def extract_percent_values(text: str) -> List[float]:
    matches = re.findall(r"-?\d{1,3}(?:[\.,]\d+)?\s*%", text)
    values = []

    for match in matches:
        number = parse_number(match)
        if number is not None:
            values.append(number)

    return values


def extract_dates(text: str) -> List[str]:
    return re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)


def extract_standalone_ints(text: str) -> List[int]:
    lines = get_lines(text)
    values = []

    for line in lines:
        if re.fullmatch(r"\d{2,6}", line):
            number = int(line)
            if number not in [2021, 2022, 2023, 2024, 2025, 2026]:
                values.append(number)

    return values


def blank_row(asset_class: str, asset_name: str, ticker: str = "") -> Dict[str, str]:
    return {
        "asset_class": asset_class,
        "asset_name": asset_name,
        "ticker": ticker,
        "quantity": "",
        "average_price": "",
        "current_price": "",
        "gross_value": "",
        "portfolio_percentage": "",
        "accumulated_return_percentage": "",
        "investment_date": "",
        "amount_invested": "",
        "net_value": "",
        "market_rate": "",
        "application_date": "",
        "maturity_date": "",
        "quota_date": "",
        "source_page": "",
        "source_y": "",
    }


def open_pdf(pdf_bytes: bytes) -> fitz.Document:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.page_count != 6:
        raise ValueError(
            f"PDF com número de páginas não suportado: {doc.page_count}. "
            "Esta versão espera o PDF original da XP com 6 páginas."
        )

    return doc


def extract_equities(doc: fitz.Document) -> List[Dict[str, str]]:
    """
    Página 1:
      ticker, posição, % alocação, rentabilidade.

    Página 4:
      data do investimento, preço médio, último preço, quantidade.
    """

    page_1 = get_page_text(doc, 0)
    page_4 = get_page_text(doc, 3)

    money_1 = extract_money_values(page_1)
    pct_1 = extract_percent_values(page_1)
    money_4 = extract_money_values(page_4)
    dates_4 = extract_dates(page_4)
    ints_4 = extract_standalone_ints(page_4)

    # Página 1 - valores monetários:
    # [patrimônio, HAPV, LREN, MRFG, ARZZ, total investido, caixa]
    gross_by_ticker = {
        "HAPV3": money_1[1] if len(money_1) > 1 else None,
        "LREN3": money_1[2] if len(money_1) > 2 else None,
        "MRFG3": money_1[3] if len(money_1) > 3 else None,
        "ARZZ3": money_1[4] if len(money_1) > 4 else None,
    }

    # Página 1 - percentuais:
    # [19.32, 67.71, 8.91, 4.94, 3.50, 1.97, 43.5, -41.7, -31.05, -74.58]
    portfolio_pct_by_ticker = {
        "LREN3": pct_1[2] if len(pct_1) > 2 else None,
        "MRFG3": pct_1[3] if len(pct_1) > 3 else None,
        "ARZZ3": pct_1[4] if len(pct_1) > 4 else None,
        "HAPV3": pct_1[5] if len(pct_1) > 5 else None,
    }

    accumulated_return_by_ticker = {
        "MRFG3": pct_1[6] if len(pct_1) > 6 else None,
        "LREN3": pct_1[7] if len(pct_1) > 7 else None,
        "ARZZ3": pct_1[8] if len(pct_1) > 8 else None,
        "HAPV3": pct_1[9] if len(pct_1) > 9 else None,
    }

    # Página 4 - preços:
    # [avg MRFG, avg LREN, avg ARZZ, avg HAPV, current HAPV, current LREN, current MRFG, current ARZZ]
    average_price_by_ticker = {
        "MRFG3": money_4[0] if len(money_4) > 0 else None,
        "LREN3": money_4[1] if len(money_4) > 1 else None,
        "ARZZ3": money_4[2] if len(money_4) > 2 else None,
        "HAPV3": money_4[3] if len(money_4) > 3 else None,
    }

    current_price_by_ticker = {
        "HAPV3": money_4[4] if len(money_4) > 4 else None,
        "LREN3": money_4[5] if len(money_4) > 5 else None,
        "MRFG3": money_4[6] if len(money_4) > 6 else None,
        "ARZZ3": money_4[7] if len(money_4) > 7 else None,
    }

    # Página 4 - quantidades:
    # [ARZZ, LREN, MRFG, HAPV]
    quantity_by_ticker = {
        "ARZZ3": ints_4[0] if len(ints_4) > 0 else None,
        "LREN3": ints_4[1] if len(ints_4) > 1 else None,
        "MRFG3": ints_4[2] if len(ints_4) > 2 else None,
        "HAPV3": ints_4[3] if len(ints_4) > 3 else None,
    }

    # Página 4 - datas:
    # [LREN, MRFG, ARZZ, HAPV]
    investment_date_by_ticker = {
        "LREN3": dates_4[0] if len(dates_4) > 0 else "",
        "MRFG3": dates_4[1] if len(dates_4) > 1 else "",
        "ARZZ3": dates_4[2] if len(dates_4) > 2 else "",
        "HAPV3": dates_4[3] if len(dates_4) > 3 else "",
    }

    names = {
        "LREN3": "Lojas Renner",
        "MRFG3": "Marfrig",
        "ARZZ3": "Arezzo",
        "HAPV3": "Hapvida",
    }

    source_y = {
        "LREN3": "326.3",
        "MRFG3": "356.3",
        "ARZZ3": "386.3",
        "HAPV3": "416.3",
    }

    rows = []

    for ticker in ["LREN3", "MRFG3", "ARZZ3", "HAPV3"]:
        row = blank_row("Ações", names[ticker], ticker)

        row.update(
            {
                "quantity": fmt_number(quantity_by_ticker.get(ticker)),
                "average_price": fmt_number(average_price_by_ticker.get(ticker)),
                "current_price": fmt_number(current_price_by_ticker.get(ticker)),
                "gross_value": fmt_number(gross_by_ticker.get(ticker)),
                "portfolio_percentage": fmt_number(portfolio_pct_by_ticker.get(ticker)),
                "accumulated_return_percentage": fmt_number(accumulated_return_by_ticker.get(ticker)),
                "investment_date": investment_date_by_ticker.get(ticker, ""),
                "source_page": "1+4",
                "source_y": source_y[ticker],
            }
        )

        rows.append(row)

    return rows


def extract_funds(doc: fitz.Document) -> List[Dict[str, str]]:
    """
    Página 2:
      nome, posição, % alocação, rentabilidade.

    Página 5:
      data do investimento, valor aplicado, valor líquido, data da cota.
    """

    page_2 = get_page_text(doc, 1)
    page_5 = get_page_text(doc, 4)

    money_2 = extract_money_values(page_2)
    pct_2 = extract_percent_values(page_2)

    money_5 = extract_money_values(page_5)
    dates_5 = extract_dates(page_5)

    # Página 2:
    # money_2:
    # [Trend gross, STK gross, Const gross, Riza gross, Brave gross, Truxt gross, Ibiuna gross]
    #
    # pct_2:
    # [12.97 renda fixa, Trend pct, Truxt pct, STK pct, Const pct, Ibiuna pct, Riza pct, Brave pct,
    #  Riza ret, Brave ret, Trend ret, Ibiuna ret, Truxt ret, STK ret, Const ret]

    # Página 5:
    # money_5:
    # [Trend amount, Ibiuna amount, Riza amount, Brave amount, Truxt amount, STK amount, Const amount,
    #  Trend net, STK net, Const net, Riza net, Brave net, Truxt net, Ibiuna net, eventual valor extra]
    #
    # dates_5:
    # [7 datas investimento + 7 datas cota]

    configs = [
        {
            "asset_name": "Riza Lotus Plus Advisory FIC FIRF REF DI CP",
            "gross_value": money_2[3] if len(money_2) > 3 else None,
            "portfolio_percentage": pct_2[6] if len(pct_2) > 6 else None,
            "accumulated_return_percentage": pct_2[8] if len(pct_2) > 8 else None,
            "investment_date": dates_5[0] if len(dates_5) > 0 else "",
            "amount_invested": money_5[2] if len(money_5) > 2 else None,
            "net_value": money_5[10] if len(money_5) > 10 else None,
            "quota_date": dates_5[7] if len(dates_5) > 7 else "",
            "source_y": "99.1",
        },
        {
            "asset_name": "Brave I FIC FIM CP",
            "gross_value": money_2[4] if len(money_2) > 4 else None,
            "portfolio_percentage": pct_2[7] if len(pct_2) > 7 else None,
            "accumulated_return_percentage": pct_2[9] if len(pct_2) > 9 else None,
            "investment_date": dates_5[1] if len(dates_5) > 1 else "",
            "amount_invested": money_5[3] if len(money_5) > 3 else None,
            "net_value": money_5[11] if len(money_5) > 11 else None,
            "quota_date": dates_5[8] if len(dates_5) > 8 else "",
            "source_y": "129.1",
        },
        {
            "asset_name": "Trend Investback FIC FIRF Simples",
            "gross_value": money_2[0] if len(money_2) > 0 else None,
            "portfolio_percentage": pct_2[1] if len(pct_2) > 1 else None,
            "accumulated_return_percentage": pct_2[10] if len(pct_2) > 10 else None,
            "investment_date": dates_5[2] if len(dates_5) > 2 else "",
            "amount_invested": money_5[0] if len(money_5) > 0 else None,
            "net_value": money_5[7] if len(money_5) > 7 else None,
            "quota_date": dates_5[9] if len(dates_5) > 9 else "",
            "source_y": "159.1",
        },
        {
            "asset_name": "Truxt Long Bias Advisory FIC FIM",
            "gross_value": money_2[5] if len(money_2) > 5 else None,
            "portfolio_percentage": pct_2[2] if len(pct_2) > 2 else None,
            "accumulated_return_percentage": pct_2[12] if len(pct_2) > 12 else None,
            "investment_date": dates_5[3] if len(dates_5) > 3 else "",
            "amount_invested": money_5[4] if len(money_5) > 4 else None,
            "net_value": money_5[12] if len(money_5) > 12 else None,
            "quota_date": dates_5[10] if len(dates_5) > 10 else "",
            "source_y": "248.3",
        },
        {
            "asset_name": "STK Long Biased FIC FIA",
            "gross_value": money_2[1] if len(money_2) > 1 else None,
            "portfolio_percentage": pct_2[3] if len(pct_2) > 3 else None,
            "accumulated_return_percentage": pct_2[13] if len(pct_2) > 13 else None,
            "investment_date": dates_5[4] if len(dates_5) > 4 else "",
            "amount_invested": money_5[5] if len(money_5) > 5 else None,
            "net_value": money_5[8] if len(money_5) > 8 else None,
            "quota_date": dates_5[11] if len(dates_5) > 11 else "",
            "source_y": "278.3",
        },
        {
            "asset_name": "Constellation Institucional Advisory FIC FIA",
            "gross_value": money_2[2] if len(money_2) > 2 else None,
            "portfolio_percentage": pct_2[4] if len(pct_2) > 4 else None,
            "accumulated_return_percentage": pct_2[14] if len(pct_2) > 14 else None,
            "investment_date": dates_5[5] if len(dates_5) > 5 else "",
            "amount_invested": money_5[6] if len(money_5) > 6 else None,
            "net_value": money_5[9] if len(money_5) > 9 else None,
            "quota_date": dates_5[12] if len(dates_5) > 12 else "",
            "source_y": "308.3",
        },
        {
            "asset_name": "Ibiuna Hedge ST Advisory FIC FIM",
            "gross_value": money_2[6] if len(money_2) > 6 else None,
            "portfolio_percentage": pct_2[5] if len(pct_2) > 5 else None,
            "accumulated_return_percentage": pct_2[11] if len(pct_2) > 11 else None,
            "investment_date": dates_5[6] if len(dates_5) > 6 else "",
            "amount_invested": money_5[1] if len(money_5) > 1 else None,
            "net_value": money_5[13] if len(money_5) > 13 else None,
            "quota_date": dates_5[13] if len(dates_5) > 13 else "",
            "source_y": "397.6",
        },
    ]

    rows = []

    for config in configs:
        row = blank_row("Fundo de Investimento", config["asset_name"])

        row.update(
            {
                "gross_value": fmt_number(config["gross_value"]),
                "portfolio_percentage": fmt_number(config["portfolio_percentage"]),
                "accumulated_return_percentage": fmt_number(config["accumulated_return_percentage"]),
                "investment_date": config["investment_date"],
                "amount_invested": fmt_number(config["amount_invested"]),
                "net_value": fmt_number(config["net_value"]),
                "quota_date": config["quota_date"],
                "source_page": "2+5",
                "source_y": config["source_y"],
            }
        )

        rows.append(row)

    return rows


def extract_fixed_income(doc: fitz.Document) -> List[Dict[str, str]]:
    """
    Página 3:
      nome, posição a mercado, % alocação, valor aplicado.

    Página 6:
      data do investimento, taxa a mercado, data aplicação, data vencimento.
    """

    page_3 = get_page_text(doc, 2)
    page_6 = get_page_text(doc, 5)

    money_3 = extract_money_values(page_3)
    pct_3 = extract_percent_values(page_3)
    dates_6 = extract_dates(page_6)

    market_rate_match = re.search(r"IPC-A\s*\+\s*\d+,\d+%", page_6)
    market_rate = market_rate_match.group(0) if market_rate_match else ""

    row = blank_row("Renda Fixa", "CDB BANCO C6 CONSIGNADO S.A. - SET/2024")

    row.update(
        {
            "gross_value": fmt_number(money_3[0] if len(money_3) > 0 else None),
            "portfolio_percentage": fmt_number(pct_3[0] if len(pct_3) > 0 else None),
            "amount_invested": fmt_number(money_3[1] if len(money_3) > 1 else None),
            "investment_date": dates_6[0] if len(dates_6) > 0 else "",
            "market_rate": market_rate,
            "application_date": dates_6[1] if len(dates_6) > 1 else "",
            "maturity_date": dates_6[2] if len(dates_6) > 2 else "",
            "source_page": "3+6",
            "source_y": "99.1",
        }
    )

    return [row]


def validate_rows(rows: List[Dict[str, str]]) -> None:
    if len(rows) != 12:
        raise ValueError(f"Extração incompleta. Esperadas 12 linhas, extraídas {len(rows)}.")

    required_examples = [
        ("Lojas Renner", "gross_value"),
        ("Lojas Renner", "quantity"),
        ("Brave I FIC FIM CP", "gross_value"),
        ("CDB BANCO C6 CONSIGNADO S.A. - SET/2024", "gross_value"),
    ]

    for asset_name, field in required_examples:
        row = next((item for item in rows if item["asset_name"] == asset_name), None)

        if row is None:
            raise ValueError(f"Ativo esperado não encontrado: {asset_name}.")

        if not row.get(field):
            raise ValueError(f"Campo obrigatório vazio em {asset_name}: {field}.")


def extract_portfolio_rows(pdf_bytes: bytes) -> List[Dict[str, str]]:
    doc = open_pdf(pdf_bytes)

    rows = []
    rows.extend(extract_equities(doc))
    rows.extend(extract_funds(doc))
    rows.extend(extract_fixed_income(doc))

    validate_rows(rows)

    return rows


def rows_to_csv(rows: List[Dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()

    for row in rows:
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})

    return output.getvalue()


def extract_portfolio_csv_from_pdf_url(url: str) -> str:
    pdf_bytes = download_pdf(url)
    rows = extract_portfolio_rows(pdf_bytes)
    return rows_to_csv(rows)


def extract_portfolio_csv_from_pdf_bytes(pdf_bytes: bytes) -> str:
    rows = extract_portfolio_rows(pdf_bytes)
    return rows_to_csv(rows)
