"""Policy tool: search the store's policy manual."""

from emporio_agent.policies import CHUNK_NOTES, get_index


def search_policies(query: str, top_k: int = 3) -> dict:
    """Search the store's policy manual for rules and general information: opening hours,
    address, phone/WhatsApp/e-mail, payment methods and installment rules, returns and
    exchanges, shipping and delivery rules, tracking codes, promotions rules, warranty,
    privacy (LGPD), what the store sells (instruments only, no accessories).

    Use it for questions about HOW the store works. Do NOT use it for prices, stock or a
    customer's order (use the catalog and order tools) and never for numbers you can get
    from a dedicated tool (installments, shipping quotes, return deadlines).

    The manual is internal: answer in your own words with only what the customer needs,
    do not paste it. Obey the `notes` attached to a result, they flag inconsistencies in
    the manual and tell which tool to use for exact figures.

    Args:
        query: The customer's question or topic in Portuguese, e.g. "horário de sábado",
            "posso trocar por outro modelo?", "qual o prazo para devolver?".
        top_k: Number of manual sections to return (1-5, default 3).

    Returns:
        results: list of sections (section id, path, text, notes). Empty when the manual
        has nothing relevant: say you don't have that information and offer to hand the
        question to the team instead of guessing.
    """
    top_k = max(1, min(int(top_k), 5))
    hits = get_index().search(query, top_k=top_k)
    results = []
    for chunk, score in hits:
        result = {
            "section": chunk.section_id,
            "path": chunk.path,
            "text": chunk.text,
            "relevance": round(score, 2),
        }
        notes = CHUNK_NOTES.get(chunk.section_id)
        if notes:
            result["notes"] = notes
        results.append(result)
    if not results:
        return {
            "results": [],
            "note": "The manual has nothing relevant to this question. Do not guess: say you don't have that "
            "information and offer to hand the question to the team (handoff_to_human).",
        }
    return {"results": results}
