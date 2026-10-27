from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from ledger.models import ExclusionRule, Household, ImportBatch, Partner, Transaction
from ledger.services import ImportProblem, calculate_settlement, import_statement

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


def test_partner_export_maps_explicit_roles_and_infers_currency_from_amount_header():
    household = Household.objects.create()
    content = (
        b'"Booking Date","Value Date","Partner Name","Partner Iban",Type,'
        b'"Payment Reference","Account Name","Amount (EUR)","Original Amount",'
        b'"Original Currency","Exchange Rate"\n'
        b'"2026-09-05","2026-09-06","REWE Markt","DE001234",Card,'
        b'"Weekly groceries","Main account","-84,62","","",""\n'
    )
    statement = SimpleUploadedFile("bank-export.csv", content, content_type="text/csv")

    import_statement(
        household=household,
        partner=Partner.A,
        uploaded_file=statement,
        currency="USD",
        expense_direction="negative",
    )

    item = Transaction.objects.get()
    assert item.transaction_date == date(2026, 9, 5)
    assert item.description == "REWE Markt"
    assert item.reference == "Weekly groceries"
    assert item.category == "Card"
    assert item.amount_minor == 8462
    assert item.currency == "EUR"


def test_replacing_an_import_swaps_batches_after_the_new_file_is_valid():
    household = Household.objects.create()
    original = import_statement(
        household=household,
        partner=Partner.A,
        uploaded_file=statement_file(),
        currency="EUR",
        expense_direction="negative",
    )
    original_id = original.batch.id

    replacement = import_statement(
        household=household,
        partner=Partner.A,
        uploaded_file=statement_file(),
        currency="EUR",
        expense_direction="negative",
        replace_batch=original.batch,
    )

    assert ImportBatch.objects.count() == 1
    assert not ImportBatch.objects.filter(pk=original_id).exists()
    assert replacement.batch.id != original_id
    assert Transaction.objects.count() == 1


def test_invalid_replacement_preserves_the_existing_import():
    household = Household.objects.create()
    original = import_statement(
        household=household,
        partner=Partner.A,
        uploaded_file=statement_file(),
        currency="EUR",
        expense_direction="negative",
    )
    invalid = SimpleUploadedFile("invalid.csv", b"Unknown\nvalue\n", content_type="text/csv")

    with pytest.raises(ImportProblem):
        import_statement(
            household=household,
            partner=Partner.A,
            uploaded_file=invalid,
            currency="EUR",
            expense_direction="negative",
            replace_batch=original.batch,
        )

    assert ImportBatch.objects.filter(pk=original.batch.id).exists()
    assert Transaction.objects.count() == 1


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
