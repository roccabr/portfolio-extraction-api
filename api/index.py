from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject
from io import BytesIO, StringIO
import pdfplumber
import csv
import re


app = FastAPI(title="Portfolio Extraction API")


@app.get("/")
def healthcheck():
    return {
        "status": "ok",
        "message": "Portfolio Extraction API is running"
    }


# ===============================
# 1) COMBINAR PDF LADO A LADO
# ===============================

def safe_page_size(page):
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    return width, height


def combine_pdf_bytes(input_bytes: bytes) -> bytes:
    try:
        reader = PdfReader(BytesIO(input_bytes))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Não foi possível ler o PDF: {str(e)}"
        )

    total_pages = len(reader.pages)

    if total_pages < 2:
        raise HTTPException(
            status_code=400,
            detail="O PDF precisa ter pelo menos 2 páginas."
        )

    if total_pages % 2 != 0:
        raise HTTPException(
            status_code=400,
            detail=f"O PDF tem {total_pages} páginas. O número de páginas precisa ser par."
        )

    half = total_pages // 2
    writer = PdfWriter()

    for i in range(half):
        left_page = reader.pages[i]
        right_page = reader.pages[i + half]

        try:
            left_page.transfer_rotation_to_content()
        except Exception:
            pass

        try:
            right_page.transfer_rotation_to_content()
        except Exception:
            pass

        left_width, left_height = safe_page_size(left_page)
        right_width, right_height = safe_page_size(right_page)

        new_width = left_width + right_width
        new_height = max(left_height, right_height)

        new_page = PageObject.create_blank_page(
            width=new_width,
            height=new_height
        )

        left_y = (new_height - left_height) / 2
        right_y = (new_height - right_height) / 2

        new_page.merge_transformed_page(
            left_page,
            Transformation().translate(tx=0, ty=left_y)
        )

        new_page.merge_transformed_page(
            right_page,
            Transformation().translate(tx=left_width, ty=right_y)
        )

        writer.add_page(new_page)

    output = BytesIO()
    writer.write(output)
    output.seek(0)

    return output.read()


@app.post("/combine-side-by-side")
async def combine_side_by_side(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")

    input_bytes = await file.read()
    output_bytes = combine_pdf_bytes(input_bytes)

    return Response(
        content=output_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="combined-side-by-side.pdf"'
        }
    )


# ===============================
# 2) EXTRAIR PDF PARA CSV ORGANIZADO
# ===============================

import csv
import re
from io import StringIO


