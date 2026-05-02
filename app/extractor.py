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


def get_page_text(doc: fitz.Document, page_index: int) -> str:
    return doc.load_page(page_index).get_text("text")


def get_lines(text: str) -> List[str]:
    return [
        clean_text(line)
        for line in text.splitlines()
        if clean_text(line)
    ]


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
    lines = get_lines(text)
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


def extract_equities(page_1: str, page_4: str) -> List[Dict[str, str]]:
    """
    Página 1:
    - Tickers
    - Posição financeira
    - % Alocação
    - Rentabilidade acumulada

    Página 4:
    - Data do investimento
    - Preço médio
    - Último preço
    - Quantidade
    """

    money_1 = extract_money_values(page_1)
    pct_1 = extract_percent_values(page_1)

    money_4 = extract_money_values(page_4)
    dates_4 = extract_dates(page_4)
    ints_4 = extract_standalone_ints(page_4)

    # Debug defensivo.
    # Se cair aqui, a API está lendo um PDF diferente ou o texto veio diferente.
    if len(money_1) < 5:
        raise ValueError(f"Ações: money_1 insuficiente. Extraído: {money_1}")

    if len(pct_1) < 10:
        raise ValueError(f"Ações: pct_1 insuficiente. Extraído: {pct_1}")

    if len(money_4) < 8:
        raise ValueError(f"Ações: money_4 insuficiente. Extraído: {money_4}")

    if len(dates_4) < 4:
        raise ValueError(f"Ações: dates_4 insuficiente. Extraído: {dates_4}")

    if len(ints_4) < 4:
        raise ValueError(f"Ações: ints_4 insuficiente. Extraído: {ints_4}")

    return [
        make_row(
            asset_class="Ações",
            asset_name="Lojas Renner",
            ticker="LREN3",
            quantity=ints_4[1],
            average_price=money_4[1],
            current_price=money_4[5],
            gross_value=money_1[2],
            portfolio_percentage=pct_1[2],
            accumulated_return_percentage=pct_1[7],
            investment_date=dates_4[0],
            source_page="1+4",
        ),
        make_row(
            asset_class="Ações",
            asset_name="Marfrig",
            ticker="MRFG3",
            quantity=ints_4[2],
            average_price=money_4[0],
            current_price=money_4[6],
            gross_value=money_1[3],
            portfolio_percentage=pct_1[3],
            accumulated_return_percentage=pct_1[6],
            investment_date=dates_4[1],
            source_page="1+4",
        ),
        make_row(
            asset_class="Ações",
            asset_name="Arezzo",
            ticker="ARZZ3",
            quantity=ints_4[0],
            average_price=money_4[2],
            current_price=money_4[7],
            gross_value=money_1[4],
            portfolio_percentage=pct_1[4],
            accumulated_return_percentage=pct_1[8],
            investment_date=dates_4[2],
            source_page="1+4",
        ),
        make_row(
            asset_class="Ações",
            asset_name="Hapvida",
            ticker="HAPV3",
            quantity=ints_4[3],
            average_price=money_4[3],
            current_price=money_4[4],
            gross_value=money_1[1],
            portfolio_percentage=pct_1[5],
            accumulated_return_percentage=pct_1[9],
            investment_date=dates_4[3],
            source_page="1+4",
        ),
    ]


