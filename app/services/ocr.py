from app.gemini_client import ocr_image
from app.schemas import OCRResult


def ocr_text(text: str) -> OCRResult:
    """Typed text has no OCR uncertainty, so confidence is fixed at 1.0.

    Only image inputs get a model-estimated confidence - see the README's
    "Design Decisions" section for why that number is a heuristic, not a
    calibrated probability.
    """
    return OCRResult(raw_text=text.strip(), confidence=1.0)


def ocr_from_image(image_bytes: bytes, mime_type: str) -> OCRResult:
    result = ocr_image(image_bytes, mime_type)
    return OCRResult(raw_text=result.raw_text, confidence=result.confidence)
