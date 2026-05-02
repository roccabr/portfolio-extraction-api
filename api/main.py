from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, Iterable, List, Tuple

import fitz  # PyMuPDF
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="PDF Portfolio to CSV API", version="1.0.0")

PAGE_PAIRS_1_BASED = [(1, 4), (2, 5), (3, 6)]

CSV_COLUMNS = [
    "categoria",
    "ativo",
    "posicao",
    "alocacao",
    "rentabilidade",
    "data_investimento",
    "preco_medio",
    "ultimo_preco",
    "qtd_total",
    "valor_aplicado",
    "valor_liquido",
    "data_cota",
    "taxa_mercado",
    "data_aplicacao",
    "data_vencimento",
]


@app.get("/")
def root() -> Dict[str, str]:
    return {"ok": "true", "message": "PDF Portfolio API is running"}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/merge-side-by-side")
async def merge_side_by_side(file: UploadFile = File(...)) -> Response:
    """
    Recebe um PDF de 6 páginas e devolve um novo PDF de 3 páginas:
    página 1 + 4, página 2 + 5, página 3 + 6.
    O conteúdo é mantido como PDF vetorial/texto, não como imagem.
    """
    pdf_bytes = await file.read()
    merged_bytes = build_side_by_side_pdf(pdf_bytes)
    return Response(
        content=merged_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="portfolio_lado_a_lado.pdf"'},
    )


@app.post("/extract-csv")
async def extract_csv(file: UploadFile = File(...)) -> Response:
    """
    Recebe o PDF original da carteira XP e devolve CSV.
    A extração usa as coordenadas do PDF, por isso funciona melhor quando o texto é selecionável.
    """
    pdf_bytes = await file.read()
    rows = extract_xp_portfolio_rows(pdf_bytes)
    csv_bytes = rows_to_csv_bytes(rows)
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="portfolio.csv"'},
    )


@app.post("/pdf-to-csv")
async def pdf_to_csv(file: UploadFile = File(...)) -> Response:
    """
    Endpoint combinado para o n8n: recebe o PDF original e devolve o CSV final.
    Internamente, segue a mesma lógica do layout 1+4, 2+5, 3+6.
    """
    pdf_bytes = await file.read()
    rows = extract_xp_portfolio_rows(pdf_bytes)
    csv_bytes = rows_to_csv_bytes(rows)
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="portfolio.csv"'},
    )


@app.post("/extract-json")
async def extract_json(file: UploadFile = File(...)) -> JSONResponse:
    """Útil para debug no n8n: retorna os mesmos dados em JSON."""
    pdf_bytes = await file.read()
    rows = extract_xp_portfolio_rows(pdf_bytes)
    return JSONResponse(content={"rows": rows, "count": len(rows)})


def build_side_by_side_pdf(pdf_bytes: bytes) -> bytes:
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(src) < 6:
        raise HTTPException(status_code=400, detail="O PDF precisa ter pelo menos 6 páginas.")

    out = fitz.open()
    for left_1, right_1 in PAGE_PAIRS_1_BASED:
        left = src[left_1 - 1]
        right = src[right_1 - 1]

        # Mantém a escala original. Como as páginas têm o mesmo tamanho,
        # a página final fica com o dobro da largura.
        width = left.rect.width + right.rect.width
        height = max(left.rect.height, right.rect.height)
        new_page = out.new_page(width=width, height=height)

        left_rect = fitz.Rect(0, 0, left.rect.width, left.rect.height)
        right_rect = fitz.Rect(left.rect.width, 0, width, right.rect.height)

        new_page.show_pdf_page(left_rect, src, left_1 - 1)
        new_page.show_pdf_page(right_rect, src, right_1 - 1)

    return out.tobytes(garbage=4, deflate=True)


def extract_xp_portfolio_rows(pdf_bytes: bytes) -> List[Dict[str, str]]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) < 6:
        raise HTTPException(status_code=400, detail="O PDF precisa ter pelo menos 6 páginas.")

    rows: List[Dict[str, str]] = []
    rows += extract_equities(doc[0], doc[3])
    rows += extract_funds(doc[1], doc[4])
    rows += extract_fixed_income(doc[2], doc[5])
    return rows


def extract_equities(left_page: fitz.Page, right_page: fitz.Page) -> List[Dict[str, str]]:
    left_rows = extract_left_rows(left_page, category="Ações", y_min=300, y_max=460)
    right_rows = extract_right_rows(
        right_page,
        y_min=300,
        y_max=460,
        schema="equities",
    )
    return merge_by_order(left_rows, right_rows)


def extract_funds(left_page: fitz.Page, right_page: fitz.Page) -> List[Dict[str, str]]:
    left_rows = extract_left_rows(left_page, category="Fundos de Investimentos", y_min=80, y_max=430)
    right_rows = extract_right_rows(
        right_page,
        y_min=80,
        y_max=430,
        schema="funds",
    )
    return merge_by_order(left_rows, right_rows)


def extract_fixed_income(left_page: fitz.Page, right_page: fitz.Page) -> List[Dict[str, str]]:
    left_rows = extract_fixed_left_rows(left_page, y_min=80, y_max=140)
    right_rows = extract_right_rows(
        right_page,
        y_min=80,
        y_max=140,
        schema="fixed_income",
    )
    return merge_by_order(left_rows, right_rows)


