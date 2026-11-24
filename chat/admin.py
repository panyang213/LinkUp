from django.contrib import admin

from .models import Block, FriendRequest, Friendship, Report, UserProfile


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "reason", "reported_id")
    list_filter = ("reason",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("nickname", "age", "visibility", "uid")
    search_fields = ("nickname", "uid")
    exclude = ("email",)          # private: not shown, even to admins


admin.site.register(Friendship)
admin.site.register(FriendRequest)
admin.site.register(Block)
# Conversations and messages are deliberately NOT registered, so they aren't browsable in the admin.