CSV_FIELDS = [
    "categoria",
    "ativo",
    "posicao",
    "alocacao_pct",
    "rentabilidade_pct",
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


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def get_text_blocks_from_pdf(input_bytes: bytes):
    """
    Extrai o texto bruto do PDF combinado.
    Como o PDF já está lado a lado, o texto costuma vir em blocos grandes.
    Depois fazemos parsing por padrões de produtos financeiros.
    """
    full_text = ""

    with pdfplumber.open(BytesIO(input_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            full_text += "\n" + text

    return clean_text(full_text)


def parse_money_percent_rows(text, categoria):
    """
    Parser genérico para linhas com:
    ativo + posição + % alocação + rentabilidade

    Exemplo:
    LREN3 R$27,812.04 8.91% -41,7%
    """
    rows = []

    pattern = re.compile(
        r"(?P<ativo>[A-Za-z0-9À-ÿ\.\-\&\s]+?)\s+"
        r"(?P<posicao>R\$\s?[\d\.,]+)\s+"
        r"(?P<alocacao>[\d\.,]+%)\s+"
        r"(?P<rentabilidade>[-]?\d+,\d+%|[-]?\d+\.\d+%)"
    )

    for match in pattern.finditer(text):
        ativo = clean_text(match.group("ativo"))

        # Remove possíveis títulos grudados antes do ativo
        ativo = re.sub(r"^.*?(Rentabilidade\s*\(?%?\)?\s*)", "", ativo).strip()
        ativo = re.sub(r"^.*?(Rentabilidade\s*)", "", ativo).strip()

        # Evita capturar frases muito grandes como ativo
        if len(ativo) > 120:
            ativo = " ".join(ativo.split()[-12:])

        rows.append({
            "categoria": categoria,
            "ativo": ativo,
            "posicao": clean_text(match.group("posicao")),
            "alocacao_pct": clean_text(match.group("alocacao")),
            "rentabilidade_pct": clean_text(match.group("rentabilidade")),
            "data_investimento": "",
            "preco_medio": "",
            "ultimo_preco": "",
            "qtd_total": "",
            "valor_aplicado": "",
            "valor_liquido": "",
            "data_cota": "",
            "taxa_mercado": "",
            "data_aplicacao": "",
            "data_vencimento": "",
        })

    return rows


def extract_dates_and_stock_details(text):
    """
    Extrai detalhes de ações:
    data_investimento, preço_médio, último_preço e quantidade.

    Exemplo:
    22/04/2021 R$ 29,05 R$ 16,94 1642
    """
    pattern = re.compile(
        r"(?P<data>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<preco_medio>R\$\s?[\d\.,]+)\s+"
        r"(?P<ultimo_preco>R\$\s?[\d\.,]+)\s+"
        r"(?P<qtd>\d+)"
    )

    return [
        {
            "data_investimento": clean_text(m.group("data")),
            "preco_medio": clean_text(m.group("preco_medio")),
            "ultimo_preco": clean_text(m.group("ultimo_preco")),
            "qtd_total": clean_text(m.group("qtd")),
        }
        for m in pattern.finditer(text)
    ]


def extract_fund_details(text):
    """
    Extrai detalhes de fundos:
    data_investimento, valor_aplicado, valor_liquido e data_cota.

    Exemplo:
    22/04/2021 R$ 83.267,36 R$ 95.254,02 04/04/2024
    """
    pattern = re.compile(
        r"(?P<data>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<valor_aplicado>R\$\s?[\d\.,]+)\s+"
        r"(?P<valor_liquido>R\$\s?[\d\.,]+)\s+"
        r"(?P<data_cota>\d{2}/\d{2}/\d{4})"
    )

    return [
        {
            "data_investimento": clean_text(m.group("data")),
            "valor_aplicado": clean_text(m.group("valor_aplicado")),
            "valor_liquido": clean_text(m.group("valor_liquido")),
            "data_cota": clean_text(m.group("data_cota")),
        }
        for m in pattern.finditer(text)
    ]


def extract_fixed_income_rows(text):
    """
    Extrai renda fixa.

    Exemplo:
    CDB BANCO C6 CONSIGNADO S.A. - SET/2024 R$40,478.75 12.97% R$ 30.000,00
    09/11/2023 IPC-A +5,45% 06/09/2021 05/09/2024
    """
    rows = []

    asset_pattern = re.compile(
        r"(?P<ativo>CDB\s+.+?)\s+"
        r"(?P<posicao>R\$\s?[\d\.,]+)\s+"
        r"(?P<alocacao>[\d\.,]+%)\s+"
        r"(?P<valor_aplicado>R\$\s?[\d\.,]+)"
    )

    detail_pattern = re.compile(
        r"(?P<data_investimento>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<taxa>[^0-9]{0,20}[A-Z\-]+\s?[+\-]?\d+,\d+%)\s+"
        r"(?P<data_aplicacao>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<data_vencimento>\d{2}/\d{2}/\d{4})"
    )

    assets = list(asset_pattern.finditer(text))
    details = list(detail_pattern.finditer(text))

    for i, asset in enumerate(assets):
        detail = details[i] if i < len(details) else None

        rows.append({
            "categoria": "Renda Fixa",
            "ativo": clean_text(asset.group("ativo")),
            "posicao": clean_text(asset.group("posicao")),
            "alocacao_pct": clean_text(asset.group("alocacao")),
            "rentabilidade_pct": "",
            "data_investimento": clean_text(detail.group("data_investimento")) if detail else "",
            "preco_medio": "",
            "ultimo_preco": "",
            "qtd_total": "",
            "valor_aplicado": clean_text(asset.group("valor_aplicado")),
            "valor_liquido": "",
            "data_cota": "",
            "taxa_mercado": clean_text(detail.group("taxa")) if detail else "",
            "data_aplicacao": clean_text(detail.group("data_aplicacao")) if detail else "",
            "data_vencimento": clean_text(detail.group("data_vencimento")) if detail else "",
        })

    return rows


def merge_rows_with_details(rows, details, detail_type):
    """
    Junta os detalhes extraídos por ordem.
    Para esse PDF, a ordem dos ativos na esquerda acompanha a ordem dos detalhes na direita.
    """
    final_rows = []

    for i, row in enumerate(rows):
        new_row = row.copy()

        if i < len(details):
            detail = details[i]

            if detail_type == "stocks":
                new_row["data_investimento"] = detail.get("data_investimento", "")
                new_row["preco_medio"] = detail.get("preco_medio", "")
                new_row["ultimo_preco"] = detail.get("ultimo_preco", "")
                new_row["qtd_total"] = detail.get("qtd_total", "")

            if detail_type == "funds":
                new_row["data_investimento"] = detail.get("data_investimento", "")
                new_row["valor_aplicado"] = detail.get("valor_aplicado", "")
                new_row["valor_liquido"] = detail.get("valor_liquido", "")
                new_row["data_cota"] = detail.get("data_cota", "")

        final_rows.append(new_row)

    return final_rows


def split_text_sections(text):
    """
    Divide o texto em seções principais.
    """
    acoes_text = ""
    fundos_text = ""
    renda_fixa_text = ""

    if "Ações" in text and "Fundos de Investimentos" in text:
        acoes_text = text.split("Ações", 1)[1].split("Fundos de Investimentos", 1)[0]

    if "Fundos de Investimentos" in text and "Renda Fixa" in text:
        fundos_text = text.split("Fundos de Investimentos", 1)[1].split("Renda Fixa", 1)[0]

    if "Renda Fixa" in text:
        renda_fixa_text = text.split("Renda Fixa", 1)[1]

    return acoes_text, fundos_text, renda_fixa_text


def extract_portfolio_rows(input_bytes: bytes):
    text = get_text_blocks_from_pdf(input_bytes)

    acoes_text, fundos_text, renda_fixa_text = split_text_sections(text)

    # Ações
    stock_rows = parse_money_percent_rows(acoes_text, "Ações")
    stock_details = extract_dates_and_stock_details(acoes_text)
    stock_rows = merge_rows_with_details(stock_rows, stock_details, "stocks")

    # Fundos
    fund_rows = parse_money_percent_rows(fundos_text, "Fundos de Investimentos")
    fund_details = extract_fund_details(fundos_text)
    fund_rows = merge_rows_with_details(fund_rows, fund_details, "funds")

    # Renda fixa
    fixed_income_rows = extract_fixed_income_rows(renda_fixa_text)

    rows = stock_rows + fund_rows + fixed_income_rows

    return rows


def rows_to_csv(rows):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()

    for row in rows:
        writer.writerow({
            field: row.get(field, "")
            for field in CSV_FIELDS
        })

    return output.getvalue()


@app.post("/extract-portfolio-csv")
async def extract_portfolio_csv(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")

    input_bytes = await file.read()

    try:
        rows = extract_portfolio_rows(input_bytes)

        if not rows:
            raise HTTPException(
                status_code=400,
                detail="Nenhum ativo foi encontrado no PDF."
            )

        csv_content = rows_to_csv(rows)

        return Response(
            content=csv_content.encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="portfolio-extracted.csv"'
            }
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao extrair dados do PDF: {str(e)}"
        )
