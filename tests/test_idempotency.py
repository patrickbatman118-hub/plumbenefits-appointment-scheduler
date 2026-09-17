from app.services.idempotency import fingerprint


def test_same_text_produces_same_fingerprint():
    assert fingerprint("Book dentist next Friday at 3pm", None) == fingerprint(
        "Book dentist next Friday at 3pm", None
    )


def test_different_text_produces_different_fingerprint():
    assert fingerprint("Book dentist next Friday at 3pm", None) != fingerprint(
        "Book dermatology next Friday at 3pm", None
    )


def test_text_and_image_never_collide():
    text_fp = fingerprint("some bytes", None)
    image_fp = fingerprint(None, b"some bytes")
    assert text_fp != image_fp


def test_same_image_bytes_produce_same_fingerprint():
    assert fingerprint(None, b"\x89PNG...") == fingerprint(None, b"\x89PNG...")


def test_different_image_bytes_produce_different_fingerprint():
    assert fingerprint(None, b"image-one") != fingerprint(None, b"image-two")
