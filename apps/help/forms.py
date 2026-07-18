import re

from django import forms
from django.utils.text import slugify

from .models import HelpArticle, HelpKeyword, HelpPage


class HelpArticleForm(forms.ModelForm):
    """Editor form. Keywords are a comma/newline chip field parsed to
    ``HelpKeyword`` rows; pages are a checklist of the known page-contexts."""

    keywords_text = forms.CharField(
        required=False,
        label="Keywords",
        help_text="Comma-separated tags used by search.",
        widget=forms.TextInput(attrs={"data-help-keywords": "1"}),
    )
    pages = forms.ModelMultipleChoiceField(
        queryset=HelpPage.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Show on pages",
        help_text="Pages whose help popup surfaces this article.",
    )

    class Meta:
        model = HelpArticle
        fields = [
            "title",
            "slug",
            "summary",
            "parent",
            "body_md",
            "audience",
            "order",
            "is_published",
            "pages",
        ]
        widgets = {
            "body_md": forms.Textarea(attrs={"rows": 18, "id": "helpBodyInput"}),
            "summary": forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Leave blank to derive from the title."
        # Parent picker: any article except this one and its own descendants
        # (which would create a cycle).
        parent_qs = HelpArticle.objects.live()
        if self.instance and self.instance.pk:
            parent_qs = parent_qs.exclude(pk=self.instance.pk).exclude(
                pk__in=self.instance.descendant_ids()
            )
        self.fields["parent"].queryset = parent_qs.order_by("title")
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = "— None (top level) —"
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxSelectMultiple):
                continue
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
                continue
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = (css + " form-control").strip()
        self.fields["audience"].widget.attrs["class"] = "form-select"
        self.fields["parent"].widget.attrs["class"] = "form-select"
        if self.instance and self.instance.pk:
            self.fields["keywords_text"].initial = ", ".join(
                k.name for k in self.instance.keywords.all()
            )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("slug") and cleaned.get("title"):
            cleaned["slug"] = slugify(cleaned["title"])[:80]
            self.instance.slug = cleaned["slug"]
        return cleaned

    def save(self, commit=True):
        article = super().save(commit=commit)  # commit=True also saves `pages` m2m
        if commit:
            names = [
                n.strip()
                for n in re.split(r"[,\n]", self.cleaned_data.get("keywords_text", ""))
                if n.strip()
            ]
            article.keywords.set(
                [HelpKeyword.get_or_create_by_name(n) for n in names]
            )
        return article
