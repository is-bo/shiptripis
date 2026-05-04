from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    GoogleSignInView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    SignInView,
    SignOutView,
    SignUpView,
)

urlpatterns = [
    path("auth/sign-up", SignUpView.as_view(), name="auth-sign-up"),
    path("auth/sign-in", SignInView.as_view(), name="auth-sign-in"),
    path("auth/sign-out", SignOutView.as_view(), name="auth-sign-out"),
    path("auth/refresh", TokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/oauth/google", GoogleSignInView.as_view(), name="auth-oauth-google"),
    path(
        "auth/password/reset/request",
        PasswordResetRequestView.as_view(),
        name="auth-password-reset-request",
    ),
    path(
        "auth/password/reset/confirm",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    path("me", MeView.as_view(), name="me"),
]
