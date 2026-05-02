from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject
from io import BytesIO
import pdfplumber
import csv
import re
from io import StringIO


app = FastAPI(title="Portfolio Extraction API")


import pdfplumber
import csv
import re
from io import StringIO


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

                    # Ignora linhas totalmente vazias
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
