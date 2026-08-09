from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def money_minor(value, currency="EUR"):
    try:
        amount = Decimal(int(value)) / Decimal(100)
    except (TypeError, ValueError):
        amount = Decimal(0)
    symbols = {"EUR": "€", "USD": "$", "GBP": "£"}
    symbol = symbols.get(currency, f"{currency} ")
    return f"{symbol}{amount:,.2f}"


@register.filter
def partner_name(household, partner):
    return household.partner_name(partner)
