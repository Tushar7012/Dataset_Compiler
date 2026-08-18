from __future__ import annotations

import logging
import os
from io import BytesIO

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.settings import settings as docling_settings
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.exceptions import ConversionError, SecurityError
from docling_core.types.io import DocumentStream
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

# Same reasoning as tuneforge/ingestion/documents.py: JIT-compiling the layout
# model adds a large one-time cost per process, dwarfing the actual GPU
# inference time on a request-by-request basis (measured ~95s vs ~5s on the
# GB10 spike). Disabling it is correct here too, not just a Windows quirk.
docling_settings.inference.compile_torch_models = False

logger = logging.getLogger("dgx_docling_service")

_AUTH_TOKEN = os.environ.get("DGX_PARSER_TOKEN")
if _AUTH_TOKEN is None:
    logger.warning(
        "DGX_PARSER_TOKEN is not set — this service will accept requests from anyone who can reach it "
        "over the network, with no authentication at all. Set DGX_PARSER_TOKEN before deploying for real use."
    )

app = FastAPI(title="TuneForge DGX Docling Parser")
_converter: DocumentConverter | None = None


def build_converter() -> DocumentConverter:
    # do_ocr=False and TableFormer's default ACCURATE mode mirror the app's
    # own local settings exactly — this service changes where parsing runs,
    # not what it extracts.
    pdf_options = PdfPipelineOptions(
        do_ocr=False,
        accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CUDA),
    )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)})


def get_converter() -> DocumentConverter:
    # Built once per process and reused — model loading is the expensive
    # part, not worth repeating per request.
    global _converter
    if _converter is None:
        _converter = build_converter()
    return _converter


def _check_auth(authorization: str | None) -> None:
    if _AUTH_TOKEN is None:
        return
    if authorization != f"Bearer {_AUTH_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/convert")
async def convert(
    request: Request,
    x_document_filename: str = Header(...),
    authorization: str | None = Header(default=None),
    converter: DocumentConverter = Depends(get_converter),
) -> JSONResponse:
    _check_auth(authorization)
    body = await request.body()
    stream = DocumentStream(name=x_document_filename, stream=BytesIO(body))
    try:
        result = converter.convert(stream)
    except SecurityError:
        return JSONResponse(status_code=422, content={"error": "encrypted"})
    except ConversionError as exc:
        return JSONResponse(status_code=422, content={"error": "corrupt", "detail": str(exc)})
    return JSONResponse(content=result.document.model_dump(mode="json"))
