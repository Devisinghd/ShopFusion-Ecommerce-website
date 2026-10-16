
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import api, views

router = DefaultRouter()
router.register(r'products', views.ProductViewSet, basename='product')
router.register(r'orders', views.OrderViewSet, basename='order')
router.register(r'order-items', views.OrderItemViewSet, basename='orderitem')
router.register(r'addresses', views.AddressViewSet, basename='address')

urlpatterns = [
    path('', views.index, name='index'),
    path('product/<slug:slug>/', views.detail, name='detail'),

    path('api/auth/register/', api.RegisterAPIView.as_view(), name='api-register'),
    path('api/auth/verify-email/', api.VerifyEmailAPIView.as_view(), name='api-verify-email'),
    path('api/profile/', api.ProfileAPIView.as_view(), name='api-profile'),
    path('api/cart/quote/', api.CartQuoteAPIView.as_view(), name='api-cart-quote'),
    path('api/checkout/', api.CheckoutAPIView.as_view(), name='api-checkout'),
    path(
        'api/orders/<int:order_id>/start-payment/',
        api.StartOrderPaymentAPIView.as_view(),
        name='api-order-start-payment',
    ),
    path(
        'api/orders/<int:order_id>/verify-payment/',
        api.VerifyOrderPaymentAPIView.as_view(),
        name='api-order-verify-payment',
    ),
    path(
        'api/orders/<int:order_id>/cancel/',
        api.CancelOrderAPIView.as_view(),
        name='api-order-cancel',
    ),
    path('api/', include(router.urls)),
    path('api/token/', TokenObtainPairView.as_view(), name='api-token-obtain'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='api-token-refresh'),
]