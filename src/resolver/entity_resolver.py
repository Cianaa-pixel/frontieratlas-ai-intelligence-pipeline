import re
from rapidfuzz import fuzz


def normalize_name(name: str) -> str:
    """Normalize an entity name for comparison."""
    if not name:
        return ""

    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    name = re.sub(r"\s+", " ", name)

    return name


def similarity(name_a: str, name_b: str) -> float:
    """Return similarity score between two entity names."""
    a = normalize_name(name_a)
    b = normalize_name(name_b)

    if not a or not b:
        return 0.0

    return fuzz.token_sort_ratio(a, b) / 100.0


def resolve_entity(
    name: str,
    candidates: list[str],
    threshold: float = 0.85,
):
    """
    Find the closest matching entity.

    Returns:
        {
            "matched": bool,
            "name": str | None,
            "score": float
        }
    """

    best_name = None
    best_score = 0.0

    for candidate in candidates:
        score = similarity(name, candidate)

        if score > best_score:
            best_score = score
            best_name = candidate

    if best_score >= threshold:
        return {
            "matched": True,
            "name": best_name,
            "score": round(best_score, 4),
        }

    return {
        "matched": False,
        "name": None,
        "score": round(best_score, 4),
    }


if __name__ == "__main__":
    candidates = [
        "OpenAI",
        "Anthropic",
        "Google DeepMind",
        "Microsoft",
    ]

    result = resolve_entity("Open AI", candidates)

    print(result)