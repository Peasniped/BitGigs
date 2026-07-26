import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def migrate_singleton_to_connection(apps, schema_editor):
    """Move the existing SMTP config off the EmailSettings singleton into a first
    ``MailConnection`` named "Default", and point both roles at it — so upgrading
    changes nothing about how mail sends."""
    EmailSettings = apps.get_model("core", "EmailSettings")
    MailConnection = apps.get_model("core", "MailConnection")
    es = EmailSettings.objects.filter(pk=1).first()
    if es is None:
        return
    # Only bother when something was actually configured; a fresh install stays
    # connection-less (which reads as "mail off").
    if not (es.host or es.from_email or es.password_encrypted):
        return
    conn = MailConnection.objects.create(
        name="Default",
        host=es.host,
        port=es.port,
        security=es.security,
        username=es.username,
        password_encrypted=es.password_encrypted,
        from_email=es.from_email,
        from_name=es.from_name or "BitGigs",
        timeout=es.timeout,
        is_default=True,
        last_test_at=es.last_test_at,
        last_test_ok=es.last_test_ok,
    )
    es.system_connection = conn
    es.calendar_connection = conn
    es.save()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_remove_usersettings_money_mask_style_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="MailConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="A label to tell your setups apart, e.g. 'No-reply' or 'My mailbox'.", max_length=100)),
                ("host", models.CharField(blank=True, help_text="e.g. smtp.gmail.com", max_length=255)),
                ("port", models.PositiveIntegerField(default=587)),
                ("security", models.CharField(choices=[("starttls", "STARTTLS (usually port 587)"), ("ssl", "Implicit TLS / SSL (usually port 465)"), ("none", "None — unencrypted (not recommended)")], default="starttls", max_length=10)),
                ("username", models.CharField(blank=True, help_text="Leave blank if the server accepts mail without authenticating.", max_length=255)),
                ("password_encrypted", models.CharField(blank=True, max_length=512)),
                ("from_email", models.EmailField(blank=True, help_text="The address mail is sent from. Many providers require this to match the account you authenticate as.", max_length=254)),
                ("from_name", models.CharField(blank=True, default="BitGigs", help_text="Display name shown beside the from address.", max_length=100)),
                ("timeout", models.PositiveIntegerField(default=10, help_text="Seconds to wait for the server before giving up.", validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(120)])),
                ("is_default", models.BooleanField(default=False, help_text="Used for any role that isn't pointed at a specific setup.")),
                ("last_test_at", models.DateTimeField(blank=True, null=True)),
                ("last_test_ok", models.BooleanField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Mail connection",
                "verbose_name_plural": "Mail connections",
                "ordering": ["-is_default", "name", "pk"],
            },
        ),
        migrations.AddField(
            model_name="emailsettings",
            name="system_connection",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="core.mailconnection"),
        ),
        migrations.AddField(
            model_name="emailsettings",
            name="calendar_connection",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="core.mailconnection"),
        ),
        migrations.AddField(
            model_name="emaillog",
            name="connection_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.RunPython(migrate_singleton_to_connection, migrations.RunPython.noop),
        migrations.RemoveField(model_name="emailsettings", name="host"),
        migrations.RemoveField(model_name="emailsettings", name="port"),
        migrations.RemoveField(model_name="emailsettings", name="security"),
        migrations.RemoveField(model_name="emailsettings", name="username"),
        migrations.RemoveField(model_name="emailsettings", name="password_encrypted"),
        migrations.RemoveField(model_name="emailsettings", name="from_email"),
        migrations.RemoveField(model_name="emailsettings", name="from_name"),
        migrations.RemoveField(model_name="emailsettings", name="timeout"),
        migrations.RemoveField(model_name="emailsettings", name="last_test_at"),
        migrations.RemoveField(model_name="emailsettings", name="last_test_ok"),
    ]
