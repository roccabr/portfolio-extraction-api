import csv
import io
import re
from typing import Any, Dict, List, Optional

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

    # Exemplos:
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


def get_words(page: fitz.Page) -> List[Dict[str, Any]]:
    words = []

    for raw_word in page.get_text("words"):
        x0, y0, x1, y1, text, block_no, line_no, word_no = raw_word[:8]

        text = str(text).strip()
        if not text:
            continue

        words.append(
            {
                "x0": float(x0),
                "y0": float(y0),
                "x1": float(x1),
                "y1": float(y1),
                "text": text,
                "block_no": block_no,
                "line_no": line_no,
                "word_no": word_no,
            }
        )

    return words


def text_at_y(
    words: List[Dict[str, Any]],
    y: float,
    x_min: float,
    x_max: float,
    tolerance: float = 4.0,
) -> str:
    selected = [
        word
        for word in words
        if abs(word["y0"] - y) <= tolerance
        and x_min <= word["x0"] <= x_max
    ]

    selected = sorted(selected, key=lambda word: word["x0"])
    return clean_text(" ".join(word["text"] for word in selected))


def number_at_y(
    words: List[Dict[str, Any]],
    y: float,
    x_min: float,
    x_max: float,
    tolerance: float = 4.0,
) -> Optional[float]:
    return parse_number(text_at_y(words, y, x_min, x_max, tolerance))


def date_at_y(
    words: List[Dict[str, Any]],
    y: float,
    x_min: float,
    x_max: float,
    tolerance: float = 4.0,
) -> str:
    text = text_at_y(words, y, x_min, x_max, tolerance)
    match = re.search(r"\d{2}/\d{2}/\d{4}", text)
    return match.group(0) if match else ""


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
    Página 1: ticker, valor, % alocação, rentabilidade.
    Página 4: data, preço médio, último preço, quantidade.
    """

    left_words = get_words(doc.load_page(0))
    right_words = get_words(doc.load_page(3))

    rows_config = [
        {
            "y": 326.3,
            "ticker": "LREN3",
            "asset_name": "Lojas Renner",
        },
        {
            "y": 356.3,
            "ticker": "MRFG3",
            "asset_name": "Marfrig",
        },
        {
            "y": 386.3,
            "ticker": "ARZZ3",
            "asset_name": "Arezzo",
        },
        {
            "y": 416.3,
            "ticker": "HAPV3",
            "asset_name": "Hapvida",
        },
    ]

    rows = []

    for config in rows_config:
        y = config["y"]

        row = blank_row("Ações", config["asset_name"], config["ticker"])
        row.update(
            {
                "gross_value": fmt_number(number_at_y(left_words, y, 260, 330)),
                "portfolio_percentage": fmt_number(number_at_y(left_words, y, 390, 450)),
                "accumulated_return_percentage": fmt_number(number_at_y(left_words, y, 520, 600)),
                "investment_date": date_at_y(right_words, y, 45, 115),
                "average_price": fmt_number(number_at_y(right_words, y, 180, 230)),
                "current_price": fmt_number(number_at_y(right_words, y, 310, 365)),
                "quantity": fmt_number(number_at_y(right_words, y, 440, 485)),
                "source_page": "1+4",
                "source_y": str(y),
            }
        )

        rows.append(row)

    return rows


def extract_funds(doc: fitz.Document) -> List[Dict[str, str]]:
    """
    Página 2: nome do fundo, valor líquido/posição, % alocação, rentabilidade.
    Página 5: data, valor aplicado, valor líquido, data da cota.
    """

    left_words = get_words(doc.load_page(1))
    right_words = get_words(doc.load_page(4))

    rows_config = [
        {
            "y": 99.1,
            "asset_name": "Riza Lotus Plus Advisory FIC FIRF REF DI CP",
        },
        {
            "y": 129.1,
            "asset_name": "Brave I FIC FIM CP",
        },
        {
            "y": 159.1,
            "asset_name": "Trend Investback FIC FIRF Simples",
        },
        {
            "y": 248.3,
            "asset_name": "Truxt Long Bias Advisory FIC FIM",
        },
        {
            "y": 278.3,
            "asset_name": "STK Long Biased FIC FIA",
        },
        {
            "y": 308.3,
            "asset_name": "Constellation Institucional Advisory FIC FIA",
        },
        {
            "y": 397.6,
            "asset_name": "Ibiuna Hedge ST Advisory FIC FIM",
        },
    ]

    rows = []

    for config in rows_config:
        y = config["y"]

        # Nome lido do PDF quando possível; fallback para config.
        extracted_name = text_at_y(left_words, y, 45, 245)
        asset_name = extracted_name or config["asset_name"]

        row = blank_row("Fundo de Investimento", asset_name)
        row.update(
            {
                "gross_value": fmt_number(number_at_y(left_words, y, 260, 330)),
                "portfolio_percentage": fmt_number(number_at_y(left_words, y, 390, 450)),
                "accumulated_return_percentage": fmt_number(number_at_y(left_words, y, 520, 600)),
                "investment_date": date_at_y(right_words, y, 45, 115),
                "amount_invested": fmt_number(number_at_y(right_words, y, 180, 260)),
                "net_value": fmt_number(number_at_y(right_words, y, 310, 385)),
                "quota_date": date_at_y(right_words, y, 440, 520),
                "source_page": "2+5",
                "source_y": str(y),
            }
        )

        rows.append(row)

    return rows


def extract_fixed_income(doc: fitz.Document) -> List[Dict[str, str]]:
    """
    Página 3: nome, posição a mercado, % alocação, valor aplicado.
    Página 6: data, taxa a mercado, data aplicação, vencimento.
    """

    left_words = get_words(doc.load_page(2))
    right_words = get_words(doc.load_page(5))

    y = 99.1

    extracted_name = text_at_y(left_words, y, 45, 240)
    asset_name = extracted_name or "CDB BANCO C6 CONSIGNADO S.A. - SET/2024"

    row = blank_row("Renda Fixa", asset_name)
    row.update(
        {
            "gross_value": fmt_number(number_at_y(left_words, y, 260, 330)),
            "portfolio_percentage": fmt_number(number_at_y(left_words, y, 390, 450)),
            "amount_invested": fmt_number(number_at_y(left_words, y, 520, 600)),
            "investment_date": date_at_y(right_words, y, 45, 115),
            "market_rate": text_at_y(right_words, y, 180, 270),
            "application_date": date_at_y(right_words, y, 310, 390),
            "maturity_date": date_at_y(right_words, y, 440, 540),
            "source_page": "3+6",
            "source_y": str(y),
        }
    )

    return [row]


def extract_portfolio_rows(pdf_bytes: bytes) -> List[Dict[str, str]]:
    doc = open_pdf(pdf_bytes)

    rows = []
    rows.extend(extract_equities(doc))
    rows.extend(extract_funds(doc))
    rows.extend(extract_fixed_income(doc))

    if not rows:
        raise ValueError("Nenhuma linha foi extraída do PDF.")

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
