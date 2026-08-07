from django.contrib.auth import authenticate, password_validation
from rest_framework import serializers

from apps.kyc.models import KycSubmission

from .models import User
from .wilayas import WILAYA_CODES


class SignUpSerializer(serializers.Serializer):
    full_name = serializers.CharField(min_length=2, max_length=120)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    phone = serializers.CharField(min_length=6, max_length=32)
    wilaya = serializers.CharField(min_length=2, max_length=2)

    def validate_email(self, value: str) -> str:
        normalized = value.lower().strip()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return normalized

    def validate_wilaya(self, value: str) -> str:
        if value not in WILAYA_CODES:
            raise serializers.ValidationError("Invalid wilaya code.")
        return value

    def validate_password(self, value: str) -> str:
        password_validation.validate_password(value)
        return value

    def create(self, validated_data: dict) -> User:
        user = User(
            email=validated_data["email"],
            username=validated_data["email"],
            full_name=validated_data["full_name"],
            phone=validated_data["phone"],
            wilaya=validated_data["wilaya"],
        )
        user.set_password(validated_data["password"])
        user.save()
        return user


class SignInSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs: dict) -> dict:
        email = attrs["email"].lower().strip()
        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=attrs["password"],
        )
        if user is None:
            raise serializers.ValidationError(
                {"detail": "Incorrect email or password."}
            )
        if not user.is_active:
            raise serializers.ValidationError(
                {"detail": "This account is disabled."}
            )
        attrs["user"] = user
        return attrs


class GoogleSignInSerializer(serializers.Serializer):
    id_token = serializers.CharField()
    # Optional fields used to populate a fresh User if Google didn't supply them.
    phone = serializers.CharField(required=False, allow_blank=True, max_length=32)
    wilaya = serializers.CharField(required=False, allow_blank=True, max_length=2)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(regex=r"^\d{6}$")
    new_password = serializers.CharField(min_length=8, max_length=128, write_only=True)

    def validate_new_password(self, value: str) -> str:
        password_validation.validate_password(value)
        return value


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(regex=r"^\d{6}$")


class MeSerializer(serializers.ModelSerializer):
    """Profile payload.

    `is_kyc_verified` stays the authority for *access* — one source of truth
    for "may this user transact". `kyc_status` exists purely so the UI can say
    something true: without it a user who submitted an hour ago is
    indistinguishable from one who never started, so the app would keep
    prompting them to verify and they'd re-upload to no effect.
    """

    kyc_status = serializers.SerializerMethodField()
    kyc_rejection_reason = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "phone",
            "wilaya",
            "role",
            "is_phone_verified",
            "is_email_verified",
            "is_kyc_verified",
            "kyc_status",
            "kyc_rejection_reason",
            "date_joined",
        )
        read_only_fields = fields

    def _latest_submission(self, obj: User):
        # Cached per serialization so the two method fields don't each query.
        if not hasattr(obj, "_latest_kyc"):
            obj._latest_kyc = obj.kyc_submissions.order_by("-created_at").first()
        return obj._latest_kyc

    def get_kyc_status(self, obj: User) -> str:
        if obj.is_kyc_verified:
            return "verified"
        sub = self._latest_submission(obj)
        if sub is None:
            return "unverified"
        if sub.status == KycSubmission.Status.PENDING:
            return "pending"
        if sub.status == KycSubmission.Status.REJECTED:
            return "rejected"
        # approved-but-boolean-not-set shouldn't happen (approval flips both),
        # and `expired` means they must start over — both read as "unverified".
        return "unverified"

    def get_kyc_rejection_reason(self, obj: User) -> str | None:
        sub = self._latest_submission(obj)
        if sub is not None and sub.status == KycSubmission.Status.REJECTED:
            return sub.rejection_reason or ""
        return None
