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


EQUITY_NAME_MAP = {
    "LREN3": "Lojas Renner",
    "MRFG3": "Marfrig",
    "MBRF3": "Marfrig",
    "ARZZ3": "Arezzo",
    "AZZA3": "Arezzo",
    "HAPV3": "Hapvida",
}


def download_pdf(url: str) -> bytes:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


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

    # Casos:
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


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def get_words(page: fitz.Page) -> List[Dict[str, Any]]:
    words = []
    for raw in page.get_text("words"):
        x0, y0, x1, y1, text, block_no, line_no, word_no = raw[:8]
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


def words_near_y(
    words: List[Dict[str, Any]],
    y: float,
    x_min: float,
    x_max: float,
    tolerance: float = 4.0,
) -> List[Dict[str, Any]]:
    result = [
        w for w in words
        if abs(w["y0"] - y) <= tolerance and x_min <= w["x0"] <= x_max
    ]
    return sorted(result, key=lambda w: w["x0"])


def text_near_y(
    words: List[Dict[str, Any]],
    y: float,
    x_min: float,
    x_max: float,
    tolerance: float = 4.0,
) -> str:
    selected = words_near_y(words, y, x_min, x_max, tolerance)
    return clean_text(" ".join(w["text"] for w in selected))


def money_near_y(
    words: List[Dict[str, Any]],
    y: float,
    x_min: float,
    x_max: float,
    tolerance: float = 4.0,
) -> Optional[float]:
    text = text_near_y(words, y, x_min, x_max, tolerance)
    return parse_number(text)


def percent_near_y(
    words: List[Dict[str, Any]],
    y: float,
    x_min: float,
    x_max: float,
    tolerance: float = 4.0,
) -> Optional[float]:
    text = text_near_y(words, y, x_min, x_max, tolerance)
    return parse_number(text)


def date_near_y(
    words: List[Dict[str, Any]],
    y: float,
    x_min: float,
    x_max: float,
    tolerance: float = 4.0,
) -> str:
    text = text_near_y(words, y, x_min, x_max, tolerance)
    match = re.search(r"\d{2}/\d{2}/\d{4}", text)
    return match.group(0) if match else ""


def open_pdf(pdf_bytes: bytes) -> fitz.Document:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.page_count < 3:
        raise ValueError(f"PDF inválido. Esperado pelo menos 3 páginas, recebido {doc.page_count}.")

    return doc


def get_split_pages(doc: fitz.Document):
    """
    Layout esperado:
    PDF original com 6 páginas:
      Página 1 + Página 4 = Ações
      Página 2 + Página 5 = Fundos
      Página 3 + Página 6 = Renda Fixa

    Se vier um PDF rebuilt com 3 páginas, usamos páginas 1, 2 e 3 diretamente.
    """
    if doc.page_count >= 6:
        return {
            "equities_left": doc.load_page(0),
            "equities_right": doc.load_page(3),
            "funds_left": doc.load_page(1),
            "funds_right": doc.load_page(4),
            "fixed_income_left": doc.load_page(2),
            "fixed_income_right": doc.load_page(5),
        }

    if doc.page_count == 3:
        return {
            "equities_left": doc.load_page(0),
            "equities_right": doc.load_page(0),
            "funds_left": doc.load_page(1),
            "funds_right": doc.load_page(1),
            "fixed_income_left": doc.load_page(2),
            "fixed_income_right": doc.load_page(2),
        }

    raise ValueError(f"PDF com número de páginas não suportado: {doc.page_count}.")


def extract_equities(doc: fitz.Document) -> List[Dict[str, Any]]:
    pages = get_split_pages(doc)

    left_words = get_words(pages["equities_left"])
    right_words = get_words(pages["equities_right"])

    ticker_words = [
        w for w in left_words
        if w["text"] in EQUITY_NAME_MAP and 40 <= w["x0"] <= 90
    ]

    ticker_words = sorted(ticker_words, key=lambda w: w["y0"])

    rows = []

    for w in ticker_words:
        ticker = w["text"]
        y = w["y0"]

        row = {
            "asset_class": "Ações",
            "asset_name": EQUITY_NAME_MAP.get(ticker, ticker),
            "ticker": ticker,
            "quantity": fmt(parse_number(text_near_y(right_words, y, 440, 475))),
            "average_price": fmt(money_near_y(right_words, y, 180, 225)),
            "current_price": fmt(money_near_y(right_words, y, 310, 355)),
            "gross_value": fmt(money_near_y(left_words, y, 255, 315)),
            "portfolio_percentage": fmt(percent_near_y(left_words, y, 390, 425)),
            "accumulated_return_percentage": fmt(percent_near_y(left_words, y, 520, 560)),
            "investment_date": date_near_y(right_words, y, 45, 105),
            "amount_invested": "",
            "net_value": "",
            "market_rate": "",
            "application_date": "",
            "maturity_date": "",
            "quota_date": "",
            "source_page": "1",
            "source_y": str(round(y, 1)),
        }

        rows.append(row)

    return rows


