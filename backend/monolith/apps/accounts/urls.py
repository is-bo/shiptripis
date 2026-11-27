from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .sessions import SessionTokenRefreshSerializer

from .views import (
    AccountDeletionView,
    AppleSignInView,
    GoogleSignInView,
    MePhotoView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ResendVerifyEmailView,
    SignInView,
    SignOutView,
    SignUpView,
    VerifyEmailView,
)

urlpatterns = [
    path("auth/sign-up", SignUpView.as_view(), name="auth-sign-up"),
    path("auth/sign-in", SignInView.as_view(), name="auth-sign-in"),
    path("auth/sign-out", SignOutView.as_view(), name="auth-sign-out"),
    path(
        "auth/refresh",
        TokenRefreshView.as_view(serializer_class=SessionTokenRefreshSerializer),
        name="auth-refresh",
    ),
    path("auth/oauth/google", GoogleSignInView.as_view(), name="auth-oauth-google"),
    path("auth/oauth/apple", AppleSignInView.as_view(), name="auth-oauth-apple"),
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
    path("auth/verify-email", VerifyEmailView.as_view(), name="auth-verify-email"),
    path(
        "auth/verify-email/resend",
        ResendVerifyEmailView.as_view(),
        name="auth-verify-email-resend",
    ),
    path("me", MeView.as_view(), name="me"),
    path("me/photo", MePhotoView.as_view(), name="me-photo"),
    path("me/deletion", AccountDeletionView.as_view(), name="me-deletion"),
]
