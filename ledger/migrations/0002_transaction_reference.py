from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="reference",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
