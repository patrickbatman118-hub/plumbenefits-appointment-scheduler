from app.gemini_client import extract_entities
from app.schemas import Entities, EntitiesResult


def extract(raw_text: str, department_choices: list[str]) -> EntitiesResult:
    parsed = extract_entities(raw_text, department_choices)
    entities = Entities(
        date_phrase=parsed.date_phrase,
        time_phrase=parsed.time_phrase,
        department=parsed.department,
    )
    return EntitiesResult(entities=entities, entities_confidence=parsed.entities_confidence)
