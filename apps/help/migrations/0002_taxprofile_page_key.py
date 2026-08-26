"""The tax-profile page moved from the ``core`` namespace to ``tax``.

``HelpPage`` rows are keyed by URL **view-name**, and ``sync_pages`` only ever
creates or updates — it never deletes — so without this the old
``core:taxprofile-list`` row would survive holding every article mapping, while
the page itself started asking for ``tax:taxprofile-list`` and got nothing. The
help popup would simply go quiet on that page, with no error anywhere.
"""
from django.db import migrations

OLD = "core:taxprofile-list"
NEW = "tax:taxprofile-list"


def _repoint(apps, old_key, new_key):
    HelpPage = apps.get_model("help", "HelpPage")
    old = HelpPage.objects.filter(key=old_key).first()
    if old is None:
        return
    target = HelpPage.objects.filter(key=new_key).first()
    if target is None:
        old.key = new_key
        old.save(update_fields=["key"])
        return
    # Both rows exist (sync_pages ran before this migration did): carry the
    # article mappings over to the surviving row rather than losing them.
    for article in old.articles.all():
        article.pages.add(target)
    old.delete()


def forwards(apps, schema_editor):
    _repoint(apps, OLD, NEW)


def backwards(apps, schema_editor):
    _repoint(apps, NEW, OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("help", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
