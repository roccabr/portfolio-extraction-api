from pydantic import BaseModel, HttpUrl
from typing import Optional


class ExtractPortfolioRequest(BaseModel):
    report_id: Optional[str] = None
    portfolio_pdf_url: HttpUrl
