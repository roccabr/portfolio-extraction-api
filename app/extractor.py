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
]


def download_pdf(url: str) -> bytes:
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    if not response.content.startswith(b"%PDF"):
        preview = response.content[:300].decode("utf-8", errors="ignore")
        raise ValueError(f"A URL não retornou um PDF válido. Preview: {preview}")

    return response.content


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_number(value: Optional[str]) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    text = (
        text
        .replace("R$", "")
        .replace("%", "")
        .replace("\u00a0", " ")
        .strip()
    )

    text = re.sub(r"\s+", "", text)

    if not text:
        return ""

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
        number = float(text)

        if number.is_integer():
            return str(int(number))

        return str(round(number, 6)).rstrip("0").rstrip(".")
    except Exception:
        return ""


def extract_money_values(text: str) -> List[str]:
    matches = re.findall(r"R\$\s*[\d\.\,]+", text)
    return [parse_number(match) for match in matches]


def extract_percent_values(text: str) -> List[str]:
    matches = re.findall(r"-?\d{1,3}(?:[\.,]\d+)?\s*%", text)
    return [parse_number(match) for match in matches]


def extract_dates(text: str) -> List[str]:
    return re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)


def extract_standalone_ints(text: str) -> List[str]:
    lines = [
        clean_text(line)
        for line in text.splitlines()
        if clean_text(line)
    ]

    values = []

    for line in lines:
        if re.fullmatch(r"\d{2,6}", line):
            number = int(line)

            if number not in [2021, 2022, 2023, 2024, 2025, 2026]:
                values.append(str(number))

    return values


def make_row(
    asset_class: str,
    asset_name: str,
    ticker: str = "",
    quantity: str = "",
    average_price: str = "",
    current_price: str = "",
    gross_value: str = "",
    portfolio_percentage: str = "",
    accumulated_return_percentage: str = "",
    investment_date: str = "",
    amount_invested: str = "",
    net_value: str = "",
    market_rate: str = "",
    application_date: str = "",
    maturity_date: str = "",
    quota_date: str = "",
    source_page: str = "",
) -> Dict[str, str]:
    return {
        "asset_class": asset_class,
        "asset_name": asset_name,
        "ticker": ticker,
        "quantity": quantity,
        "average_price": average_price,
        "current_price": current_price,
        "gross_value": gross_value,
        "portfolio_percentage": portfolio_percentage,
        "accumulated_return_percentage": accumulated_return_percentage,
        "investment_date": investment_date,
        "amount_invested": amount_invested,
        "net_value": net_value,
        "market_rate": market_rate,
        "application_date": application_date,
        "maturity_date": maturity_date,
        "quota_date": quota_date,
        "source_page": source_page,
    }


def rebuild_pdf_side_by_side(pdf_bytes: bytes) -> bytes:
    """
    Recebe PDF original de 6 páginas e cria um PDF reconstruído de 3 páginas:
    - Página 1 + Página 4
    - Página 2 + Página 5
    - Página 3 + Página 6

    Importante:
    Não renderiza imagem.
    Usa show_pdf_page para preservar texto vetorial sempre que possível.
    """

    src = fitz.open(stream=pdf_bytes, filetype="pdf")

    if src.page_count != 6:
        raise ValueError(
            f"PDF deve ter 6 páginas para reconstrução. Recebido: {src.page_count}"
        )

    dst = fitz.open()

    pairs = [
        (0, 3),
        (1, 4),
        (2, 5),
    ]

    for left_index, right_index in pairs:
        left_page = src.load_page(left_index)
        right_page = src.load_page(right_index)

        width = left_page.rect.width + right_page.rect.width
        height = max(left_page.rect.height, right_page.rect.height)

        new_page = dst.new_page(width=width, height=height)

        left_rect = fitz.Rect(
            0,
            0,
            left_page.rect.width,
            left_page.rect.height,
        )

        right_rect = fitz.Rect(
            left_page.rect.width,
            0,
            left_page.rect.width + right_page.rect.width,
            right_page.rect.height,
        )

        new_page.show_pdf_page(left_rect, src, left_index)
        new_page.show_pdf_page(right_rect, src, right_index)

    return dst.tobytes()


def get_rebuilt_page_texts(pdf_bytes: bytes) -> List[str]:
    rebuilt_bytes = rebuild_pdf_side_by_side(pdf_bytes)
    rebuilt_doc = fitz.open(stream=rebuilt_bytes, filetype="pdf")

    texts = []

    for index in range(rebuilt_doc.page_count):
        text = rebuilt_doc.load_page(index).get_text("text")
        texts.append(text)

    if len(texts) != 3:
        raise ValueError(f"PDF reconstruído deveria ter 3 páginas. Recebido: {len(texts)}")

    return texts


