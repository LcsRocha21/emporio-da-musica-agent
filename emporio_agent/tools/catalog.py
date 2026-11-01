"""Catalog tools: product search and product lookup.

All prices come from the database; nothing is ever guessed. The *effective* price is
the promotional price when there is an active promotion, otherwise the list price.
"""

import difflib
import json
from contextlib import closing
from decimal import Decimal

from emporio_agent.text_utils import normalize_text
from emporio_agent.tools._common import connect, format_brl, money, to_decimal

PIX_DISCOUNT_PERCENT = Decimal("5")

# Words that carry no search meaning in a customer query (already accent-free).
STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "com", "sem",
    "para", "pra", "por", "em", "no", "na", "e", "ou", "ate", "que", "qual", "quais",
    "quero", "queria", "preciso", "tem", "voces", "disponiveis", "disponivel",
}  # fmt: skip

# What customers call each category. Keys are category ids from categories.csv.
CATEGORY_ALIASES = {
    1: ["guitarra", "guitarras"],
    2: ["baixo", "baixos", "contrabaixo", "contrabaixos"],  # contrabaixo = bass guitar in Brazil
    3: ["bateria", "baterias", "percussao"],
    4: ["teclado", "teclados", "piano", "pianos", "sintetizador", "sintetizadores"],
    5: ["violao", "violoes"],
    6: ["sopro", "madeiras", "flauta", "flautas", "clarinete", "clarinetes", "saxofone", "saxofones", "oboe"],
    7: ["metais", "trompete", "trompetes", "trombone", "trombones", "tuba", "tubas", "trompa", "trompas"],
    8: ["violino", "violinos", "viola", "violas", "violoncelo", "violoncelos", "cello", "cellos"],
    9: ["ukulele", "ukuleles", "ukelele", "uke"],
}  # fmt: skip
_ALIAS_TO_CATEGORY = {alias: cid for cid, aliases in CATEGORY_ALIASES.items() for alias in aliases}

_MATERIAL_ALIASES = {"nylon": "nylon", "nailon": "nylon", "aco": "steel", "steel": "steel"}

_CATALOG_SQL = """
SELECT p.*, c.name AS category_name, ap.discount_percent, ap.description AS promo_label
FROM products p
JOIN categories c ON c.category_id = p.category_id
LEFT JOIN active_promotions ap ON ap.product_id = p.product_id
ORDER BY p.product_id
"""


