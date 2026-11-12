import random
import re

from django import forms
from django.conf import settings

from .content import ADJECTIVES, ANIMALS

NICKNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{1,19}$")


class AnonymousEntryForm(forms.Form):
    nickname = forms.CharField(required=False, max_length=20)
    age_confirmed = forms.BooleanField(
        error_messages={"required": f"You must be {settings.MIN_AGE} or older to continue."})
    rules_accepted = forms.BooleanField(
        error_messages={"required": "Please accept the community rules."})

    def clean_nickname(self):
        nick = " ".join((self.cleaned_data.get("nickname") or "").split())
        if not nick:
            return f"{random.choice(ADJECTIVES)} {random.choice(ANIMALS)}"
        if not NICKNAME_RE.match(nick):
            raise forms.ValidationError(
                "Use 2–20 letters, numbers, spaces, dots, dashes or underscores.")
        return nick


from .services import GENDERS, VISIBILITY  # noqa: E402

MAX_PHOTO_BYTES = 2 * 1024 * 1024


def sniff_image(data):
    """Return a content type if `data` really is a JPEG/PNG/WebP, else None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ProfileForm(forms.Form):
    nickname = forms.CharField(max_length=20)
    age = forms.IntegerField(min_value=settings.MIN_AGE, max_value=99, error_messages={
        "min_value": f"You must be {settings.MIN_AGE} or older.", "required": "Enter your age."})
    gender = forms.ChoiceField(choices=GENDERS)
    bio = forms.CharField(max_length=160, widget=forms.Textarea(attrs={"rows": 2}))
    interests = forms.CharField(max_length=200, help_text="Comma separated, up to 8.")
    visibility = forms.ChoiceField(choices=VISIBILITY)
    photo = forms.FileField(required=False)
    remove_photo = forms.BooleanField(required=False)

    def clean_nickname(self):
        nick = " ".join(self.cleaned_data["nickname"].split())
        if not NICKNAME_RE.match(nick):
            raise forms.ValidationError("Use 2–20 letters, numbers, spaces, dots, dashes or underscores.")
        return nick

    def clean_bio(self):
        bio = " ".join(self.cleaned_data["bio"].split())
        if not bio:
            raise forms.ValidationError("Write a short bio.")
        return bio

    def clean_interests(self):
        items = []
        for part in self.cleaned_data["interests"].split(","):
            part = " ".join(part.lower().split())[:24]
            if part and part not in items:
                items.append(part)
        if not items:
            raise forms.ValidationError("Add at least one interest.")
        return items[:8]

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo:
            return None
        if photo.size > MAX_PHOTO_BYTES:
            raise forms.ValidationError("Photo must be under 2 MB.")
        data = photo.read()
        ctype = sniff_image(data)
        if not ctype:
            raise forms.ValidationError("Use a JPEG, PNG or WebP image.")
        return {"data": data, "content_type": ctype}
