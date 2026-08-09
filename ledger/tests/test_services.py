from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from ledger.models import ExclusionRule, Household, Partner, Transaction
from ledger.services import calculate_settlement, import_statement

pytestmark = pytest.mark.django_db


def statement_file(name="statement.csv", merchant="REWE Markt", amount="-84.62"):
    content = (
        "Date,Description,Amount,Category,Currency\n"
        f"03/07/2026,{merchant},{amount},Groceries,EUR\n"
        "04/07/2026,Salary,2500.00,Income,EUR\n"
    ).encode()
    return SimpleUploadedFile(name, content, content_type="text/csv")


def test_negative_statement_imports_expenses_and_skips_income():
    household = Household.objects.create()

    result = import_statement(
        household=household,
        partner=Partner.A,
        uploaded_file=statement_file(),
        currency="EUR",
        expense_direction="auto",
    )

    assert result.imported == 1
    assert result.skipped == 1
    item = Transaction.objects.get()
    assert item.transaction_date == date(2026, 7, 3)
    assert item.amount_minor == 8462
    assert item.description == "REWE Markt"
    assert item.included is True


def test_saved_merchant_rule_applies_to_future_import():
    household = Household.objects.create()
    ExclusionRule.objects.create(
        household=household,
        match_type=ExclusionRule.MatchType.EXACT_MERCHANT,
        match_value="NETFLIX",
        display_value="Netflix",
    )

    import_statement(
        household=household,
        partner=Partner.B,
        uploaded_file=statement_file(name="netflix.csv", merchant="Netflix", amount="-17.99"),
        currency="EUR",
        expense_direction="negative",
    )

    item = Transaction.objects.get()
    assert item.included is False
    assert item.auto_excluded_by is not None


@pytest.mark.parametrize(
    ("ratio_a", "expected_payer", "expected_due"),
    [
        (5000, Partner.A, 30000),
        (6000, Partner.A, 40000),
    ],
)
def test_settlement_calculation_uses_configurable_ratio(ratio_a, expected_payer, expected_due):
    household = Household.objects.create()
    a_result = import_statement(
        household=household,
        partner=Partner.A,
        uploaded_file=statement_file(name="a.csv", merchant="A expense", amount="-200.00"),
        currency="EUR",
        expense_direction="negative",
    )
    b_result = import_statement(
        household=household,
        partner=Partner.B,
        uploaded_file=statement_file(name="b.csv", merchant="B expense", amount="-800.00"),
        currency="EUR",
        expense_direction="negative",
    )
    assert a_result.imported == b_result.imported == 1

    summary = calculate_settlement(household.transactions.all(), ratio_a)

    assert summary["total"] == 100000
    assert summary["payer"] == expected_payer
    assert summary["receiver"] == Partner.B
    assert summary["amount_due"] == expected_due
    assert summary["responsibility_a"] + summary["responsibility_b"] == summary["total"]


def test_excluded_transactions_are_removed_from_settlement():
    household = Household.objects.create()
    import_statement(
        household=household,
        partner=Partner.A,
        uploaded_file=statement_file(name="excluded.csv", amount="-100.00"),
        currency="EUR",
        expense_direction="negative",
    )
    item = Transaction.objects.get()
    item.included = False
    item.save(update_fields=["included"])

    summary = calculate_settlement(household.transactions.all(), 5000)

    assert summary["total"] == 0
    assert summary["amount_due"] == 0
