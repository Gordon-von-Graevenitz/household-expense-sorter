from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.upload_statement_view, name="upload"),
    path("transactions/<int:transaction_id>/", views.transaction_action, name="transaction_action"),
    path("ratio/", views.update_ratio, name="update_ratio"),
    path("payments/", views.record_payment, name="record_payment"),
    path("rules/<int:rule_id>/disable/", views.disable_rule, name="disable_rule"),
]
