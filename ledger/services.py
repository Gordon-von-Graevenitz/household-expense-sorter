from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from django.db import IntegrityError, transaction
from django.db.models import Sum

from .models import ExclusionRule, Household, ImportBatch, Partner, Transaction

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class ImportProblem(ValueError):
    pass


class DuplicateImport(ImportProblem):
    pass


@dataclass(frozen=True)
class ImportResult:
    batch: ImportBatch
    imported: int
    skipped: int
    first_date: date


def normalize_merchant(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def _normalize_column(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


COLUMN_ALIASES = {
    "date": {
        "date",
        "transactiondate",
        "bookingdate",
        "bookingday",
        "valuedate",
        "datum",
        "buchungstag",
        "valuta",
    },
    "description": {
        "description",
        "merchant",
        "payee",
        "details",
        "name",
        "memo",
        "reference",
        "verwendungszweck",
        "empfaenger",
        "zahlungsempfaenger",
        "beguenstigter",
    },
    "amount": {
        "amount",
        "transactionamount",
        "value",
        "betrag",
        "debit",
        "withdrawal",
        "umsatz",
    },
    "category": {"category", "transactioncategory", "kategorie", "type"},
    "currency": {"currency", "currencycode", "waehrung", "wahrung"},
}


def _find_columns(frame: pd.DataFrame) -> dict[str, str | None]:
    normalized = {_normalize_column(column): str(column) for column in frame.columns}
    found: dict[str, str | None] = {}
    for field, aliases in COLUMN_ALIASES.items():
        found[field] = next((normalized[alias] for alias in aliases if alias in normalized), None)
    missing = [field for field in ("date", "description", "amount") if not found[field]]
    if missing:
        available = ", ".join(str(column) for column in frame.columns)
        missing_names = ", ".join(missing)
        raise ImportProblem(
            f"Could not identify the {missing_names} column(s). Available columns: {available}."
        )
    return found


def _read_statement(filename: str, content: bytes) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        text = None
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ImportProblem("The CSV encoding could not be read.")
        try:
            return pd.read_csv(
                io.StringIO(text), sep=None, engine="python", dtype=str, keep_default_na=False
            )
        except Exception as exc:
            raise ImportProblem("The CSV could not be parsed.") from exc
    if suffix == ".xlsx":
        try:
            return pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl")
        except Exception as exc:
            raise ImportProblem("The XLSX workbook could not be parsed safely.") from exc
    raise ImportProblem("Only CSV and XLSX statements are supported.")


def _parse_amount(raw_value: object) -> Decimal:
    value = str(raw_value).strip()
    if not value:
        raise InvalidOperation
    negative_parentheses = value.startswith("(") and value.endswith(")")
    value = re.sub(r"[^0-9,.'+\-]", "", value).replace("'", "")
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        tail = value.rsplit(",", 1)[-1]
        value = value.replace(",", ".") if len(tail) in {1, 2} else value.replace(",", "")
    elif value.count(".") > 1:
        value = value.replace(".", "")
    amount = Decimal(value)
    return -amount if negative_parentheses and amount > 0 else amount


def _resolve_direction(amounts: list[Decimal], requested: str) -> str:
    if requested != "auto":
        return requested
    return "negative" if any(amount < 0 for amount in amounts) else "positive"


def _matching_rule(household: Household, merchant: str, category: str):
    return (
        household.rules.filter(
            active=True,
        )
        .filter(models_q_exact_merchant(merchant) | models_q_category(category))
        .first()
    )


def models_q_exact_merchant(merchant: str):
    from django.db.models import Q

    return Q(match_type=ExclusionRule.MatchType.EXACT_MERCHANT, match_value=merchant)


def models_q_category(category: str):
    from django.db.models import Q

    return Q(match_type=ExclusionRule.MatchType.CATEGORY, match_value=category.upper())


def import_statement(
    *, household: Household, partner: str, uploaded_file, currency: str, expense_direction: str
) -> ImportResult:
    content = uploaded_file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ImportProblem("The statement must be 10 MB or smaller.")
    file_hash = hashlib.sha256(content).hexdigest()
    if ImportBatch.objects.filter(
        household=household, partner=partner, file_hash=file_hash
    ).exists():
        raise DuplicateImport("This exact statement has already been imported for this partner.")

    frame = _read_statement(uploaded_file.name, content)
    if frame.empty:
        raise ImportProblem("The statement contains no transaction rows.")
    columns = _find_columns(frame)

    parsed_rows = []
    parsed_amounts = []
    for index, row in frame.iterrows():
        try:
            amount = _parse_amount(row[columns["amount"]])
            parsed_amounts.append(amount)
            parsed_rows.append((index, row, amount))
        except (InvalidOperation, ValueError):
            continue
    if not parsed_rows:
        raise ImportProblem("No valid transaction amounts were found.")

    direction = _resolve_direction(parsed_amounts, expense_direction)
    prepared = []
    detected_currencies = set()
    skipped = 0
    for index, row, amount in parsed_rows:
        if (direction == "negative" and amount >= 0) or (direction == "positive" and amount <= 0):
            skipped += 1
            continue
        try:
            transaction_date = pd.to_datetime(
                str(row[columns["date"]]).strip(), dayfirst=True, errors="raise"
            ).date()
        except (ValueError, TypeError):
            skipped += 1
            continue
        description = str(row[columns["description"]]).strip()
        if not description:
            skipped += 1
            continue
        normalized = normalize_merchant(description)
        category = (
            str(row[columns["category"]]).strip() if columns["category"] else "Uncategorised"
        ) or "Uncategorised"
        row_currency = (
            str(row[columns["currency"]]).strip().upper() if columns["currency"] else currency
        ) or currency
        if len(row_currency) != 3 or not row_currency.isalpha():
            raise ImportProblem(f"Invalid currency value: {row_currency!r}.")
        detected_currencies.add(row_currency)
        amount_minor = int(
            (abs(amount) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        if amount_minor == 0:
            skipped += 1
            continue
        fingerprint = hashlib.sha256(
            f"{partner}|{transaction_date.isoformat()}|{normalized}|{amount_minor}|{row_currency}".encode()
        ).hexdigest()
        prepared.append(
            {
                "source_row": int(index) + 2,
                "date": transaction_date,
                "description": description[:255],
                "normalized": normalized[:255],
                "category": category[:100],
                "amount_minor": amount_minor,
                "currency": row_currency,
                "fingerprint": fingerprint,
            }
        )
    if not prepared:
        raise ImportProblem("No expenses matched the selected amount direction.")
    if len(detected_currencies) > 1:
        raise ImportProblem(
            "This statement contains multiple currencies. Import each currency separately."
        )

    batch_currency = detected_currencies.pop()
    try:
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                household=household,
                partner=partner,
                original_filename=Path(uploaded_file.name).name[:255],
                file_hash=file_hash,
                currency=batch_currency,
            )
            transactions = []
            for item in prepared:
                rule = _matching_rule(household, item["normalized"], item["category"])
                transactions.append(
                    Transaction(
                        import_batch=batch,
                        household=household,
                        partner=partner,
                        transaction_date=item["date"],
                        description=item["description"],
                        normalized_description=item["normalized"],
                        category=item["category"],
                        amount_minor=item["amount_minor"],
                        currency=item["currency"],
                        included=rule is None,
                        exclusion_reason=(
                            f"Matched saved rule: {rule.display_value}" if rule else ""
                        ),
                        auto_excluded_by=rule,
                        source_row=item["source_row"],
                        fingerprint=item["fingerprint"],
                    )
                )
            Transaction.objects.bulk_create(transactions)
            batch.row_count = len(transactions)
            batch.save(update_fields=["row_count"])
    except IntegrityError as exc:
        raise DuplicateImport("This exact statement has already been imported.") from exc
    return ImportResult(
        batch=batch,
        imported=len(prepared),
        skipped=skipped,
        first_date=min(item["date"] for item in prepared),
    )


def round_share(total_minor: int, basis_points: int) -> int:
    return int(
        (Decimal(total_minor) * Decimal(basis_points) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def calculate_settlement(queryset, split_a_basis_points: int) -> dict[str, int | str]:
    totals = {
        row["partner"]: row["total"]
        for row in queryset.filter(included=True)
        .values("partner")
        .annotate(total=Sum("amount_minor"))
    }
    paid_a = int(totals.get(Partner.A, 0) or 0)
    paid_b = int(totals.get(Partner.B, 0) or 0)
    total = paid_a + paid_b
    responsibility_a = round_share(total, split_a_basis_points)
    responsibility_b = total - responsibility_a
    balance_a = paid_a - responsibility_a
    if balance_a < 0:
        payer, receiver, amount_due = Partner.A, Partner.B, -balance_a
    elif balance_a > 0:
        payer, receiver, amount_due = Partner.B, Partner.A, balance_a
    else:
        payer = receiver = ""
        amount_due = 0
    return {
        "paid_a": paid_a,
        "paid_b": paid_b,
        "total": total,
        "responsibility_a": responsibility_a,
        "responsibility_b": responsibility_b,
        "payer": payer,
        "receiver": receiver,
        "amount_due": amount_due,
    }