def extract_equities(rebuilt_page_1: str) -> List[Dict[str, str]]:
    money = extract_money_values(rebuilt_page_1)
    pct = extract_percent_values(rebuilt_page_1)
    dates = extract_dates(rebuilt_page_1)
    ints = extract_standalone_ints(rebuilt_page_1)

    if len(money) < 15:
        raise ValueError(f"Ações: money insuficiente no rebuilt. Extraído: {money}")

    if len(pct) < 10:
        raise ValueError(f"Ações: pct insuficiente no rebuilt. Extraído: {pct}")

    if len(dates) < 4:
        raise ValueError(f"Ações: dates insuficiente no rebuilt. Extraído: {dates}")

    if len(ints) < 4:
        raise ValueError(f"Ações: ints insuficiente no rebuilt. Extraído: {ints}")

    # No rebuilt_page_1, os valores esperados são:
    # money:
    # 0 total wealth
    # 1 HAPV gross
    # 2 LREN gross
    # 3 MRFG gross
    # 4 ARZZ gross
    # 5 total invested
    # 6 cash
    # 7 avg MRFG
    # 8 avg LREN
    # 9 avg ARZZ
    # 10 avg HAPV
    # 11 current HAPV
    # 12 current LREN
    # 13 current MRFG
    # 14 current ARZZ
    #
    # pct:
    # 0 ações class
    # 1 fundos class
    # 2 LREN allocation
    # 3 MRFG allocation
    # 4 ARZZ allocation
    # 5 HAPV allocation
    # 6 MRFG return
    # 7 LREN return
    # 8 ARZZ return
    # 9 HAPV return
    #
    # dates:
    # 0 LREN
    # 1 MRFG
    # 2 ARZZ
    # 3 HAPV
    #
    # ints:
    # 0 advisor code may not appear because A7699 is alphanumeric
    # expected quantities: 193, 1642, 1504, 1547

    # Remove possíveis números que não sejam quantidades.
    quantity_ints = [
        value for value in ints
        if value not in ["792854"]
    ]

    if len(quantity_ints) < 4:
        raise ValueError(f"Ações: quantidades insuficientes. Extraído: {quantity_ints}")

    return [
        make_row(
            asset_class="Ações",
            asset_name="Lojas Renner",
            ticker="LREN3",
            quantity=quantity_ints[1],
            average_price=money[8],
            current_price=money[12],
            gross_value=money[2],
            portfolio_percentage=pct[2],
            accumulated_return_percentage=pct[7],
            investment_date=dates[0],
            source_page="1+4",
        ),
        make_row(
            asset_class="Ações",
            asset_name="Marfrig",
            ticker="MRFG3",
            quantity=quantity_ints[2],
            average_price=money[7],
            current_price=money[13],
            gross_value=money[3],
            portfolio_percentage=pct[3],
            accumulated_return_percentage=pct[6],
            investment_date=dates[1],
            source_page="1+4",
        ),
        make_row(
            asset_class="Ações",
            asset_name="Arezzo",
            ticker="ARZZ3",
            quantity=quantity_ints[0],
            average_price=money[9],
            current_price=money[14],
            gross_value=money[4],
            portfolio_percentage=pct[4],
            accumulated_return_percentage=pct[8],
            investment_date=dates[2],
            source_page="1+4",
        ),
        make_row(
            asset_class="Ações",
            asset_name="Hapvida",
            ticker="HAPV3",
            quantity=quantity_ints[3],
            average_price=money[10],
            current_price=money[11],
            gross_value=money[1],
            portfolio_percentage=pct[5],
            accumulated_return_percentage=pct[9],
            investment_date=dates[3],
            source_page="1+4",
        ),
    ]