def fund_name_near_y(words: List[Dict[str, Any]], y: float) -> str:
    return text_near_y(words, y, 45, 250)


def extract_funds(doc: fitz.Document) -> List[Dict[str, Any]]:
    pages = get_split_pages(doc)

    left_words = get_words(pages["funds_left"])
    right_words = get_words(pages["funds_right"])

    fund_starters = [
        "Riza",
        "Brave",
        "Trend",
        "Truxt",
        "STK",
        "Constellation",
        "Ibiuna",
    ]

    starter_words = [
        w for w in left_words
        if w["text"] in fund_starters and 40 <= w["x0"] <= 90
    ]

    starter_words = sorted(starter_words, key=lambda w: w["y0"])

    rows = []
    seen = set()

    for w in starter_words:
        y = w["y0"]
        name = fund_name_near_y(left_words, y)

        if not name or name in seen:
            continue

        seen.add(name)

        row = {
            "asset_class": "Fundo de Investimento",
            "asset_name": name,
            "ticker": "",
            "quantity": "",
            "average_price": "",
            "current_price": "",
            "gross_value": fmt(money_near_y(left_words, y, 255, 315)),
            "portfolio_percentage": fmt(percent_near_y(left_words, y, 390, 425)),
            "accumulated_return_percentage": fmt(percent_near_y(left_words, y, 520, 560)),
            "investment_date": date_near_y(right_words, y, 45, 105),
            "amount_invested": fmt(money_near_y(right_words, y, 180, 250)),
            "net_value": fmt(money_near_y(right_words, y, 310, 370)),
            "market_rate": "",
            "application_date": "",
            "maturity_date": "",
            "quota_date": date_near_y(right_words, y, 440, 500),
            "source_page": "2",
            "source_y": str(round(y, 1)),
        }

        rows.append(row)

    return rows


def extract_fixed_income(doc: fitz.Document) -> List[Dict[str, Any]]:
    pages = get_split_pages(doc)

    left_words = get_words(pages["fixed_income_left"])
    right_words = get_words(pages["fixed_income_right"])

    cdb_words = [
        w for w in left_words
        if w["text"].upper() in ["CDB", "TESOURO", "LCA", "LCI"] and 40 <= w["x0"] <= 90
    ]

    cdb_words = sorted(cdb_words, key=lambda w: w["y0"])

    rows = []

    for w in cdb_words:
        y = w["y0"]
        name = text_near_y(left_words, y, 45, 230)

        row = {
            "asset_class": "Renda Fixa",
            "asset_name": name,
            "ticker": "",
            "quantity": "",
            "average_price": "",
            "current_price": "",
            "gross_value": fmt(money_near_y(left_words, y, 255, 315)),
            "portfolio_percentage": fmt(percent_near_y(left_words, y, 390, 425)),
            "accumulated_return_percentage": "",
            "investment_date": date_near_y(right_words, y, 45, 105),
            "amount_invested": fmt(money_near_y(left_words, y, 520, 580)),
            "net_value": "",
            "market_rate": text_near_y(right_words, y, 180, 260),
            "application_date": date_near_y(right_words, y, 310, 370),
            "maturity_date": date_near_y(right_words, y, 440, 500),
            "quota_date": "",
            "source_page": "3",
            "source_y": str(round(y, 1)),
        }

        rows.append(row)

    return rows


def extract_portfolio_rows(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    doc = open_pdf(pdf_bytes)

    rows = []
    rows.extend(extract_equities(doc))
    rows.extend(extract_funds(doc))
    rows.extend(extract_fixed_income(doc))

    if not rows:
        raise ValueError("Nenhuma linha de carteira foi extraída do PDF.")

    return rows


def rows_to_csv(rows: List[Dict[str, Any]]) -> str:
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
