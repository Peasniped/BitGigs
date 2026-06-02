from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("workplaces", "0005_alter_contracttermset_ferietillaeg_payout_months_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="workplace",
            name="is_active",
        ),
    ]
