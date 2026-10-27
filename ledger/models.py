from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class Partner(models.TextChoices):
    A = "A", "Partner A"
    B = "B", "Partner B"


class Household(models.Model):
    name = models.CharField(max_length=120, default="Our household")
    partner_a_name = models.CharField(max_length=80, default="Partner A")
    partner_b_name = models.CharField(max_length=80, default="Partner B")
    default_split_a_basis_points = models.PositiveSmallIntegerField(
        default=5000,
        validators=[MinValueValidator(0), MaxValueValidator(10000)],
        help_text="Partner A's share where 10,000 represents 100%.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def partner_name(self, partner):
        return self.partner_a_name if partner == Partner.A else self.partner_b_name


class ExclusionRule(models.Model):
    class MatchType(models.TextChoices):
        EXACT_MERCHANT = "exact_merchant", "Exact merchant"
        CATEGORY = "category", "Category"

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="rules")
    match_type = models.CharField(max_length=24, choices=MatchType.choices)
    match_value = models.CharField(max_length=255)
    display_value = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "match_type", "match_value"],
                name="unique_household_exclusion_rule",
            )
        ]

    def __str__(self):
        return f"{self.get_match_type_display()}: {self.display_value}"


class ImportBatch(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="imports")
    partner = models.CharField(max_length=1, choices=Partner.choices)
    original_filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64)
    currency = models.CharField(max_length=3)
    row_count = models.PositiveIntegerField(default=0)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-imported_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "partner", "file_hash"],
                name="unique_partner_statement_file",
            )
        ]

    def __str__(self):
        return f"{self.get_partner_display()} — {self.original_filename}"


class Transaction(models.Model):
    import_batch = models.ForeignKey(
        ImportBatch, on_delete=models.CASCADE, related_name="transactions"
    )
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="transactions")
    partner = models.CharField(max_length=1, choices=Partner.choices)
    transaction_date = models.DateField()
    description = models.CharField(max_length=255)
    normalized_description = models.CharField(max_length=255)
    reference = models.CharField(max_length=500, blank=True)
    category = models.CharField(max_length=100, default="Uncategorised")
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    included = models.BooleanField(default=True)
    exclusion_reason = models.CharField(max_length=255, blank=True)
    auto_excluded_by = models.ForeignKey(
        ExclusionRule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="matched_transactions",
    )
    source_row = models.PositiveIntegerField()
    fingerprint = models.CharField(max_length=64, db_index=True)
    split_a_basis_points = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10000)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["transaction_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["import_batch", "source_row"],
                name="unique_source_row_per_import",
            ),
            models.CheckConstraint(
                condition=Q(amount_minor__gt=0),
                name="transaction_amount_is_positive",
            ),
        ]

    def __str__(self):
        return f"{self.transaction_date}: {self.description}"


class Settlement(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="settlements")
    month = models.DateField(help_text="First day of the settlement month.")
    currency = models.CharField(max_length=3)
    split_a_basis_points = models.PositiveSmallIntegerField()
    total_minor = models.PositiveBigIntegerField()
    paid_a_minor = models.PositiveBigIntegerField()
    paid_b_minor = models.PositiveBigIntegerField()
    payer = models.CharField(max_length=1, choices=Partner.choices, blank=True)
    amount_due_minor = models.PositiveBigIntegerField(default=0)
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-month", "currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "month", "currency"],
                name="unique_monthly_currency_settlement",
            )
        ]

    def __str__(self):
        return f"{self.month:%B %Y} ({self.currency})"


class Payment(models.Model):
    settlement = models.ForeignKey(Settlement, on_delete=models.CASCADE, related_name="payments")
    payer = models.CharField(max_length=1, choices=Partner.choices)
    amount_minor = models.PositiveBigIntegerField()
    paid_on = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]

    def __str__(self):
        return f"{self.get_payer_display()} paid {self.amount_minor} on {self.paid_on}"
