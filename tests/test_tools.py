import pytest

from helpdesk.tools import (
    estimate_purchase,
    load_knowledge,
    search_accounting_knowledge,
    search_hr_knowledge,
    search_it_knowledge,
    search_knowledge,
)


def test_search_handles_full_width_case_and_missing_topics():
    assert search_knowledge("ＶＰＮに接続できない")["results"][0]["id"] == "IT-001"
    assert search_knowledge("就業規則の退職金")["results"] == []
    assert search_knowledge(" ")["results"] == []


def test_search_limits_and_document_ids():
    assert len(search_knowledge("VPN PC 在宅 経費 メール", limit=2)["results"]) == 2
    assert search_knowledge("IT-002")["results"][0]["id"] == "IT-002"


@pytest.mark.parametrize(
    "search,query,expected,other_id",
    [
        (search_it_knowledge, "ソフトウェア", "IT-003", "HR-002"),
        (search_it_knowledge, "フィッシング", "SEC-001", "FIN-004"),
        (search_hr_knowledge, "有給", "HR-002", "IT-001"),
        (search_hr_knowledge, "残業", "HR-004", "FIN-002"),
        (search_accounting_knowledge, "宿泊", "FIN-002", "IT-002"),
        (search_accounting_knowledge, "請求書", "FIN-005", "HR-001"),
    ],
)
def test_specialist_searches_only_its_own_policies(search, query, expected, other_id):
    assert search(query)["results"][0]["id"] == expected
    assert search(other_id)["results"] == []


def test_knowledge_has_unique_ids_and_complete_documents():
    documents = load_knowledge()
    assert len(documents) == len({doc["id"] for doc in documents}) == 16
    for doc in documents:
        assert all(
            doc.get(field) for field in ("title", "category", "keywords", "content", "contact")
        )
        assert search_knowledge(doc["id"])["results"][0]["id"] == doc["id"]


@pytest.mark.parametrize(
    "price,quantity,included,total,approvers",
    [
        (100_000, 2, True, 200_000, ["直属の上長"]),
        (200_001, 1, True, 200_001, ["直属の上長", "部門責任者"]),
        (180_000, 2, True, 360_000, ["直属の上長", "部門責任者"]),
        (90_910, 2, False, 200_002, ["直属の上長", "部門責任者"]),
        (101, 3, False, 333, ["直属の上長"]),
    ],
)
def test_purchase_approval_boundary_and_integer_tax(price, quantity, included, total, approvers):
    result = estimate_purchase(price, quantity, included)
    assert result["total_yen"] == total
    assert result["approvers"] == approvers
    assert result["submitted"] is False


@pytest.mark.parametrize(
    "price,quantity", [(0, 1), (-1, 1), (10, 0), (10, 1001), (True, 1), (10.5, 1), (10, False)]
)
def test_purchase_rejects_invalid_numeric_inputs(price, quantity):
    assert "error" in estimate_purchase(price, quantity)
