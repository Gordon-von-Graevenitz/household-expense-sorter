import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ledger.models import ExclusionRule, Household, ImportBatch, Partner, Payment, Transaction

pytestmark = pytest.mark.django_db


def upload(client, partner, filename, rows):
    statement = SimpleUploadedFile(filename, rows.encode(), content_type="text/csv")
    return client.post(
        reverse("ledger:upload"),
        {
            "partner": partner,
            "statement": statement,
            "currency": "EUR",
            "expense_direction": "negative",
        },
    )


def test_dashboard_renders_two_upload_panels(client):
    response = client.get(reverse("ledger:dashboard"))

    assert response.status_code == 200
    assert response.content.count(b'name="statement"') == 2
    assert b"Partner A" in response.content
    assert b"Partner B" in response.content


def test_upload_redirects_to_statement_month(client):
    response = upload(
        client,
        Partner.A,
        "july.csv",
        "Date,Description,Amount\n03/07/2026,Groceries,-20.00\n",
    )

    assert response.status_code == 302
    assert "month=2026-07" in response.url
    assert Transaction.objects.get().amount_minor == 2000


def test_google_sheets_export_data_contains_only_included_rows(client):
    upload(
        client,
        Partner.A,
        "july.csv",
        "Date,Description,Category,Amount\n"
        "03/07/2026,Included shop,Groceries,-20.00\n"
        "04/07/2026,Excluded shop,Shopping,-30.00\n",
    )
    excluded = Transaction.objects.get(description="Excluded shop")
    excluded.included = False
    excluded.save(update_fields=["included"])

    response = client.get(
        reverse("ledger:dashboard"),
        {"month": "2026-07", "currency": "EUR"},
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "Copy for Google Sheets" in content
    assert content.count("data-export-row") == 1
    assert 'data-export-date="03.07.2026"' in content
    assert 'data-export-category="Groceries"' in content
    assert 'data-export-details="Included shop"' in content
    assert 'data-export-amount="20.00"' in content
    assert f'id="transaction-{excluded.id}"' in content
    assert content.count("data-preserve-scroll") == 2


def test_clear_import_deletes_only_that_batch_and_its_transactions(client):
    upload(
        client,
        Partner.A,
        "july.csv",
        "Date,Description,Amount\n03/07/2026,Groceries,-20.00\n",
    )
    batch = ImportBatch.objects.get()

    response = client.post(
        reverse("ledger:delete_import", args=[batch.id]),
        {"month": "2026-07", "currency": "EUR"},
    )

    assert response.status_code == 302
    assert ImportBatch.objects.count() == 0
    assert Transaction.objects.count() == 0


def test_replace_upload_swaps_the_selected_batch(client):
    upload(
        client,
        Partner.A,
        "first.csv",
        "Date,Description,Amount\n03/07/2026,Old merchant,-20.00\n",
    )
    original = ImportBatch.objects.get()
    replacement = SimpleUploadedFile(
        "replacement.csv",
        b"Date,Description,Amount\n04/07/2026,New merchant,-30.00\n",
        content_type="text/csv",
    )

    response = client.post(
        reverse("ledger:upload"),
        {
            "partner": Partner.A,
            "replace_batch_id": original.id,
            "statement": replacement,
            "currency": "EUR",
            "expense_direction": "negative",
        },
    )

    assert response.status_code == 302
    assert ImportBatch.objects.count() == 1
    assert Transaction.objects.get().description == "New merchant"


def test_always_exclude_creates_rule_and_excludes_matching_transactions(client):
    upload(
        client,
        Partner.A,
        "a.csv",
        "Date,Description,Amount\n03/07/2026,Netflix,-17.99\n",
    )
    item = Transaction.objects.get()

    response = client.post(
        reverse("ledger:transaction_action", args=[item.id]),
        {"action": "always"},
    )

    assert response.status_code == 302
    item.refresh_from_db()
    assert item.included is False
    assert ExclusionRule.objects.filter(match_value="NETFLIX", active=True).exists()


def test_record_payment_closes_outstanding_settlement(client):
    upload(
        client,
        Partner.A,
        "a.csv",
        "Date,Description,Amount\n03/07/2026,A expense,-200.00\n",
    )
    upload(
        client,
        Partner.B,
        "b.csv",
        "Date,Description,Amount\n03/07/2026,B expense,-800.00\n",
    )

    response = client.post(
        reverse("ledger:record_payment"),
        {"month": "2026-07", "currency": "EUR", "paid_on": "2026-08-01", "note": "Transfer"},
    )

    assert response.status_code == 302
    payment = Payment.objects.get()
    assert payment.payer == Partner.A
    assert payment.amount_minor == 30000


def test_ratio_update_is_stored_as_basis_points(client):
    Household.objects.create(pk=1)

    response = client.post(
        reverse("ledger:update_ratio"),
        {"month": "2026-07", "currency": "EUR", "partner_a_percent": 60},
    )

    assert response.status_code == 302
    assert Household.objects.get(pk=1).default_split_a_basis_points == 6000
