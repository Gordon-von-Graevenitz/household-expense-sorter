import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ledger.models import ExclusionRule, Household, Partner, Payment, Transaction

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
