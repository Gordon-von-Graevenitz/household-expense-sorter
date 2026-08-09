from pathlib import Path

from django import forms

from .models import Partner


class UploadStatementForm(forms.Form):
    partner = forms.ChoiceField(choices=Partner.choices, widget=forms.HiddenInput)
    statement = forms.FileField()
    currency = forms.CharField(min_length=3, max_length=3, initial="EUR")
    expense_direction = forms.ChoiceField(
        choices=[
            ("auto", "Detect automatically"),
            ("negative", "Negative amounts are expenses"),
            ("positive", "Positive amounts are expenses"),
        ],
        initial="auto",
    )

    def clean_statement(self):
        statement = self.cleaned_data["statement"]
        suffix = Path(statement.name).suffix.lower()
        if suffix not in {".csv", ".xlsx"}:
            raise forms.ValidationError("Upload a CSV or XLSX file.")
        if statement.size > 10 * 1024 * 1024:
            raise forms.ValidationError("The statement must be 10 MB or smaller.")
        return statement

    def clean_currency(self):
        currency = self.cleaned_data["currency"].strip().upper()
        if not currency.isalpha():
            raise forms.ValidationError("Use a three-letter currency code, such as EUR.")
        return currency


class RatioForm(forms.Form):
    partner_a_percent = forms.IntegerField(min_value=0, max_value=100)


class PaymentForm(forms.Form):
    paid_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    amount_minor = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    payer = forms.ChoiceField(choices=Partner.choices, widget=forms.HiddenInput)
    note = forms.CharField(max_length=255, required=False)
