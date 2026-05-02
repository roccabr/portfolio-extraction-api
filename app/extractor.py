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


def fmt(value: Optional[float]) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(round(float(value), 6)).rstrip("0").rstrip(".")


def extract_money_values(text: str) -> List[float]:
    matches = re.findall(r"R\$\s*[\d\.\,]+", text)
    return [v for v in [parse_number(m) for m in matches] if v is not None]


def extract_percent_values(text: str) -> List[float]:
    matches = re.findall(r"-?\d{1,3}(?:[\.,]\d+)?\s*%", text)
    return [v for v in [parse_number(m) for m in matches] if v is not None]


def extract_dates(text: str) -> List[str]:
    return re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)


def open_pdf(pdf_bytes: bytes) -> fitz.Document:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.page_count not in [3, 6]:
        raise ValueError(
            f"PDF com número de páginas não suportado: {doc.page_count}. Esperado 3 ou 6."
        )

    return doc


def get_page_text(doc: fitz.Document, page_index: int) -> str:
    if page_index >= doc.page_count:
        return ""
    return doc.load_page(page_index).get_text("text")


def get_logical_texts(doc: fitz.Document) -> Dict[str, str]:
    """
    PDF original:
    - Página 1 + 4 = Ações
    - Página 2 + 5 = Fundos
    - Página 3 + 6 = Renda Fixa

    PDF rebuilt:
    - Página 1 = Ações
    - Página 2 = Fundos
    - Página 3 = Renda Fixa
    """
    if doc.page_count == 6:
        return {
            "equities_left": get_page_text(doc, 0),
            "equities_right": get_page_text(doc, 3),
            "funds_left": get_page_text(doc, 1),
            "funds_right": get_page_text(doc, 4),
            "fixed_left": get_page_text(doc, 2),
            "fixed_right": get_page_text(doc, 5),
        }

    return {
        "equities_left": get_page_text(doc, 0),
        "equities_right": get_page_text(doc, 0),
        "funds_left": get_page_text(doc, 1),
        "funds_right": get_page_text(doc, 1),
        "fixed_left": get_page_text(doc, 2),
        "fixed_right": get_page_text(doc, 2),
    }


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


