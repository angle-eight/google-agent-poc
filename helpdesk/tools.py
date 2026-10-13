"""Small, deterministic tools. All policies below are fictional demo data."""

import json
import unicodedata
from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=1)
def load_knowledge() -> list[dict]:
    return json.loads(files("helpdesk").joinpath("data/knowledge.json").read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().lower()


def search_knowledge(
    query: str, limit: int = 3, *, categories: tuple[str, ...] | None = None
) -> dict:
    """Search fictional company policies using short Japanese or English keywords.

    Args:
        query: Topic or keywords such as VPN, 在宅勤務, PC購入, 経費.
        limit: Maximum number of documents, between 1 and 5.
        categories: Restrict results to these categories when specified.

    Returns:
        Matching documents including IDs to cite, or an empty results list.
    """
    query = normalize(query)
    if not query:
        return {"results": [], "demo_data": True}
    scored = []
    for doc in load_knowledge():
        if categories is not None and doc["category"] not in categories:
            continue
        score = sum(len(word) for word in doc["keywords"] if normalize(word) in query)
        if normalize(doc["id"]) in query:
            score += 100
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    return {"results": [doc for _, doc in scored[: max(1, min(limit, 5))]], "demo_data": True}


def search_it_knowledge(query: str, limit: int = 3) -> dict:
    """Search fictional IT/security policies: VPN, PC, software, accounts, lost devices, phishing.

    Args:
        query: Short topic, keywords, or policy ID such as VPN or IT-002.
        limit: Maximum number of documents, between 1 and 5.
    """
    return search_knowledge(query, limit, categories=("IT", "セキュリティ"))


def search_hr_knowledge(query: str, limit: int = 3) -> dict:
    """Search fictional HR policies: remote work, paid leave, flextime, overtime, caregiving.

    Args:
        query: Short topic, keywords, or policy ID such as 有給休暇 or HR-002.
        limit: Maximum number of documents, between 1 and 5.
    """
    return search_knowledge(query, limit, categories=("人事",))


def search_accounting_knowledge(query: str, limit: int = 3) -> dict:
    """Search fictional accounting policies: expenses, travel, meals, receipts, invoices.

    Args:
        query: Short topic, keywords, or policy ID such as 出張 or FIN-002.
        limit: Maximum number of documents, between 1 and 5.
    """
    return search_knowledge(query, limit, categories=("経理",))


KNOWLEDGE_SEARCH_TOOLS = frozenset(
    {
        "search_knowledge",  # Accept responses from an existing single-agent deployment as well.
        "search_it_knowledge",
        "search_hr_knowledge",
        "search_accounting_knowledge",
    }
)


def estimate_purchase(unit_price_yen: int, quantity: int, tax_included: bool = True) -> dict:
    """Calculate a PC purchase total and approval route using fictional policy IT-002.

    Args:
        unit_price_yen: Price per PC in whole Japanese yen, greater than zero.
        quantity: Number of PCs, between 1 and 1000.
        tax_included: Whether the unit price includes the demo tax rate of 10 percent.

    Returns:
        Integer total in yen and required approvers. No order or request is submitted.
    """
    if (
        type(unit_price_yen) is not int
        or type(quantity) is not int
        or type(tax_included) is not bool
        or not 1 <= unit_price_yen <= 1_000_000_000
        or not 1 <= quantity <= 1000
    ):
        return {"error": "単価は1〜10億円、台数は1〜1000の整数で指定してください。"}
    subtotal = unit_price_yen * quantity
    # For this demo, floor fractional yen once on the order total.
    total = subtotal if tax_included else subtotal * 110 // 100
    return {
        "total_yen": total,
        "tax_included": True,
        "tax_rule": "デモ税率10%。税抜の場合、合計への課税後に1円未満切り捨て。",
        "approvers": ["直属の上長"] if total <= 200_000 else ["直属の上長", "部門責任者"],
        "source_id": "IT-002",
        "demo_data": True,
        "submitted": False,
    }
