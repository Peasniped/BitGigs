"""Fill the configured database with the demo dataset (see core.demo_data).

Destructive: it replaces the workplaces, contracts, shifts, payroll, tax
profiles and user accounts in whichever database settings point at. It prints
that database and asks before touching anything, because "which settings module
am I on" is exactly the mistake this would make expensive.

    python manage.py seed_demo_data --settings=config.settings.local
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.demo_data import (
    DEFAULT_EMAIL, DEFAULT_NAME, DEFAULT_PASSWORD, DEFAULT_SEED, build_demo_data,
)


class Command(BaseCommand):
    help = (
        "Replace all data with a generated demo dataset for screenshots and demos."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--noinput", "--no-input", action="store_false", dest="interactive",
            help="Skip the confirmation prompt.",
        )
        parser.add_argument(
            "--seed", type=int, default=DEFAULT_SEED,
            help=f"Random seed, so a run is reproducible (default {DEFAULT_SEED}).",
        )
        parser.add_argument("--email", default=DEFAULT_EMAIL, help="Demo account e-mail.")
        parser.add_argument(
            "--password", default=DEFAULT_PASSWORD, help="Demo account password.",
        )
        parser.add_argument(
            "--name", default=DEFAULT_NAME, help="Display name used in greetings.",
        )
        parser.add_argument(
            "--skip-payroll", action="store_true",
            help="Don't generate payroll periods and payslip lines (much faster).",
        )

    def handle(self, *args, **options):
        target = connection.settings_dict
        where = target.get("NAME") or "(unnamed)"
        self.stdout.write(
            f"This replaces ALL data in {connection.vendor} database:\n  {where}\n"
        )

        if options["interactive"]:
            try:
                answer = input("Type 'yes' to continue: ")
            except EOFError:
                # Piped or scripted without --noinput: refuse rather than let a
                # traceback stand in for "are you sure".
                raise CommandError(
                    "No terminal to confirm on — re-run with --noinput if you "
                    "meant to replace the data."
                )
            if answer.strip().lower() != "yes":
                raise CommandError("Cancelled — nothing was changed.")

        result = build_demo_data(
            seed=options["seed"],
            email=options["email"],
            password=options["password"],
            name=options["name"],
            with_payroll=not options["skip_payroll"],
        )

        self.stdout.write(self.style.SUCCESS("Demo data written."))
        self.stdout.write(
            f"  {result.workplaces} workplaces, {result.contracts} contracts, "
            f"{result.term_sets} term sets"
        )
        self.stdout.write(
            f"  {result.approved} approved shifts, {result.pending} awaiting "
            f"approval, {result.planned} planned"
        )
        if result.periods:
            self.stdout.write(f"  {result.periods} payroll periods")
        self.stdout.write(f"  {result.first_day} → {result.last_day}")
        self.stdout.write(
            f"\nSign in as {options['email']} / {options['password']}"
        )