def _percent(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral() else float(value)


def _enrich(row: dict) -> dict:
    """Add pricing fields (Decimal) and search helpers to a product row."""
    list_price = money(row["price_brl"])
    discount = row["discount_percent"]
    if discount:
        pct = to_decimal(discount)
        effective = money(list_price * (Decimal(100) - pct) / Decimal(100))
        promotion = {"discount_percent": _percent(pct), "label": row["promo_label"]}
        pix_price = None  # PIX discount does not stack on promotional prices
    else:
        effective = list_price
        promotion = None
        pix_price = money(list_price * (Decimal(100) - PIX_DISCOUNT_PERCENT) / Decimal(100))
    row.update(
        list_price=list_price,
        effective_price=effective,
        promotion=promotion,
        pix_price=pix_price,
        name_words=set(normalize_text(row["name"]).split()),
        search_words=set(row["search_text"].split()),
    )
    return row


def load_catalog(conn) -> list[dict]:
    """All products with pricing fields. The catalog is small, so filtering is done in Python."""
    return [_enrich(dict(r)) for r in conn.execute(_CATALOG_SQL).fetchall()]


def public_view(product: dict, detailed: bool = False) -> dict:
    """JSON-safe description of a product, with display strings ready to quote."""
    view = {
        "product_id": product["product_id"],
        "name": product["name"],
        "category": product["category_name"],
        "availability": product["availability"],  # in_stock | out_of_stock | discontinued | coming_soon
        "units_in_stock": product["stock_quantity"],
        "price_brl": float(product["effective_price"]),
        "price_display": format_brl(product["effective_price"]),
    }
    if product["promotion"]:
        view["promotion"] = {
            **product["promotion"],
            "original_price_display": format_brl(product["list_price"]),
            "promo_price_display": format_brl(product["effective_price"]),
        }
        view["pix_price_display"] = None
        view["pix_note"] = "PIX discount does not apply to promotional prices"
    else:
        view["promotion"] = None
        view["pix_price_display"] = format_brl(product["pix_price"])
    if detailed:
        view["description"] = product["description"]
        view["specs"] = json.loads(product["specs_json"])
    return view


def _matches_token(token: str, words: set[str]) -> bool:
    if token.isdigit():
        return token in words
    return any(word.startswith(token) for word in words)


def _tokens(text: str | None) -> list[str]:
    return [t for t in normalize_text(text).split() if t not in STOPWORDS]


def _resolve_category(text: str | None, categories: dict[int, str]) -> int | None:
    """Map free text ("violões", "ukulele", "Teclados e Pianos") to a category id."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    for cid, name in categories.items():
        if normalized == normalize_text(name):
            return cid
    for token in normalized.split():
        if token in _ALIAS_TO_CATEGORY:
            return _ALIAS_TO_CATEGORY[token]
    return None


def search_products(
    query: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    string_material: str | None = None,
    electroacoustic: bool | None = None,
    only_available: bool = True,
    sort_by: str = "price_asc",
    limit: int = 8,
) -> dict:
    """Search the store catalog. Use it for browsing questions such as "which acoustic
    guitars cost up to R$ 1000?" or "do you have ukuleles?". ALWAYS call it before
    stating what the store sells, prices or stock.

    Args:
        query: Free text in Portuguese (brand, model, instrument type, features), e.g.
            "yamaha", "violão de aço", "ukulele soprano". Accents are ignored.
        category: Optional category such as "violões", "guitarras", "baixos", "baterias",
            "teclados", "ukuleles", "sopro". Also detected inside `query`.
        min_price: Minimum price in BRL. Compared with the price the customer pays
            (promotional price when there is an active promotion).
        max_price: Maximum price in BRL (same rule as min_price).
        string_material: "nylon" or "steel" (aço). Only applies to acoustic guitars and ukuleles.
        electroacoustic: True for models with built-in pickup, False for purely acoustic.
        only_available: True (default) hides products that are out of stock, discontinued or
            coming soon. Use False to see them too, flagged by their `availability`.
        sort_by: "price_asc" (default) or "price_desc".
        limit: Maximum number of products returned (1-20, default 8).

    Returns:
        total_matches, products (each with display prices, promotion and availability) and
        a `note` when nothing was found. Show promotions together with the original price
        and the discount percentage.
    """
    with closing(connect()) as conn:
        catalog = load_catalog(conn)
        categories = {r["category_id"]: r["name"] for r in conn.execute("SELECT category_id, name FROM categories")}

    tokens = _tokens(query)
    category_id = _resolve_category(category, categories)
    if category_id is None:
        for token in tokens:
            if token in _ALIAS_TO_CATEGORY:
                category_id = _ALIAS_TO_CATEGORY[token]
                break
    if category_id is not None:
        tokens = [t for t in tokens if _ALIAS_TO_CATEGORY.get(t) != category_id]

    result = {"filters_applied": {"query": query, "category": categories.get(category_id), "min_price": min_price,
                                  "max_price": max_price, "string_material": string_material,
                                  "electroacoustic": electroacoustic, "only_available": only_available}}

    if category_id is not None and not any(p["category_id"] == category_id for p in catalog):
        result.update(total_matches=0, products=[],
                      note=f"The catalog currently has no products in the category '{categories[category_id]}'.")
        return result

    material = _MATERIAL_ALIASES.get(normalize_text(string_material)) if string_material else None
    matches = []
    for p in catalog:
        if category_id is not None and p["category_id"] != category_id:
            continue
        if only_available and p["availability"] != "in_stock":
            continue
        if min_price is not None and p["effective_price"] < to_decimal(min_price):
            continue
        if max_price is not None and p["effective_price"] > to_decimal(max_price):
            continue
        if material and p["string_material"] != material:
            continue
        if electroacoustic is not None and p["has_pickup"] != (1 if electroacoustic else 0):
            continue
        if not all(_matches_token(t, p["search_words"]) for t in tokens):
            continue
        matches.append(p)

    in_stock_first = lambda p: 0 if p["availability"] == "in_stock" else 1  # noqa: E731
    if sort_by == "price_desc":
        matches.sort(key=lambda p: (in_stock_first(p), -p["effective_price"]))
    else:
        matches.sort(key=lambda p: (in_stock_first(p), p["effective_price"]))

    limit = max(1, min(int(limit), 20))
    result["total_matches"] = len(matches)
    result["products"] = [public_view(p, detailed=True) for p in matches[:limit]]
    if not matches:
        result["note"] = "No products matched these filters. Try relaxing the price range or the search words."
    return result


def _alternatives(target: dict, catalog: list[dict], count: int = 3) -> list[dict]:
    """Available products of the same category, closest in price to `target`."""
    pool = [
        p for p in catalog
        if p["product_id"] != target["product_id"]
        and p["category_id"] == target["category_id"]
        and p["availability"] == "in_stock"
    ]  # fmt: skip
    same_material = [p for p in pool if target["string_material"] and p["string_material"] == target["string_material"]]
    pool = same_material or pool
    pool.sort(key=lambda p: abs(p["effective_price"] - target["list_price"]))
    return [public_view(p) for p in pool[:count]]


def find_product(text: str, catalog: list[dict]) -> tuple[str, list[dict]]:
    """Resolve a product reference. Returns (status, products): found | ambiguous | not_found."""
    text = (text or "").strip()
    if text.isdigit():
        by_id = [p for p in catalog if p["product_id"] == int(text)]
        if by_id:
            return "found", by_id
    tokens = _tokens(text)
    if not tokens:
        return "not_found", []
    matches = [p for p in catalog if all(_matches_token(t, p["name_words"]) for t in tokens)]
    if len(matches) > 1:
        exact = [p for p in matches if normalize_text(p["name"]) == normalize_text(text)]
        matches = exact or matches
    if len(matches) == 1:
        return "found", matches
    if matches:
        return "ambiguous", matches
    return "not_found", []


def get_product(product: str) -> dict:
    """Look up ONE specific product by name, model or id and return its current price,
    promotion, stock and specs. Use it for questions like "how much is the Takamine GD20?"
    or "do you have the Yamaha C40 in stock?". ALWAYS call it before quoting a price or
    confirming availability of a specific product.

    If the product is out of stock, discontinued or coming soon, `alternatives` lists
    available products of the same category with similar prices: offer those.

    Args:
        product: Product name or model in Portuguese/English as the customer wrote it
            (e.g. "Takamine GD20", "Yamaha C40") or a numeric product_id.

    Returns:
        status: "found" (with `product` and maybe `alternatives`), "ambiguous" (with
        `matches`: ask which one the customer means) or "not_found" (with `suggestions`).
    """
    with closing(connect()) as conn:
        catalog = load_catalog(conn)

    status, found = find_product(product, catalog)
    if status == "found":
        item = found[0]
        result = {"status": "found", "product": public_view(item, detailed=True)}
        if item["availability"] != "in_stock":
            result["alternatives"] = _alternatives(item, catalog)
        return result
    if status == "ambiguous":
        return {"status": "ambiguous", "matches": [public_view(p) for p in found[:6]], "total_matches": len(found)}

    names = {normalize_text(p["name"]): p for p in catalog}
    close = difflib.get_close_matches(normalize_text(product), list(names), n=3, cutoff=0.5)
    return {"status": "not_found", "suggestions": [public_view(names[n]) for n in close]}
