from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workplaces", "0002_add_payrate_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="workplace",
            name="contract_start_date",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Date the employment contract starts. Used for income projections.",
            ),
        ),
        migrations.AddField(
            model_name="workplace",
            name="contract_end_date",
            field=models.DateField(
                blank=True,
                null=True,
                help_text=(
                    "Expected end date of the contract (optional). If set, this workplace "
                    "earns nothing in months after this date."
                ),
            ),
        ),
    ]
