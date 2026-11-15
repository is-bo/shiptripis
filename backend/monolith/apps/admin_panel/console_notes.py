"""Internal notes on the deal, dispute and person pages (plan L16).

Each of the three pages shows its notes, newest first, and a form to add one
for whoever may open the page. A note is append only and staff only. The rule
lives in `staff_actions.add_note`; this module renders the card and takes the
form's POST.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .console_forms import ConsoleForm
from .models import AdminNote
from .people_links import display_name
from .staff_actions import NOTE_TARGETS, StaffActionError, add_note, may_add_note, notes_for

#: Every capability that opens one of the three pages: the route's own gate.
#: The view then checks the one page the note is for.
NOTE_ROUTE_CAPABILITIES: tuple[str, ...] = tuple(
    dict.fromkeys(code for _model, codes in NOTE_TARGETS.values() for code in codes)
)
SHOWN = 50

_PAGES = {
    AdminNote.TargetType.DEAL: "admin_console:deal-detail",
    AdminNote.TargetType.DISPUTE: "admin_console:dispute-detail",
    AdminNote.TargetType.PERSON: "admin_console:user-detail",
}


class NoteForm(ConsoleForm):
    body = forms.CharField(
        max_length=AdminNote.BODY_MAX_LENGTH,
        label="Add an internal note",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Only staff see notes. A note cannot be edited or deleted, so write what a colleague needs to know.",
    )


def notes_panel(request, target_type: str, target_id: int) -> dict:
    """The notes card's context for one record."""

    notes = list(notes_for(target_type, target_id)[: SHOWN + 1])
    return {
        "target_type": target_type,
        "what": AdminNote.TargetType(target_type).label.lower(),
        "notes": [
            {
                "author": display_name(note.author),
                "at": note.created_at,
                "body": note.body,
                "via_helper": note.via_helper,
            }
            for note in notes[:SHOWN]
        ],
        "more": len(notes) > SHOWN,
        "may_add": may_add_note(request.user, target_type),
        "form": NoteForm(auto_id=f"id_note_{target_type}_%s"),
        "action": reverse("admin_console:note-add", args=(target_type, target_id)),
    }


@require_POST
def note_add(request, target_type: str, pk: int):
    if target_type not in NOTE_TARGETS:
        raise Http404
    if not may_add_note(request.user, target_type):
        raise PermissionDenied("Your staff role cannot open this page.")
    if not NOTE_TARGETS[target_type][0].objects.filter(pk=pk).exists():
        raise Http404
    back = f"{reverse(_PAGES[target_type], args=(pk,))}#st-notes"
    form = NoteForm(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(form.errors.get("body", ["Write the note first."])))
        return redirect(back)
    try:
        add_note(
            actor=request.user,
            target_type=target_type,
            target_id=pk,
            body=form.cleaned_data["body"],
        )
    except StaffActionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "The note is added. Only staff can see it.")
    return redirect(back)
