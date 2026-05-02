from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject
from io import BytesIO
import urllib.request


app = FastAPI(title="Portfolio Extraction API")


class PdfUrlRequest(BaseModel):
    pdf_url: str


@app.get("/")
def healthcheck():
    return {
        "status": "ok",
        "message": "Portfolio Extraction API is running"
    }


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
            detail=f"O PDF tem {total_pages} páginas. Para parear lado a lado, o número de páginas precisa ser par."
        )

    half = total_pages // 2
    writer = PdfWriter()

    try:
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

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao combinar páginas do PDF: {str(e)}"
        )


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


@app.post("/combine-side-by-side-url")
async def combine_side_by_side_url(payload: PdfUrlRequest):
    try:
        request = urllib.request.Request(
            payload.pdf_url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")

            if "pdf" not in content_type.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"A URL não retornou um PDF. Content-Type recebido: {content_type}"
                )

            input_bytes = response.read()

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Não foi possível baixar o PDF pela URL informada: {str(e)}"
        )

    output_bytes = combine_pdf_bytes(input_bytes)

    return Response(
        content=output_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="combined-side-by-side.pdf"'
        }
    )
