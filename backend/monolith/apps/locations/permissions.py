from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsLocationCreatorOrReadOnly(BasePermission):
    """Future-safe object permission for this create/read-only API.

    Phase 1 intentionally exposes no update or delete endpoint. If a mutable
    action is added later, this permission prevents ownership from being used
    as a substitute for the identity of the actor who created the record.
    """

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return obj.created_by_id == request.user.id
