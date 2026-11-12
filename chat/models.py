from django.db import models


class Report(models.Model):
    """A voluntary abuse report.

    Only what the reporting user chooses to type is stored. Chat content is never
    captured automatically, and the ids below are random per-session tokens.
    """

    REASONS = [
        ("harassment", "Harassment or bullying"),
        ("sexual", "Sexual or explicit content"),
        ("spam", "Spam or scams"),
        ("underage", "Seems to be under 18"),
        ("other", "Something else"),
    ]

    reporter_id = models.CharField(max_length=64)
    reported_id = models.CharField(max_length=64)
    reason = models.CharField(max_length=20, choices=REASONS)
    details = models.TextField(blank=True, max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_reason_display()} ({self.created_at:%Y-%m-%d %H:%M})"
