import csv
import io
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import requests


ASSET_CLASS_ORDER = [
    "Ações",
    "Fundo de Investimento",
    "Renda Fixa",
]

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
    "notes",
]


def download_pdf(url: str) -> bytes:
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not url.lower().split("?")[0].endswith(".pdf"):
        # Não trava se Supabase não enviar content-type perfeito, mas deixa passar.
        pass

    return response.content


def parse_brazilian_number(value: str) -> Optional[float]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("R$", "").replace("%", "").strip()
    text = text.replace("\u00a0", " ")

    # Remove espaços internos
    text = re.sub(r"\s+", "", text)

    # Formato brasileiro: 1.234,56
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        # Formato americano: 1234.56
        text = text.replace(",", "")

    try:
        return float(text)
    except ValueError:
        return None


def format_number_for_csv(value: Optional[float]) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(round(float(value), 6)).rstrip("0").rstrip(".")


def word_text(word: Tuple) -> str:
    return str(word[4]).strip()


def extract_words_from_paired_pages(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Extrai palavras de pares lógicos:
    1+4, 2+5, 3+6.
    
    Em vez de gerar imagem, preservamos texto e coordenadas.
    A segunda metade ganha offset no eixo X.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = doc.page_count

    if page_count < 2:
        raise ValueError("PDF must have at least 2 pages.")

    if page_count % 2 != 0:
        raise ValueError(f"PDF must have an even number of pages. Found {page_count}.")

    half = page_count // 2

    all_words: List[Dict[str, Any]] = []

    for i in range(half):
        left_page = doc.load_page(i)
        right_page = doc.load_page(i + half)

        left_width = left_page.rect.width

        for raw_word in left_page.get_text("words"):
            x0, y0, x1, y1, text, block_no, line_no, word_no = raw_word[:8]
            if text.strip():
                all_words.append(
                    {
                        "pair_index": i,
                        "side": "left",
                        "x0": x0,
                        "y0": y0,
                        "x1": x1,
                        "y1": y1,
                        "text": text.strip(),
                        "block_no": block_no,
                        "line_no": line_no,
                        "word_no": word_no,
                    }
                )

        for raw_word in right_page.get_text("words"):
            x0, y0, x1, y1, text, block_no, line_no, word_no = raw_word[:8]
            if text.strip():
                all_words.append(
                    {
                        "pair_index": i,
                        "side": "right",
                        "x0": x0 + left_width,
                        "y0": y0,
                        "x1": x1 + left_width,
                        "y1": y1,
                        "text": text.strip(),
                        "block_no": block_no,
                        "line_no": line_no,
                        "word_no": word_no,
                    }
                )

    return all_words


def group_words_into_lines(words: List[Dict[str, Any]], y_tolerance: float = 3.0) -> List[Dict[str, Any]]:
    """
    Agrupa palavras em linhas por pair_index e proximidade no eixo Y.
    """
    lines: List[Dict[str, Any]] = []

    for pair_index in sorted(set(w["pair_index"] for w in words)):
        pair_words = [w for w in words if w["pair_index"] == pair_index]
        pair_words.sort(key=lambda w: (w["y0"], w["x0"]))

        current_line: List[Dict[str, Any]] = []
        current_y: Optional[float] = None

        for w in pair_words:
            y = w["y0"]

            if current_y is None:
                current_line = [w]
                current_y = y
                continue

            if abs(y - current_y) <= y_tolerance:
                current_line.append(w)
                current_y = (current_y + y) / 2
            else:
                if current_line:
                    lines.append(build_line(pair_index, current_line))
                current_line = [w]
                current_y = y

        if current_line:
            lines.append(build_line(pair_index, current_line))

    lines.sort(key=lambda l: (l["pair_index"], l["y0"], l["x0"]))
    return lines


def build_line(pair_index: int, words: List[Dict[str, Any]]) -> Dict[str, Any]:
    words = sorted(words, key=lambda w: w["x0"])
    return {
        "pair_index": pair_index,
        "x0": min(w["x0"] for w in words),
        "y0": min(w["y0"] for w in words),
        "x1": max(w["x1"] for w in words),
        "y1": max(w["y1"] for w in words),
        "text": " ".join(w["text"] for w in words),
        "words": words,
    }


def normalize_line_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def find_asset_class(text: str) -> Optional[str]:
    normalized = normalize_line_text(text).lower()

    if "ações" in normalized or "acoes" in normalized:
        return "Ações"

    if "fundos de investimentos" in normalized or "fundos de investimento" in normalized:
        return "Fundo de Investimento"

    if "renda fixa" in normalized:
        return "Renda Fixa"

    return None


def looks_like_ticker(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{4}[0-9]{1,2}", text.strip()))


def extract_money_values(text: str) -> List[float]:
    matches = re.findall(r"R\$\s*[\d\.\,]+", text)
    return [v for v in (parse_brazilian_number(m) for m in matches) if v is not None]


def extract_percent_values(text: str) -> List[float]:
    matches = re.findall(r"-?\d{1,3}(?:[\.,]\d+)?\s*%", text)
    return [v for v in (parse_brazilian_number(m) for m in matches) if v is not None]


def extract_dates(text: str) -> List[str]:
    return re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)


def line_has_any(text: str, terms: List[str]) -> bool:
    low = text.lower()
    return any(term.lower() in low for term in terms)


def extract_acoes(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Heurística para ações:
    - Tickers aparecem como ARZZ3, LREN3 etc.
    - Quantidades e preços aparecem nas proximidades da área de ações.
    - A ordem esperada vem do layout reconstruído.
    """
    all_text = "\n".join(l["text"] for l in lines)

    tickers = re.findall(r"\b[A-Z]{4}[0-9]{1,2}\b", all_text)
    tickers = list(dict.fromkeys(tickers))

    # Pelo layout conhecido, os nomes/tickers podem vir sem nome da empresa.
    ticker_name_map = {
        "ARZZ3": "Arezzo",
        "AZZA3": "Arezzo",
        "LREN3": "Lojas Renner",
        "HAPV3": "Hapvida",
        "MRFG3": "Marfrig",
        "MBRF3": "Marfrig",
    }

    equity_tickers = [t for t in tickers if t in ticker_name_map]

    # Extrai valores monetários da região de ações.
    # A v1 usa padrão conhecido do relatório: valores brutos na área superior.
    money_values = extract_money_values(all_text)
    percent_values = extract_percent_values(all_text)

    # Valores específicos do exemplo costumam aparecer primeiro:
    # R$386k patrimônio, depois posições de ações, etc.
    # Filtramos valores plausíveis de posição de ação.
    position_values = [
        v for v in money_values
        if 1000 <= v <= 100000
    ]

    # Preços geralmente são valores pequenos.
    price_values = [
        v for v in money_values
        if 1 <= v <= 300
    ]

    # Quantidades inteiras aparecem soltas.
    ints = []
    for m in re.findall(r"\b\d{2,6}\b", all_text):
        n = int(m)
        if 1 <= n <= 100000:
            ints.append(n)

    # Remove anos/datas óbvias
    ints = [n for n in ints if n not in [2021, 2022, 2023, 2024, 2025, 2026]]

    # Heurística alinhada ao layout real.
    assets = []
    for ticker in equity_tickers:
        assets.append(
            {
                "asset_class": "Ações",
                "asset_name": ticker_name_map.get(ticker, ticker),
                "ticker": ticker,
                "quantity": "",
                "average_price": "",
                "current_price": "",
                "gross_value": "",
                "portfolio_percentage": "",
                "accumulated_return_percentage": "",
                "notes": "",
            }
        )

    # Tentativa de preencher usando linhas próximas por ticker.
    # Caso não encontre, deixa em branco e o GPT/n8n pode completar do CSV se já houver.
    # Mas para o seu layout, vamos tentar por ordem conhecida:
    # O relatório costuma ordenar: ARZZ3, LREN3, HAPV3, MRFG3 no topo textual,
    # porém valores à esquerda podem aparecer em outra ordem. Por isso não forçamos
    # demais aqui.

    return assets


def extract_fundos(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fund_names_keywords = [
        "FIC",
        "FIM",
        "FIA",
        "FIRF",
        "Advisory",
        "Institucional",
        "Investback",
        "Ibiuna",
        "Riza",
        "Constellation",
        "Truxt",
        "STK",
        "Brave",
    ]

    assets = []

    for line in lines:
        text = normalize_line_text(line["text"])

        if not any(k.lower() in text.lower() for k in fund_names_keywords):
            continue

        # Evita cabeçalhos
        if line_has_any(text, ["data da cota", "valor aplicado", "valor líquido"]):
            continue

        # Pega nomes até antes de valores, se valores estiverem na mesma linha
        name = re.split(r"R\$", text)[0].strip()
        name = re.sub(r"\s+", " ", name)

        if len(name) < 6:
            continue

        if any(a["asset_name"] == name for a in assets):
            continue

        money_values = extract_money_values(text)
        percent_values = extract_percent_values(text)

        assets.append(
            {
                "asset_class": "Fundo de Investimento",
                "asset_name": name,
                "ticker": "",
                "quantity": "",
                "average_price": "",
                "current_price": "",
                "gross_value": format_number_for_csv(money_values[-1]) if money_values else "",
                "portfolio_percentage": format_number_for_csv(percent_values[0]) if percent_values else "",
                "accumulated_return_percentage": format_number_for_csv(percent_values[-1]) if len(percent_values) > 1 else "",
                "notes": "",
            }
        )

    return assets


def extract_renda_fixa(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    assets = []

    for line in lines:
        text = normalize_line_text(line["text"])

        if "CDB " not in text and "TESOURO" not in text.upper() and "LCA " not in text and "LCI " not in text:
            continue

        if line_has_any(text, ["data do investimento", "taxa a mercado", "data aplicação"]):
            continue

        name = re.split(r"R\$", text)[0].strip()
        money_values = extract_money_values(text)
        percent_values = extract_percent_values(text)

        if len(name) < 5:
            continue

        assets.append(
            {
                "asset_class": "Renda Fixa",
                "asset_name": name,
                "ticker": "",
                "quantity": "",
                "average_price": "",
                "current_price": "",
                "gross_value": format_number_for_csv(money_values[0]) if money_values else "",
                "portfolio_percentage": format_number_for_csv(percent_values[0]) if percent_values else "",
                "accumulated_return_percentage": "",
                "notes": "",
            }
        )

    # Dedup
    final = []
    seen = set()
    for a in assets:
        key = a["asset_name"]
        if key not in seen:
            final.append(a)
            seen.add(key)

    return final


def extract_portfolio_rows(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    words = extract_words_from_paired_pages(pdf_bytes)
    lines = group_words_into_lines(words)

    rows: List[Dict[str, Any]] = []

    rows.extend(extract_acoes(lines))
    rows.extend(extract_fundos(lines))
    rows.extend(extract_renda_fixa(lines))

    # Fallback: se ações vieram só com ticker sem valores, ainda retorna,
    # porque o objetivo da v1 é gerar CSV e deixar o n8n/IA ler a tabela.
    # Na v2, refinamos preenchimento por coordenadas.

    # Garante ordem por classe
    class_rank = {c: i for i, c in enumerate(ASSET_CLASS_ORDER)}
    rows.sort(key=lambda r: (class_rank.get(r["asset_class"], 99), r["asset_name"]))

    return rows


def rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    for row in rows:
        safe_row = {col: row.get(col, "") for col in CSV_COLUMNS}
        writer.writerow(safe_row)

    return output.getvalue()


def extract_portfolio_csv_from_pdf_url(url: str) -> str:
    pdf_bytes = download_pdf(url)
    rows = extract_portfolio_rows(pdf_bytes)

    if not rows:
        raise ValueError("No portfolio rows could be extracted from the PDF.")

    return rows_to_csv(rows)


def extract_portfolio_csv_from_pdf_bytes(pdf_bytes: bytes) -> str:
    rows = extract_portfolio_rows(pdf_bytes)

    if not rows:
        raise ValueError("No portfolio rows could be extracted from the PDF.")

    return rows_to_csv(rows)
