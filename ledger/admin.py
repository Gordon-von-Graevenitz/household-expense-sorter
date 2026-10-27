from django.contrib import admin

from .models import ExclusionRule, Household, ImportBatch, Payment, Settlement, Transaction


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("name", "partner_a_name", "partner_b_name", "default_split_a_basis_points")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_date",
        "description",
        "partner",
        "amount_minor",
        "currency",
        "included",
    )
    list_filter = ("partner", "currency", "included", "category")
    search_fields = ("description", "normalized_description", "reference")


admin.site.register(ImportBatch)
admin.site.register(ExclusionRule)
admin.site.register(Settlement)
admin.site.register(Payment)
