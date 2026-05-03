from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class ShipTripUserAdmin(UserAdmin):
    list_display = ("email", "role", "is_phone_verified", "is_kyc_verified", "is_staff")
    list_filter = ("role", "is_phone_verified", "is_kyc_verified", "is_staff")
    search_fields = ("email", "phone", "username")
    ordering = ("email",)
