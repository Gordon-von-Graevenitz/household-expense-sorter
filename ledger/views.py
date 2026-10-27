from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import PaymentForm, RatioForm, UploadStatementForm
from .models import ExclusionRule, Household, Partner, Payment, Settlement, Transaction
from .services import DuplicateImport, ImportProblem, calculate_settlement, import_statement


def get_household() -> Household:
    household, _ = Household.objects.get_or_create(
        pk=1,
        defaults={
            "name": "Our household",
            "partner_a_name": "Partner A",
            "partner_b_name": "Partner B",
        },
    )
    return household


def parse_month(value: str | None) -> date:
    if value:
        try:
            year, month = (int(part) for part in value.split("-", 1))
            return date(year, month, 1)
        except (TypeError, ValueError):
            pass
    today = timezone.localdate()
    return date(today.year, today.month, 1)


def next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def dashboard_url(month: date, currency: str) -> str:
    return f"{reverse('ledger:dashboard')}?month={month:%Y-%m}&currency={currency}"


def dashboard(request: HttpRequest) -> HttpResponse:
    household = get_household()
    month = parse_month(request.GET.get("month"))
    end = next_month(month)
    month_transactions = household.transactions.filter(
        transaction_date__gte=month, transaction_date__lt=end
    )
    currencies = list(
        month_transactions.order_by("currency").values_list("currency", flat=True).distinct()
    )
    selected_currency = request.GET.get("currency", "").upper()
    if selected_currency not in currencies:
        selected_currency = currencies[0] if currencies else "EUR"
    transactions = month_transactions.filter(currency=selected_currency).select_related(
        "import_batch", "auto_excluded_by"
    )
    partner_a_transactions = transactions.filter(partner=Partner.A)
    partner_b_transactions = transactions.filter(partner=Partner.B)
    summary = calculate_settlement(transactions, household.default_split_a_basis_points)

    settlement = Settlement.objects.filter(
        household=household, month=month, currency=selected_currency
    ).first()
    paid_minor = 0
    payments = []
    if settlement:
        payments = list(settlement.payments.all())
        paid_minor = settlement.payments.aggregate(total=Sum("amount_minor"))["total"] or 0
    summary["settled_minor"] = int(paid_minor)
    summary["outstanding_minor"] = max(int(summary["amount_due"]) - int(paid_minor), 0)

    partner_batches = {}
    for partner in (Partner.A, Partner.B):
        partner_batches[partner] = (
            household.imports.filter(
                partner=partner,
                transactions__transaction_date__gte=month,
                transactions__transaction_date__lt=end,
                currency=selected_currency,
            )
            .distinct()
            .first()
        )

    context = {
        "household": household,
        "month": month,
        "month_value": month.strftime("%Y-%m"),
        "month_label": month.strftime("%B %Y"),
        "currency": selected_currency,
        "currencies": currencies,
        "partner_a_transactions": partner_a_transactions,
        "partner_b_transactions": partner_b_transactions,
        "partner_a_batch": partner_batches[Partner.A],
        "partner_b_batch": partner_batches[Partner.B],
        "summary": summary,
        "payments": payments,
        "rules": household.rules.filter(active=True),
        "today": timezone.localdate(),
        "ratio_a": household.default_split_a_basis_points // 100,
        "ratio_b": 100 - household.default_split_a_basis_points // 100,
    }
    return render(request, "ledger/dashboard.html", context)


