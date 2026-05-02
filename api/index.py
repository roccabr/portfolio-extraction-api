from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response, JSONResponse
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject
from io import BytesIO
import math


app = FastAPI(title="Portfolio Extraction API")


@app.get("/")
def healthcheck():
    return {
        "status": "ok",
        "message": "Portfolio Extraction API is running"
    }


def safe_page_size(page):
    """
    Retorna largura e altura da página em pontos PDF.
    """
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    return width, height


@app.post("/combine-side-by-side")
async def combine_side_by_side(file: UploadFile = File(...)):
    """
    Recebe um PDF com páginas fora de ordem visual e devolve um novo PDF
    com as páginas lado a lado.

    Regra:
    - página 1 com página 4
    - página 2 com página 5
    - página 3 com página 6

    Para PDFs maiores, a lógica geral é:
    primeira metade + segunda metade.
    Exemplo:
    1 + 4
    2 + 5
    3 + 6
    """

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")

    input_bytes = await file.read()

    try:
        reader = PdfReader(BytesIO(input_bytes))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler o PDF: {str(e)}")

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

            # Normaliza rotação para evitar páginas viradas ou deslocadas.
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

            # Centraliza verticalmente caso as páginas tenham alturas diferentes.
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

        return Response(
            content=output.read(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="combined-side-by-side.pdf"'
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao combinar páginas do PDF: {str(e)}"
        )