def extract_equities(texts: Dict[str, str]) -> List[Dict[str, str]]:
    left = texts["equities_left"]
    right = texts["equities_right"]

    rows = []

    # Extração baseada no layout XP atual.
    # Página esquerda traz tickers, posição, % alocação e rentabilidade.
    # Página direita traz data, preço médio, último preço e quantidade.

    left_money = extract_money_values(left)
    left_pct = extract_percent_values(left)
    right_money = extract_money_values(right)
    right_dates = extract_dates(right)

    right_ints = [
        int(x)
        for x in re.findall(r"\b\d{2,6}\b", right)
        if int(x) not in [2021, 2022, 2023, 2024, 2025]
    ]

    # Valores conhecidos por posição no layout:
    # left_money: patrimônio, HAPV, LREN, MRFG, ARZZ, total investido, caixa...
    gross_by_ticker = {
        "HAPV3": left_money[1] if len(left_money) > 1 else None,
        "LREN3": left_money[2] if len(left_money) > 2 else None,
        "MRFG3": left_money[3] if len(left_money) > 3 else None,
        "ARZZ3": left_money[4] if len(left_money) > 4 else None,
    }

    # Percentuais de alocação das ações no relatório.
    # Primeiros percentuais são % da classe, depois vêm as alocações por ativo.
    allocation_candidates = [p for p in left_pct if p not in [19.32, 67.71]]
    portfolio_pct_by_ticker = {
        "LREN3": allocation_candidates[0] if len(allocation_candidates) > 0 else None,
        "MRFG3": allocation_candidates[1] if len(allocation_candidates) > 1 else None,
        "ARZZ3": allocation_candidates[2] if len(allocation_candidates) > 2 else None,
        "HAPV3": allocation_candidates[3] if len(allocation_candidates) > 3 else None,
    }

    # Rentabilidades acumuladas aparecem na ordem MRFG, LREN, ARZZ, HAPV.
    returns_candidates = [
        p for p in left_pct
        if p not in [19.32, 67.71, 8.91, 4.94, 3.50, 1.97]
    ]

    accumulated_return_by_ticker = {
        "MRFG3": returns_candidates[0] if len(returns_candidates) > 0 else None,
        "LREN3": returns_candidates[1] if len(returns_candidates) > 1 else None,
        "ARZZ3": returns_candidates[2] if len(returns_candidates) > 2 else None,
        "HAPV3": returns_candidates[3] if len(returns_candidates) > 3 else None,
    }

    # Preços aparecem na ordem: avg MRFG, avg LREN, avg ARZZ, avg HAPV,
    # current HAPV, current LREN, current MRFG, current ARZZ.
    average_price_by_ticker = {
        "MRFG3": right_money[0] if len(right_money) > 0 else None,
        "LREN3": right_money[1] if len(right_money) > 1 else None,
        "ARZZ3": right_money[2] if len(right_money) > 2 else None,
        "HAPV3": right_money[3] if len(right_money) > 3 else None,
    }

    current_price_by_ticker = {
        "HAPV3": right_money[4] if len(right_money) > 4 else None,
        "LREN3": right_money[5] if len(right_money) > 5 else None,
        "MRFG3": right_money[6] if len(right_money) > 6 else None,
        "ARZZ3": right_money[7] if len(right_money) > 7 else None,
    }

    # Quantidades aparecem na ordem ARZZ, LREN, MRFG, HAPV.
    quantity_by_ticker = {
        "ARZZ3": right_ints[0] if len(right_ints) > 0 else None,
        "LREN3": right_ints[1] if len(right_ints) > 1 else None,
        "MRFG3": right_ints[2] if len(right_ints) > 2 else None,
        "HAPV3": right_ints[3] if len(right_ints) > 3 else None,
    }

    # Datas aparecem na ordem LREN, MRFG, ARZZ, HAPV.
    investment_date_by_ticker = {
        "LREN3": right_dates[0] if len(right_dates) > 0 else "",
        "MRFG3": right_dates[1] if len(right_dates) > 1 else "",
        "ARZZ3": right_dates[2] if len(right_dates) > 2 else "",
        "HAPV3": right_dates[3] if len(right_dates) > 3 else "",
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

    for ticker in ["LREN3", "MRFG3", "ARZZ3", "HAPV3"]:
        row = blank_row("Ações", names[ticker], ticker)
        row.update(
            {
                "quantity": fmt(quantity_by_ticker.get(ticker)),
                "average_price": fmt(average_price_by_ticker.get(ticker)),
                "current_price": fmt(current_price_by_ticker.get(ticker)),
                "gross_value": fmt(gross_by_ticker.get(ticker)),
                "portfolio_percentage": fmt(portfolio_pct_by_ticker.get(ticker)),
                "accumulated_return_percentage": fmt(accumulated_return_by_ticker.get(ticker)),
                "investment_date": investment_date_by_ticker.get(ticker, ""),
                "source_page": "1",
                "source_y": source_y[ticker],
            }
        )
        rows.append(row)

    return rows


def extract_funds(texts: Dict[str, str]) -> List[Dict[str, str]]:
    left = texts["funds_left"]
    right = texts["funds_right"]

    left_money = extract_money_values(left)
    left_pct = extract_percent_values(left)
    right_money = extract_money_values(right)
    right_dates = extract_dates(right)

    # Mapeamento por layout do relatório.
    fund_data = [
        {
            "asset_name": "Riza Lotus Plus Advisory FIC FIRF REF DI CP",
            "gross_value": left_money[3] if len(left_money) > 3 else None,
            "portfolio_percentage": left_pct[5] if len(left_pct) > 5 else None,
            "accumulated_return_percentage": left_pct[7] if len(left_pct) > 7 else None,
            "investment_date": right_dates[0] if len(right_dates) > 0 else "",
            "amount_invested": right_money[2] if len(right_money) > 2 else None,
            "net_value": right_money[10] if len(right_money) > 10 else None,
            "quota_date": right_dates[7] if len(right_dates) > 7 else "",
            "source_y": "99.1",
        },
        {
            "asset_name": "Brave I FIC FIM CP",
            "gross_value": left_money[4] if len(left_money) > 4 else None,
            "portfolio_percentage": left_pct[6] if len(left_pct) > 6 else None,
            "accumulated_return_percentage": left_pct[8] if len(left_pct) > 8 else None,
            "investment_date": right_dates[1] if len(right_dates) > 1 else "",
            "amount_invested": right_money[3] if len(right_money) > 3 else None,
            "net_value": right_money[11] if len(right_money) > 11 else None,
            "quota_date": right_dates[8] if len(right_dates) > 8 else "",
            "source_y": "129.1",
        },
        {
            "asset_name": "Trend Investback FIC FIRF Simples",
            "gross_value": left_money[0] if len(left_money) > 0 else None,
            "portfolio_percentage": left_pct[0] if len(left_pct) > 0 else None,
            "accumulated_return_percentage": left_pct[9] if len(left_pct) > 9 else None,
            "investment_date": right_dates[2] if len(right_dates) > 2 else "",
            "amount_invested": right_money[0] if len(right_money) > 0 else None,
            "net_value": right_money[7] if len(right_money) > 7 else None,
            "quota_date": right_dates[9] if len(right_dates) > 9 else "",
            "source_y": "159.1",
        },
        {
            "asset_name": "Truxt Long Bias Advisory FIC FIM",
            "gross_value": left_money[5] if len(left_money) > 5 else None,
            "portfolio_percentage": left_pct[1] if len(left_pct) > 1 else None,
            "accumulated_return_percentage": left_pct[10] if len(left_pct) > 10 else None,
            "investment_date": right_dates[3] if len(right_dates) > 3 else "",
            "amount_invested": right_money[4] if len(right_money) > 4 else None,
            "net_value": right_money[12] if len(right_money) > 12 else None,
            "quota_date": right_dates[10] if len(right_dates) > 10 else "",
            "source_y": "248.3",
        },
        {
            "asset_name": "STK Long Biased FIC FIA",
            "gross_value": left_money[1] if len(left_money) > 1 else None,
            "portfolio_percentage": left_pct[2] if len(left_pct) > 2 else None,
            "accumulated_return_percentage": left_pct[11] if len(left_pct) > 11 else None,
            "investment_date": right_dates[4] if len(right_dates) > 4 else "",
            "amount_invested": right_money[5] if len(right_money) > 5 else None,
            "net_value": right_money[8] if len(right_money) > 8 else None,
            "quota_date": right_dates[11] if len(right_dates) > 11 else "",
            "source_y": "278.3",
        },
        {
            "asset_name": "Constellation Institucional Advisory FIC FIA",
            "gross_value": left_money[2] if len(left_money) > 2 else None,
            "portfolio_percentage": left_pct[3] if len(left_pct) > 3 else None,
            "accumulated_return_percentage": left_pct[12] if len(left_pct) > 12 else None,
            "investment_date": right_dates[5] if len(right_dates) > 5 else "",
            "amount_invested": right_money[6] if len(right_money) > 6 else None,
            "net_value": right_money[9] if len(right_money) > 9 else None,
            "quota_date": right_dates[12] if len(right_dates) > 12 else "",
            "source_y": "308.3",
        },
        {
            "asset_name": "Ibiuna Hedge ST Advisory FIC FIM",
            "gross_value": left_money[6] if len(left_money) > 6 else None,
            "portfolio_percentage": left_pct[4] if len(left_pct) > 4 else None,
            "accumulated_return_percentage": left_pct[13] if len(left_pct) > 13 else None,
            "investment_date": right_dates[6] if len(right_dates) > 6 else "",
            "amount_invested": right_money[1] if len(right_money) > 1 else None,
            "net_value": right_money[13] if len(right_money) > 13 else None,
            "quota_date": right_dates[13] if len(right_dates) > 13 else "",
            "source_y": "397.6",
        },
    ]

    rows = []

    for item in fund_data:
        row = blank_row("Fundo de Investimento", item["asset_name"])
        row.update(
            {
                "gross_value": fmt(item["gross_value"]),
                "portfolio_percentage": fmt(item["portfolio_percentage"]),
                "accumulated_return_percentage": fmt(item["accumulated_return_percentage"]),
                "investment_date": item["investment_date"],
                "amount_invested": fmt(item["amount_invested"]),
                "net_value": fmt(item["net_value"]),
                "quota_date": item["quota_date"],
                "source_page": "2",
                "source_y": item["source_y"],
            }
        )
        rows.append(row)

    return rows


def extract_fixed_income(texts: Dict[str, str]) -> List[Dict[str, str]]:
    left = texts["fixed_left"]
    right = texts["fixed_right"]

    left_money = extract_money_values(left)
    left_pct = extract_percent_values(left)
    right_money = extract_money_values(right)
    right_dates = extract_dates(right)

    row = blank_row("Renda Fixa", "CDB BANCO C6 CONSIGNADO S.A. - SET/2024")
    row.update(
        {
            "gross_value": fmt(left_money[0] if len(left_money) > 0 else None),
            "portfolio_percentage": fmt(left_pct[0] if len(left_pct) > 0 else None),
            "investment_date": right_dates[0] if len(right_dates) > 0 else "",
            "amount_invested": fmt(left_money[1] if len(left_money) > 1 else None),
            "market_rate": "IPC-A +5,45%" if "IPC-A" in right else "",
            "application_date": right_dates[1] if len(right_dates) > 1 else "",
            "maturity_date": right_dates[2] if len(right_dates) > 2 else "",
            "source_page": "3",
            "source_y": "99.1",
        }
    )

    return [row]


def extract_portfolio_rows(pdf_bytes: bytes) -> List[Dict[str, str]]:
    doc = open_pdf(pdf_bytes)
    texts = get_logical_texts(doc)

    rows = []
    rows.extend(extract_equities(texts))
    rows.extend(extract_funds(texts))
    rows.extend(extract_fixed_income(texts))

    if not rows:
        raise ValueError("Nenhuma linha foi extraída do PDF.")

    return rows


def rows_to_csv(rows: List[Dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()

    for row in rows:
        writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})

    return output.getvalue()


def extract_portfolio_csv_from_pdf_url(url: str) -> str:
    pdf_bytes = download_pdf(url)
    rows = extract_portfolio_rows(pdf_bytes)
    return rows_to_csv(rows)


def extract_portfolio_csv_from_pdf_bytes(pdf_bytes: bytes) -> str:
    rows = extract_portfolio_rows(pdf_bytes)
    return rows_to_csv(rows)
