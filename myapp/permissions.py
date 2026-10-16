from rest_framework import permissions

class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS or request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        owner = getattr(obj, 'user', None)
        if owner is None and hasattr(obj, 'order'):
            owner = getattr(obj.order, 'user', None)
        if owner is None and hasattr(obj, 'seller'):
            owner = getattr(obj, 'seller', None)

        return owner == request.user