"""Blocking another member (App Store 1.2). The one home of the rule.

A member blocks the other party of one of their own matches, from the chat.
While either of two members blocks the other (`blocked_between`):

- neither can send a chat message to the other (`apps.matching.services.
  chat_eligibility` answers `blocked`), and their conversation stays readable;
- neither can propose to the other, counter or accept the other's proposal
  (`apps.matching.v1_services`), or tell the other "I can carry this"
  (`apps.discovery.interest`).

A delivery that is already funded goes on unchanged: the pickup and delivery
codes, progress, problem reports and disputes do not need the chat, and money
never depends on a block. Only the blocker can lift their block.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Q

from .models import UserBlock


def blocked_between(first_id: int, second_id: int) -> bool:
    """Whether either member blocks the other."""

    return UserBlock.objects.filter(
        Q(blocker_id=first_id, blocked_id=second_id)
        | Q(blocker_id=second_id, blocked_id=first_id)
    ).exists()


def blocks(blocker_id: int, blocked_id: int) -> bool:
    """Whether ``blocker_id`` blocks ``blocked_id`` (one direction)."""

    return UserBlock.objects.filter(blocker_id=blocker_id, blocked_id=blocked_id).exists()


def block(*, blocker, blocked_id: int) -> tuple[UserBlock, bool]:
    """Record the block once. Returns `(block, created)`; a repeat is a no-op."""

    existing = UserBlock.objects.filter(blocker=blocker, blocked_id=blocked_id).first()
    if existing is not None:
        return existing, False
    try:
        with transaction.atomic():
            return UserBlock.objects.create(blocker=blocker, blocked_id=blocked_id), True
    except IntegrityError:
        return UserBlock.objects.get(blocker=blocker, blocked_id=blocked_id), False


def unblock(*, blocker, blocked_id: int) -> bool:
    """Lift the block. Returns whether there was one."""

    deleted, _ = UserBlock.objects.filter(blocker=blocker, blocked_id=blocked_id).delete()
    return bool(deleted)