def extract_funds(page_2: str, page_5: str) -> List[Dict[str, str]]:
    """
    Página 2:
    - Nome do fundo
    - Posição
    - % Alocação
    - Rentabilidade

    Página 5:
    - Data do investimento
    - Valor aplicado
    - Valor líquido
    - Data da cota
    """

    money_2 = extract_money_values(page_2)
    pct_2 = extract_percent_values(page_2)

    money_5 = extract_money_values(page_5)
    dates_5 = extract_dates(page_5)

    if len(money_2) < 7:
        raise ValueError(f"Fundos: money_2 insuficiente. Extraído: {money_2}")

    if len(pct_2) < 15:
        raise ValueError(f"Fundos: pct_2 insuficiente. Extraído: {pct_2}")

    if len(money_5) < 14:
        raise ValueError(f"Fundos: money_5 insuficiente. Extraído: {money_5}")

    if len(dates_5) < 14:
        raise ValueError(f"Fundos: dates_5 insuficiente. Extraído: {dates_5}")

    return [
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Riza Lotus Plus Advisory FIC FIRF REF DI CP",
            gross_value=money_2[3],
            portfolio_percentage=pct_2[6],
            accumulated_return_percentage=pct_2[8],
            investment_date=dates_5[0],
            amount_invested=money_5[2],
            net_value=money_5[10],
            quota_date=dates_5[7],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Brave I FIC FIM CP",
            gross_value=money_2[4],
            portfolio_percentage=pct_2[7],
            accumulated_return_percentage=pct_2[9],
            investment_date=dates_5[1],
            amount_invested=money_5[3],
            net_value=money_5[11],
            quota_date=dates_5[8],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Trend Investback FIC FIRF Simples",
            gross_value=money_2[0],
            portfolio_percentage=pct_2[1],
            accumulated_return_percentage=pct_2[10],
            investment_date=dates_5[2],
            amount_invested=money_5[0],
            net_value=money_5[7],
            quota_date=dates_5[9],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Truxt Long Bias Advisory FIC FIM",
            gross_value=money_2[5],
            portfolio_percentage=pct_2[2],
            accumulated_return_percentage=pct_2[12],
            investment_date=dates_5[3],
            amount_invested=money_5[4],
            net_value=money_5[12],
            quota_date=dates_5[10],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="STK Long Biased FIC FIA",
            gross_value=money_2[1],
            portfolio_percentage=pct_2[3],
            accumulated_return_percentage=pct_2[13],
            investment_date=dates_5[4],
            amount_invested=money_5[5],
            net_value=money_5[8],
            quota_date=dates_5[11],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Constellation Institucional Advisory FIC FIA",
            gross_value=money_2[2],
            portfolio_percentage=pct_2[4],
            accumulated_return_percentage=pct_2[14],
            investment_date=dates_5[5],
            amount_invested=money_5[6],
            net_value=money_5[9],
            quota_date=dates_5[12],
            source_page="2+5",
        ),
        make_row(
            asset_class="Fundo de Investimento",
            asset_name="Ibiuna Hedge ST Advisory FIC FIM",
            gross_value=money_2[6],
            portfolio_percentage=pct_2[5],
            accumulated_return_percentage=pct_2[11],
            investment_date=dates_5[6],
            amount_invested=money_5[1],
            net_value=money_5[13],
            quota_date=dates_5[13],
            source_page="2+5",
        ),
    ]


def extract_fixed_income(page_3: str, page_6: str) -> List[Dict[str, str]]:
    """
    Página 3:
    - Nome
    - Posição a mercado
    - % Alocação
    - Valor aplicado

    Página 6:
    - Data do investimento
    - Taxa a mercado
    - Data aplicação
    - Data vencimento
    """

    money_3 = extract_money_values(page_3)
    pct_3 = extract_percent_values(page_3)
    dates_6 = extract_dates(page_6)

    if len(money_3) < 2:
        raise ValueError(f"Renda Fixa: money_3 insuficiente. Extraído: {money_3}")

    if len(pct_3) < 1:
        raise ValueError(f"Renda Fixa: pct_3 insuficiente. Extraído: {pct_3}")

    if len(dates_6) < 3:
        raise ValueError(f"Renda Fixa: dates_6 insuficiente. Extraído: {dates_6}")

    market_rate_match = re.search(r"IPC-A\s*\+\s*\d+,\d+%", page_6)
    market_rate = market_rate_match.group(0) if market_rate_match else ""

    return [
        make_row(
            asset_class="Renda Fixa",
            asset_name="CDB BANCO C6 CONSIGNADO S.A. - SET/2024",
            gross_value=money_3[0],
            portfolio_percentage=pct_3[0],
            amount_invested=money_3[1],
            investment_date=dates_6[0],
            market_rate=market_rate,
            application_date=dates_6[1],
            maturity_date=dates_6[2],
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
        ("Lojas Renner", "portfolio_percentage"),
        ("Lojas Renner", "accumulated_return_percentage"),
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

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.page_count != 6:
        raise ValueError(
            f"PDF deve ter 6 páginas para este extrator XP. Recebido: {doc.page_count}"
        )

    page_1 = get_page_text(doc, 0)
    page_2 = get_page_text(doc, 1)
    page_3 = get_page_text(doc, 2)
    page_4 = get_page_text(doc, 3)
    page_5 = get_page_text(doc, 4)
    page_6 = get_page_text(doc, 5)

    rows = []
    rows.extend(extract_equities(page_1, page_4))
    rows.extend(extract_funds(page_2, page_5))
    rows.extend(extract_fixed_income(page_3, page_6))

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
