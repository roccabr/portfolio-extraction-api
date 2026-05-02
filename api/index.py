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
# 2) EXTRAIR PDF PARA CSV
# ===============================

def clean_text(value):
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def normalize_spaces(value):
    return re.sub(r"\s+", " ", clean_text(value))


def extract_tables_from_pdf(input_bytes: bytes):
    rows = []

    with pdfplumber.open(BytesIO(input_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()

            for table_index, table in enumerate(tables, start=1):
                if not table:
                    continue

                for row in table:
                    cleaned_row = [normalize_spaces(cell) for cell in row]

                    if not any(cleaned_row):
                        continue

                    rows.append({
                        "page": page_number,
                        "table": table_index,
                        "col_1": cleaned_row[0] if len(cleaned_row) > 0 else "",
                        "col_2": cleaned_row[1] if len(cleaned_row) > 1 else "",
                        "col_3": cleaned_row[2] if len(cleaned_row) > 2 else "",
                        "col_4": cleaned_row[3] if len(cleaned_row) > 3 else "",
                        "col_5": cleaned_row[4] if len(cleaned_row) > 4 else "",
                        "col_6": cleaned_row[5] if len(cleaned_row) > 5 else "",
                        "col_7": cleaned_row[6] if len(cleaned_row) > 6 else "",
                        "col_8": cleaned_row[7] if len(cleaned_row) > 7 else "",
                        "col_9": cleaned_row[8] if len(cleaned_row) > 8 else "",
                        "col_10": cleaned_row[9] if len(cleaned_row) > 9 else "",
                    })

    return rows


def rows_to_csv(rows):
    output = StringIO()

    fieldnames = [
        "page",
        "table",
        "col_1",
        "col_2",
        "col_3",
        "col_4",
        "col_5",
        "col_6",
        "col_7",
        "col_8",
        "col_9",
        "col_10",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for row in rows:
        writer.writerow(row)

    return output.getvalue()


@app.post("/extract-portfolio-csv")
async def extract_portfolio_csv(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")

    input_bytes = await file.read()

    try:
        rows = extract_tables_from_pdf(input_bytes)

        if not rows:
            raise HTTPException(
                status_code=400,
                detail="Nenhuma tabela foi encontrada no PDF."
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
