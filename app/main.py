from fastapi import File, UploadFile
from fastapi.responses import JSONResponse
import fitz

from app.extractor import (
    extract_money_values,
    extract_percent_values,
    extract_dates,
    extract_standalone_ints,
    extract_portfolio_csv_from_pdf_bytes,
)


@app.get("/debug-version")
def debug_version():
    return {
        "ok": True,
        "version": "DEBUG_XP_EXTRACTOR_2026_05_02",
        "message": "Se isso aparecer, o deploy novo está ativo."
    }


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
            "csv_preview": csv_result[:1500]
        }

    except Exception as error:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(error)
            }
        )
