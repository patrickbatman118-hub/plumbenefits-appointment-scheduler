from app.guardrails import ambiguous_date_time, ambiguous_department, low_confidence, slot_conflict


def test_ambiguous_department_shape():
    result = ambiguous_department()
    assert result.status == "needs_clarification"
    assert "department" in result.message.lower()


def test_ambiguous_date_time_shape():
    result = ambiguous_date_time()
    assert result.status == "needs_clarification"
    assert "date/time" in result.message.lower()


def test_low_confidence_message_includes_stage_and_values():
    result = low_confidence("OCR", 0.3, 0.5)
    assert result.status == "needs_clarification"
    assert "OCR" in result.message
    assert "0.30" in result.message
    assert "0.50" in result.message


def test_slot_conflict_shape():
    result = slot_conflict("Dentistry", "2025-09-26", "15:00")
    assert result.status == "slot_conflict"
    assert "Dentistry" in result.message
    assert "2025-09-26" in result.message
