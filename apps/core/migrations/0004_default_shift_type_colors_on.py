from django.db import migrations, models


def enable_existing(apps, schema_editor):
    # The setting is now on by default; flip the existing singleton so current
    # installs pick it up too (the field is brand new, so nothing is overridden).
    UserSettings = apps.get_model("core", "UserSettings")
    UserSettings.objects.update(show_shift_type_colors=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_usersettings_show_shift_type_colors"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usersettings",
            name="show_shift_type_colors",
            field=models.BooleanField(
                default=True,
                help_text="Colour calendar shift chips by type (on-site / remote / sick / …).",
            ),
        ),
        migrations.RunPython(enable_existing, migrations.RunPython.noop),
    ]
