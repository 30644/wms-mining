"""
二维码批量生成工具
端点: /api/utils/qrcode/single | batch | print-sheet
"""
import io, zipfile
from typing import List, Optional

import qrcode
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.routes.auth import get_current_user

router = APIRouter()


class SingleQRRequest(BaseModel):
    text: str
    size: int = Field(default=200, ge=50, le=1000)


class BatchQRRequest(BaseModel):
    texts: List[str] = Field(..., min_length=1)
    size: int = Field(default=200, ge=50, le=1000)


class PrintSheetRequest(BaseModel):
    texts: List[str] = Field(..., min_length=1)
    cols: int = Field(default=4, ge=1, le=8)
    size: int = Field(default=150, ge=50, le=500)


def _generate_qr_image(text: str, size: int = 200):
    img = qrcode.make(text)
    img = img.resize((size, size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@router.post("/qrcode/single", summary="生成单个二维码")
async def generate_single_qr(req: SingleQRRequest, _=Depends(get_current_user)):
    buf = _generate_qr_image(req.text, req.size)
    return StreamingResponse(buf, media_type="image/png",
                             headers={"Content-Disposition": f"attachment; filename={req.text}.png"})


@router.post("/qrcode/batch", summary="批量生成二维码（ZIP下载）")
async def generate_batch_qr(req: BatchQRRequest, _=Depends(get_current_user)):
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for text in req.texts:
            img_buf = _generate_qr_image(text, req.size)
            safe_name = text.replace("/", "_").replace("\\", "_") + ".png"
            zf.writestr(safe_name, img_buf.read())
    zip_buf.seek(0)
    return StreamingResponse(zip_buf, media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=qr_codes.zip"})


@router.post("/qrcode/print-sheet", summary="二维码打印排版（PDF）")
async def generate_print_sheet(req: PrintSheetRequest, _=Depends(get_current_user)):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    pdf_buf = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buf, pagesize=A4,
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    elements = []

    # 每页表格
    rows_per_page = 5
    texts = req.texts
    cols = req.cols
    cell_size = req.size / 3.78  # px to mm (approximate)

    for page_start in range(0, len(texts), rows_per_page * cols):
        page_texts = texts[page_start:page_start + rows_per_page * cols]
        table_data = []
        row = []
        for i, text in enumerate(page_texts):
            img_buf = _generate_qr_image(text, req.size)
            # 将图片嵌入到paragraph中
            from reportlab.platypus import Image
            img = Image(img_buf, width=cell_size, height=cell_size)
            label = Paragraph(text, styles["Normal"])
            cell = [[img], [label]]
            row.append(cell)
            if len(row) == cols or i == len(page_texts) - 1:
                while len(row) < cols:
                    row.append("")
                table_data.append(row)
                row = []

        if table_data:
            t = Table(table_data, colWidths=[doc.width / cols] * cols,
                      rowHeights=[cell_size + 12*mm] * len(table_data))
            t.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 6*mm))

    doc.build(elements)
    pdf_buf.seek(0)
    return StreamingResponse(pdf_buf, media_type="application/pdf",
                             headers={"Content-Disposition": "attachment; filename=qr_print_sheet.pdf"})
