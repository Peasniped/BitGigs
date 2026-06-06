from django.db import migrations, models


def copy_defaults_to_workplace(apps, schema_editor):
    Workplace = apps.get_model("workplaces", "Workplace")
    ContractTermSet = apps.get_model("workplaces", "ContractTermSet")
    for wp in Workplace.objects.all():
        ts = (
            ContractTermSet.objects.filter(contract__workplace=wp)
            .order_by("-effective_from")
            .first()
        )
        if ts is None:
            continue
        wp.default_shift_start_time = ts.default_shift_start_time
        wp.default_shift_end_time = ts.default_shift_end_time
        wp.default_shift_break_minutes = ts.default_shift_break_minutes
        wp.default_shift_type = ts.default_shift_type
        wp.save(update_fields=[
            "default_shift_start_time",
            "default_shift_end_time",
            "default_shift_break_minutes",
            "default_shift_type",
        ])


class Migration(migrations.Migration):

    dependencies = [
        ("workplaces", "0006_remove_workplace_is_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="workplace",
            name="default_shift_start_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workplace",
            name="default_shift_end_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workplace",
            name="default_shift_break_minutes",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="workplace",
            name="default_shift_type",
            field=models.CharField(
                default="on_site",
                max_length=15,
                choices=[
                    ("on_site", "On-site"),
                    ("remote", "Remote"),
                    ("sick_leave", "Sick leave (with pay)"),
                    ("paid_absence", "Paid absence"),
                    ("vacation", "Vacation"),
                ],
            ),
        ),
        migrations.RunPython(copy_defaults_to_workplace, migrations.RunPython.noop),
        migrations.RemoveField(model_name="contracttermset", name="default_shift_start_time"),
        migrations.RemoveField(model_name="contracttermset", name="default_shift_end_time"),
        migrations.RemoveField(model_name="contracttermset", name="default_shift_break_minutes"),
        migrations.RemoveField(model_name="contracttermset", name="default_shift_type"),
    ]
