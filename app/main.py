from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response, JSONResponse

from app.schemas import ExtractPortfolioRequest
from app.extractor import (
    extract_portfolio_csv_from_pdf_bytes,
    extract_portfolio_csv_from_pdf_url,
)

app = FastAPI(
    title="Portfolio Extraction API",
    description="API para reconstruir PDF de carteira e retornar CSV padronizado.",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "portfolio-extraction-api",
        "version": "0.1.0",
    }


@app.post("/extract-portfolio-csv")
def extract_portfolio_csv(payload: ExtractPortfolioRequest):
    try:
        csv_content = extract_portfolio_csv_from_pdf_url(str(payload.portfolio_pdf_url))

        filename = "portfolio_extracted.csv"
        if payload.report_id:
            filename = f"{payload.report_id}_portfolio_extracted.csv"

        return Response(
            content=csv_content,
            media_type="text/csv",
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
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="File must be a PDF.")

        pdf_bytes = await file.read()
        csv_content = extract_portfolio_csv_from_pdf_bytes(pdf_bytes)

        filename = file.filename.replace(".pdf", "_portfolio_extracted.csv")

        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "error": str(error),
            },
        )