def page_words(page: fitz.Page) -> List[Dict[str, Any]]:
    words = []
    for w in page.get_text("words"):
        x0, y0, x1, y1, text, *_ = w
        words.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text})
    return sorted(words, key=lambda item: (item["y0"], item["x0"]))


def group_lines(words: Iterable[Dict[str, Any]], tolerance: float = 4.0) -> List[List[Dict[str, Any]]]:
    lines: List[List[Dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["y0"], item["x0"])):
        if not lines:
            lines.append([word])
            continue
        current_y = sum(w["y0"] for w in lines[-1]) / len(lines[-1])
        if abs(word["y0"] - current_y) <= tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda item: item["x0"])
    return lines


def text_in_range(line: List[Dict[str, Any]], x_min: float, x_max: float) -> str:
    parts = [w["text"] for w in line if x_min <= w["x0"] < x_max]
    return clean_text(" ".join(parts))


def line_y(line: List[Dict[str, Any]]) -> float:
    return sum(w["y0"] for w in line) / len(line)


def extract_left_rows(page: fitz.Page, category: str, y_min: float, y_max: float) -> List[Dict[str, str]]:
    lines = group_lines([w for w in page_words(page) if y_min <= w["y0"] <= y_max])
    rows: List[Dict[str, str]] = []

    for line in lines:
        name = text_in_range(line, 0, 250)
        position = text_in_range(line, 250, 380)
        allocation = text_in_range(line, 380, 500)
        profitability = text_in_range(line, 500, 650)

        if not name or not looks_like_money(position) or not looks_like_percent(allocation):
            continue

        rows.append(empty_row() | {
            "categoria": category,
            "ativo": name,
            "posicao": normalize_money(position),
            "alocacao": allocation,
            "rentabilidade": profitability,
            "_y": f"{line_y(line):.2f}",
        })
    return rows


def extract_fixed_left_rows(page: fitz.Page, y_min: float, y_max: float) -> List[Dict[str, str]]:
    lines = group_lines([w for w in page_words(page) if y_min <= w["y0"] <= y_max])
    rows: List[Dict[str, str]] = []

    for line in lines:
        name = text_in_range(line, 0, 250)
        market_position = text_in_range(line, 250, 380)
        allocation = text_in_range(line, 380, 500)
        applied_value = text_in_range(line, 500, 650)

        if not name or not looks_like_money(market_position) or not looks_like_percent(allocation):
            continue

        rows.append(empty_row() | {
            "categoria": "Renda Fixa",
            "ativo": name,
            "posicao": normalize_money(market_position),
            "alocacao": allocation,
            "valor_aplicado": normalize_money(applied_value),
            "_y": f"{line_y(line):.2f}",
        })
    return rows


def extract_right_rows(page: fitz.Page, y_min: float, y_max: float, schema: str) -> List[Dict[str, str]]:
    lines = group_lines([w for w in page_words(page) if y_min <= w["y0"] <= y_max])
    rows: List[Dict[str, str]] = []

    for line in lines:
        first_col = text_in_range(line, 0, 165)
        if not looks_like_date(first_col):
            continue

        if schema == "equities":
            rows.append(empty_row() | {
                "data_investimento": first_col,
                "preco_medio": normalize_money(text_in_range(line, 165, 280)),
                "ultimo_preco": normalize_money(text_in_range(line, 300, 420)),
                "qtd_total": text_in_range(line, 430, 530),
                "_y": f"{line_y(line):.2f}",
            })
        elif schema == "funds":
            rows.append(empty_row() | {
                "data_investimento": first_col,
                "valor_aplicado": normalize_money(text_in_range(line, 165, 290)),
                "valor_liquido": normalize_money(text_in_range(line, 300, 430)),
                "data_cota": text_in_range(line, 430, 560),
                "_y": f"{line_y(line):.2f}",
            })
        elif schema == "fixed_income":
            rows.append(empty_row() | {
                "data_investimento": first_col,
                "taxa_mercado": text_in_range(line, 165, 300),
                "data_aplicacao": text_in_range(line, 300, 430),
                "data_vencimento": text_in_range(line, 430, 560),
                "_y": f"{line_y(line):.2f}",
            })
        else:
            raise ValueError(f"Schema não suportado: {schema}")

    return rows


def merge_by_order(left_rows: List[Dict[str, str]], right_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    max_len = max(len(left_rows), len(right_rows))

    for idx in range(max_len):
        base = empty_row()
        if idx < len(left_rows):
            base.update(left_rows[idx])
        if idx < len(right_rows):
            for key, value in right_rows[idx].items():
                if key == "_y":
                    continue
                if value:
                    base[key] = value
        base.pop("_y", None)
        merged.append(base)

    return merged


def empty_row() -> Dict[str, str]:
    return {column: "" for column in CSV_COLUMNS}


def rows_to_csv_bytes(rows: List[Dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value


def normalize_money(value: str) -> str:
    value = clean_text(value)
    value = value.replace("R$ ", "R$")
    return value


def looks_like_money(value: str) -> bool:
    return "R$" in value and bool(re.search(r"\d", value))


def looks_like_percent(value: str) -> bool:
    return "%" in value and bool(re.search(r"\d", value))


def looks_like_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{2}/\d{2}/\d{4}", clean_text(value)))
