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


class UserProfile(models.Model):
    uid = models.CharField(max_length=128, primary_key=True)         
    email = models.CharField(max_length=254, blank=True, default="")
    nickname = models.CharField(max_length=20, blank=True, default="")
    nickname_lower = models.CharField(max_length=20, blank=True, default="", db_index=True)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, default="")
    bio = models.CharField(max_length=160, blank=True, default="")
    interests = models.JSONField(default=list, blank=True)
    visibility = models.CharField(max_length=10, default="public")
    photo_url = models.CharField(max_length=300, blank=True, default="")
    created_at = models.BigIntegerField(null=True, blank=True)

    def __str__(self):
        return self.nickname or self.uid


class Block(models.Model):
    owner = models.CharField(max_length=128, db_index=True)
    blocked = models.CharField(max_length=128)

    class Meta:
        unique_together = [("owner", "blocked")]


class FriendRequest(models.Model):
    rid = models.CharField(max_length=300, primary_key=True)         
    from_uid = models.CharField(max_length=128, db_index=True)
    to_uid = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=10)                         
    ts = models.BigIntegerField(default=0)


class Friendship(models.Model):
    user_a = models.CharField(max_length=128, db_index=True)          # always the smaller id
    user_b = models.CharField(max_length=128, db_index=True)

    class Meta:
        unique_together = [("user_a", "user_b")]


class Notification(models.Model):
    uid = models.CharField(max_length=128, db_index=True)
    type = models.CharField(max_length=30)
    from_uid = models.CharField(max_length=128, blank=True, default="")
    text = models.CharField(max_length=300)
    ts = models.BigIntegerField(db_index=True)
    read = models.BooleanField(default=False)


class Conversation(models.Model):
    cid = models.CharField(max_length=300, primary_key=True)          # "<smaller id>__<larger id>"
    user_a = models.CharField(max_length=128, db_index=True)
    user_b = models.CharField(max_length=128, db_index=True)
    last_message = models.CharField(max_length=100, blank=True, default="")
    last_ts = models.BigIntegerField(default=0)
    last_sender = models.CharField(max_length=128, blank=True, default="")
    unread_a = models.PositiveIntegerField(default=0)
    unread_b = models.PositiveIntegerField(default=0)
    cleared_a = models.BigIntegerField(default=0)                     # "delete conversation" timestamps
    cleared_b = models.BigIntegerField(default=0)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=128)
    text = models.TextField()
    ts = models.BigIntegerField(db_index=True)

    class Meta:
        ordering = ["ts", "id"]