def upload_statement_view(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect("ledger:dashboard")
    household = get_household()
    form = UploadStatementForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(
            request, " ".join(error for errors in form.errors.values() for error in errors)
        )
        return redirect("ledger:dashboard")
    replace_batch = None
    replace_batch_id = form.cleaned_data.get("replace_batch_id")
    if replace_batch_id:
        replace_batch = household.imports.filter(
            pk=replace_batch_id,
            partner=form.cleaned_data["partner"],
        ).first()
        if replace_batch is None:
            messages.error(request, "The import selected for replacement no longer exists.")
            return redirect("ledger:dashboard")
    try:
        result = import_statement(
            household=household,
            partner=form.cleaned_data["partner"],
            uploaded_file=form.cleaned_data["statement"],
            currency=form.cleaned_data["currency"],
            expense_direction=form.cleaned_data["expense_direction"],
            replace_batch=replace_batch,
        )
    except (DuplicateImport, ImportProblem) as exc:
        messages.error(request, str(exc))
        return redirect("ledger:dashboard")
    partner_name = household.partner_name(result.batch.partner)
    action = "Replaced the import with" if replace_batch else "Imported"
    note = f"{action} {result.imported} expenses for {partner_name}."
    if result.skipped:
        note += f" Skipped {result.skipped} non-expense or invalid rows."
    messages.success(request, note.strip())
    return redirect(dashboard_url(result.first_date.replace(day=1), result.batch.currency))


def delete_import(request: HttpRequest, batch_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("ledger:dashboard")
    household = get_household()
    batch = get_object_or_404(household.imports, pk=batch_id)
    month = parse_month(request.POST.get("month"))
    currency = request.POST.get("currency", batch.currency).upper()
    filename = batch.original_filename
    deleted_transactions = batch.transactions.count()
    batch.delete()
    messages.success(
        request,
        f"Cleared {filename} and its {deleted_transactions} imported transactions.",
    )
    return redirect(dashboard_url(month, currency))


def transaction_action(request: HttpRequest, transaction_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("ledger:dashboard")
    household = get_household()
    item = get_object_or_404(Transaction, pk=transaction_id, household=household)
    action = request.POST.get("action")
    if action == "include":
        item.included = True
        item.exclusion_reason = ""
        item.auto_excluded_by = None
        item.save(update_fields=["included", "exclusion_reason", "auto_excluded_by"])
    elif action == "exclude":
        item.included = False
        item.exclusion_reason = "Excluded for this month"
        item.auto_excluded_by = None
        item.save(update_fields=["included", "exclusion_reason", "auto_excluded_by"])
    elif action == "always":
        rule, _ = ExclusionRule.objects.update_or_create(
            household=household,
            match_type=ExclusionRule.MatchType.EXACT_MERCHANT,
            match_value=item.normalized_description,
            defaults={"display_value": item.description, "active": True},
        )
        household.transactions.filter(normalized_description=item.normalized_description).update(
            included=False,
            exclusion_reason=f"Matched saved rule: {rule.display_value}",
            auto_excluded_by=rule,
        )
        messages.success(request, f"{item.description} will be excluded from future imports.")
    return redirect(dashboard_url(item.transaction_date.replace(day=1), item.currency))


def update_ratio(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect("ledger:dashboard")
    household = get_household()
    form = RatioForm(request.POST)
    month = parse_month(request.POST.get("month"))
    currency = request.POST.get("currency", "EUR").upper()
    if form.is_valid():
        household.default_split_a_basis_points = form.cleaned_data["partner_a_percent"] * 100
        household.save(update_fields=["default_split_a_basis_points"])
        messages.success(request, "The household split ratio has been updated.")
    else:
        messages.error(request, "Choose a split between 0% and 100%.")
    return redirect(dashboard_url(month, currency))


def record_payment(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect("ledger:dashboard")
    household = get_household()
    month = parse_month(request.POST.get("month"))
    currency = request.POST.get("currency", "EUR").upper()
    end = next_month(month)
    queryset = household.transactions.filter(
        transaction_date__gte=month,
        transaction_date__lt=end,
        currency=currency,
    )
    summary = calculate_settlement(queryset, household.default_split_a_basis_points)
    settlement, _ = Settlement.objects.update_or_create(
        household=household,
        month=month,
        currency=currency,
        defaults={
            "split_a_basis_points": household.default_split_a_basis_points,
            "total_minor": summary["total"],
            "paid_a_minor": summary["paid_a"],
            "paid_b_minor": summary["paid_b"],
            "payer": summary["payer"],
            "amount_due_minor": summary["amount_due"],
        },
    )
    already_paid = settlement.payments.aggregate(total=Sum("amount_minor"))["total"] or 0
    outstanding = max(int(summary["amount_due"]) - int(already_paid), 0)
    form_data = request.POST.copy()
    form_data["amount_minor"] = outstanding
    form_data["payer"] = summary["payer"]
    form = PaymentForm(form_data)
    if outstanding and form.is_valid():
        Payment.objects.create(
            settlement=settlement,
            payer=form.cleaned_data["payer"],
            amount_minor=form.cleaned_data["amount_minor"],
            paid_on=form.cleaned_data["paid_on"],
            note=form.cleaned_data["note"],
        )
        messages.success(request, "The settlement payment has been recorded.")
    elif not outstanding:
        messages.info(request, "This settlement is already fully paid.")
    else:
        messages.error(request, "Choose a valid payment date.")
    return redirect(dashboard_url(month, currency))


def disable_rule(request: HttpRequest, rule_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("ledger:dashboard")
    household = get_household()
    rule = get_object_or_404(ExclusionRule, pk=rule_id, household=household)
    rule.active = False
    rule.save(update_fields=["active"])
    messages.success(request, f"The rule for {rule.display_value} has been disabled.")
    month = parse_month(request.POST.get("month"))
    currency = request.POST.get("currency", "EUR").upper()
    return redirect(dashboard_url(month, currency))
