from django.db import migrations, models
import django.db.models.deletion


def assign_terms_to_shifts(apps, schema_editor):
    from django.db.models import Q

    Shift = apps.get_model("shifts", "Shift")
    WorkplaceContract = apps.get_model("workplaces", "WorkplaceContract")
    ContractTermSet = apps.get_model("workplaces", "ContractTermSet")

    updates = []
    for shift in Shift.objects.select_related("workplace"):
        contract = (
            WorkplaceContract.objects.filter(
                workplace=shift.workplace,
                start_date__lte=shift.date,
            )
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=shift.date))
            .order_by("-start_date")
            .first()
        )
        if contract is None:
            contract = (
                WorkplaceContract.objects.filter(workplace=shift.workplace)
                .order_by("start_date")
                .first()
            )
        if contract is None:
            continue

        terms = (
            ContractTermSet.objects.filter(
                contract=contract,
                effective_from__lte=shift.date,
            )
            .order_by("-effective_from")
            .first()
        )
        if terms is None:
            terms = (
                ContractTermSet.objects.filter(contract=contract)
                .order_by("effective_from")
                .first()
            )

        shift.terms_id = terms.pk if terms else None
        updates.append(shift)

    Shift.objects.bulk_update(updates, ["terms_id"])


def reverse_terms(apps, schema_editor):
    Shift = apps.get_model("shifts", "Shift")
    Shift.objects.update(terms=None)


class Migration(migrations.Migration):

    dependencies = [
        ("shifts", "0001_initial"),
        ("workplaces", "0004_workplacecontract_contracttermset"),
    ]

    operations = [
        migrations.AddField(
            model_name="shift",
            name="terms",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="shifts",
                to="workplaces.contracttermset",
                help_text="Employment terms active when this shift was worked.",
            ),
        ),
        migrations.RunPython(assign_terms_to_shifts, reverse_code=reverse_terms),
    ]
