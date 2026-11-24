"""A member's profile photo on the person page, and removing it (P3A, spec 21).

A photo is public the moment a member stores it; nobody checks it first. The
person page shows it in the header to anyone who can open the page, because
anyone at all can already see it in the app. One audited action: staff with
`moderate_profile_photos` remove it with a reason, which the member is shown.
The rule is `apps.accounts.photos.remove_by_staff`.

The form carries the version of the photo the operator was shown, so a photo
the member replaced meanwhile is never removed unseen: the page reloads with
the new one and the operator decides again.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.accounts.models import ProfilePhoto
from apps.accounts.photos import (
    MODERATE_PERMISSION,
    PHOTO_CHANGED,
    PhotoRefused,
    remove_by_staff,
    signed_url,
)

from .console_forms import ConsoleForm
from .people_links import display_name
from .permissions import has_admin_permission

User = get_user_model()


class PhotoRemovalForm(ConsoleForm):
    #: The photo the page showed. Removal applies only while it is still the one.
    version = forms.CharField(max_length=32, widget=forms.HiddenInput)
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="The member sees this reason on their profile. It is also kept in the audit log.",
    )


def photo_summary(request, person) -> dict:
    """The photo as the person page shows it: the image, or the removal record.

    One query. ``remove_url`` is set only for staff who may remove it, and
    only while there is an active photo to remove.
    """

    photo = (
        ProfilePhoto.objects.select_related("removed_by").filter(user=person).first()
    )
    if photo is None:
        return {"state": "none"}
    if photo.state == ProfilePhoto.State.REMOVED:
        return {
            "state": "removed",
            "removed_at": photo.removed_at,
            "removed_by": photo.removed_by.email if photo.removed_by else "—",
            "reason": photo.removed_reason,
        }
    return {
        "state": "active",
        # `public_photo` publishes it only for an active, unbanned account.
        "public": person.is_active and not person.is_banned,
        "url": signed_url(photo),
        "uploaded_at": photo.uploaded_at,
        "remove_url": (
            reverse("admin_console:user-photo-remove", args=(person.pk,))
            if has_admin_permission(request.user, MODERATE_PERMISSION)
            else None
        ),
    }


def photo_remove(request, pk: int):
    """Remove a member's photo with a reason. `moderate_profile_photos`, audited."""

    from .console_views import _render

    person = get_object_or_404(User, pk=pk)
    back = reverse("admin_console:user-detail", args=(person.pk,))
    photo = ProfilePhoto.objects.filter(user=person, state=ProfilePhoto.State.ACTIVE).first()
    form = PhotoRemovalForm(
        request.POST or None, initial={"version": photo.version if photo else ""}
    )
    if request.method == "POST" and photo is not None and form.is_valid():
        try:
            remove_by_staff(
                user=person,
                actor=request.user,
                version=form.cleaned_data["version"],
                reason=form.cleaned_data["reason"],
            )
        except PhotoRefused as exc:
            if exc.code == PHOTO_CHANGED:
                messages.error(
                    request,
                    "The member changed their photo after this page was opened. "
                    "Nothing was removed: look at the new photo.",
                )
                return redirect(request.path)
            messages.error(request, f"{exc.detail} Nothing was changed.")
            return redirect(back)
        messages.success(
            request,
            "The photo is removed. Nobody sees it any more; the member sees your reason.",
        )
        return redirect(back)
    preview = None
    if photo is not None:
        preview = {
            "url": signed_url(photo),
            "alt": f"Profile photo of {display_name(person)}",
        }
    who = f"{display_name(person)} (person {person.pk})"
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": "Remove photo",
            "description": (
                f"The photo of {who} disappears from Wassla at once, for everyone, and "
                "the stored image is deleted. The member sees that Wassla removed it, "
                "with your reason, and may add a different photo."
                if photo is not None
                else f"{who} has no photo to remove."
            ),
            "form": form if photo is not None else None,
            "preview": preview,
            "submit_label": "Remove photo",
            "danger": True,
            "back_url": back,
        },
    )