def extract_funds(rebuilt_page_2: str) -> List[Dict[str, str]]:
    money = extract_money_values(rebuilt_page_2)
    pct = extract_percent_values(rebuilt_page_2)
    dates = extract_dates(rebuilt_page_2)

    if len(money) < 22:
        raise ValueError(f"Fundos: money insuficiente no rebuilt. Extraído: {money}")

    if len(pct) < 15:
        raise ValueError(f"Fundos: pct insuficiente no rebuilt. Extraído: {pct}")

    if len(dates) < 14:
        raise ValueError(f"Fundos: dates insuficiente no rebuilt. Extraído: {dates}")

    # No rebuilt_page_2, conforme layout:
    # money:
    # 0 Trend gross
    # 1 STK gross
    # 2 Const gross
    # 3 Riza gross
    # 4 Brave gross
    # 5 Truxt gross
    # 6 Ibiuna gross
    # 7 Trend applied
    # 8 Ibiuna applied
    # 9 Riza applied
    # 10 Brave applied
    # 11 Truxt applied
    # 12 STK applied
    # 13 Const applied
    # 14 Trend net
    # 15 STK net
    # 16 Const net
    # 17 Riza net
    # 18 Brave net
    # 19 Truxt net
    # 20 Ibiuna net
    # 21 CDB gross
    #
    # pct:
    # 0 renda fixa class
    # 1 Trend allocation
    # 2 Truxt allocation
    # 3 STK allocation
    # 4 Const allocation
    # 5 Ibiuna allocation
    # 6 Riza allocation
    # 7 Brave allocation
    # 8 Riza return
    # 9 Brave return
    # 10 Trend return
    # 11 Ibiuna return
    # 12 Truxt return
    # 13 STK return
    # 14 Const return

    return [
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Riza Lotus Plus Advisory FIC FIRF REF DI CP",
            gross_value=money[3],
            portfolio_percentage=pct[6],
            accumulated_return_percentage=pct[8],
            investment_date=dates[0],
            amount_invested=money[9],
            net_value=money[17],
            quota_date=dates[7],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Brave I FIC FIM CP",
            gross_value=money[4],
            portfolio_percentage=pct[7],
            accumulated_return_percentage=pct[9],
            investment_date=dates[1],
            amount_invested=money[10],
            net_value=money[18],
            quota_date=dates[8],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Trend Investback FIC FIRF Simples",
            gross_value=money[0],
            portfolio_percentage=pct[1],
            accumulated_return_percentage=pct[10],
            investment_date=dates[2],
            amount_invested=money[7],
            net_value=money[14],
            quota_date=dates[9],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Truxt Long Bias Advisory FIC FIM",
            gross_value=money[5],
            portfolio_percentage=pct[2],
            accumulated_return_percentage=pct[12],
            investment_date=dates[3],
            amount_invested=money[11],
            net_value=money[19],
            quota_date=dates[10],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="STK Long Biased FIC FIA",
            gross_value=money[1],
            portfolio_percentage=pct[3],
            accumulated_return_percentage=pct[13],
            investment_date=dates[4],
            amount_invested=money[12],
            net_value=money[15],
            quota_date=dates[11],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Constellation Institucional Advisory FIC FIA",
            gross_value=money[2],
            portfolio_percentage=pct[4],
            accumulated_return_percentage=pct[14],
            investment_date=dates[5],
            amount_invested=money[13],
            net_value=money[16],
            quota_date=dates[12],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Ibiuna Hedge ST Advisory FIC FIM",
            gross_value=money[6],
            portfolio_percentage=pct[5],
            accumulated_return_percentage=pct[11],
            investment_date=dates[6],
            amount_invested=money[8],
            net_value=money[20],
            quota_date=dates[13],
            source_page="2+5",
        ),
    ]


def extract_fixed_income(rebuilt_page_3: str) -> List[Dict[str, str]]:
    money = extract_money_values(rebuilt_page_3)
    pct = extract_percent_values(rebuilt_page_3)
    dates = extract_dates(rebuilt_page_3)

    if len(money) < 2:
        raise ValueError(f"Renda Fixa: money insuficiente no rebuilt. Extraído: {money}")

    if len(pct) < 1:
        raise ValueError(f"Renda Fixa: pct insuficiente no rebuilt. Extraído: {pct}")

    if len(dates) < 3:
        raise ValueError(f"Renda Fixa: dates insuficiente no rebuilt. Extraído: {dates}")

    market_rate_match = re.search(r"IPC-A\s*\+\s*\d+,\d+%", rebuilt_page_3)
    market_rate = market_rate_match.group(0) if market_rate_match else ""

    return [
        make_row(
            asset_class="Renda Fixa",
            asset_name="CDB BANCO C6 CONSIGNADO S.A. - SET/2024",
            gross_value=money[0],
            portfolio_percentage=pct[0],
            amount_invested=money[1],
            investment_date=dates[0],
            market_rate=market_rate,
            application_date=dates[1],
            maturity_date=dates[2],
            source_page="3+6",
        )
    ]


def validate_rows(rows: List[Dict[str, str]]) -> None:
    if len(rows) != 12:
        raise ValueError(f"Esperadas 12 linhas, extraídas {len(rows)}.")

    required_fields = [
        ("Lojas Renner", "quantity"),
        ("Lojas Renner", "average_price"),
        ("Lojas Renner", "current_price"),
        ("Lojas Renner", "gross_value"),
        ("Brave I FIC FIM CP", "gross_value"),
        ("CDB BANCO C6 CONSIGNADO S.A. - SET/2024", "gross_value"),
    ]

    for asset_name, field in required_fields:
        row = next((item for item in rows if item["asset_name"] == asset_name), None)

        if not row:
            raise ValueError(f"Ativo esperado não encontrado: {asset_name}")

        if not row.get(field):
            raise ValueError(f"Campo obrigatório vazio: {asset_name}.{field}")


def extract_portfolio_rows(pdf_bytes: bytes) -> List[Dict[str, str]]:
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Arquivo recebido não parece ser um PDF válido.")

    rebuilt_texts = get_rebuilt_page_texts(pdf_bytes)

    rows = []
    rows.extend(extract_equities(rebuilt_texts[0]))
    rows.extend(extract_funds(rebuilt_texts[1]))
    rows.extend(extract_fixed_income(rebuilt_texts[2]))

    validate_rows(rows)

    return rows


def rows_to_csv(rows: List[Dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()

    for row in rows:
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})

    return output.getvalue()


def extract_portfolio_csv_from_pdf_bytes(pdf_bytes: bytes) -> str:
    rows = extract_portfolio_rows(pdf_bytes)
    return rows_to_csv(rows)


def extract_portfolio_csv_from_pdf_url(url: str) -> str:
    pdf_bytes = download_pdf(url)
    return extract_portfolio_csv_from_pdf_bytes(pdf_bytes)
