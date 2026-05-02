from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from typing import Optional
import fitz

from app.extractor import (
    extract_portfolio_csv_from_pdf_bytes,
    extract_portfolio_csv_from_pdf_url,
    extract_money_values,
    extract_percent_values,
    extract_dates,
    extract_standalone_ints,
)

app = FastAPI(
    title="Portfolio Extraction API",
    description="API para extrair CSV de carteira XP a partir de PDF.",
    version="0.1.0",
)


class ExtractPortfolioRequest(BaseModel):
    report_id: Optional[str] = None
    portfolio_pdf_url: str


@app.get("/")
def root():
    return {
        "ok": True,
        "service": "portfolio-extraction-api",
        "message": "API online"
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "portfolio-extraction-api",
        "version": "0.1.0"
    }


@app.get("/debug-version")
def debug_version():
    return {
        "ok": True,
        "version": "DEBUG_XP_EXTRACTOR_2026_05_02",
        "message": "Deploy novo ativo."
    }


@app.post("/extract-portfolio-csv")
def extract_portfolio_csv(payload: ExtractPortfolioRequest):
    try:
        csv_content = extract_portfolio_csv_from_pdf_url(
            str(payload.portfolio_pdf_url)
        )

        filename = "portfolio_extracted.csv"
        if payload.report_id:
            filename = f"{payload.report_id}_portfolio_extracted.csv"

        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "error": str(error),
            },
        )


@app.post("/extract-portfolio-csv/upload")
async def extract_portfolio_csv_upload(file: UploadFile = File(...)):
    try:
        pdf_bytes = await file.read()
        csv_content = extract_portfolio_csv_from_pdf_bytes(pdf_bytes)

        filename = "portfolio_extracted.csv"

        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "error": str(error),
            },
        )


@app.post("/debug-upload")
async def debug_upload(file: UploadFile = File(...)):
    try:
        pdf_bytes = await file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        page_1 = doc.load_page(0).get_text("text")
        page_4 = doc.load_page(3).get_text("text")

        csv_result = extract_portfolio_csv_from_pdf_bytes(pdf_bytes)

        return {
            "ok": True,
            "page_count": doc.page_count,
            "page_1_preview": page_1[:1200],
            "page_4_preview": page_4[:1200],
            "money_1": extract_money_values(page_1),
            "pct_1": extract_percent_values(page_1),
            "money_4": extract_money_values(page_4),
            "dates_4": extract_dates(page_4),
            "ints_4": extract_standalone_ints(page_4),
            "csv_preview": csv_result[:2000]
        }

    except Exception as error:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(error)
            }
        )
