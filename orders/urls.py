from django.urls import path
from . import views 
urlpatterns = [
    path('add-address/',views.add_address,name='add_address'),
    path('address-list/',views.address_list,name='address_list'),
    path('checkout/',views.checkout,name='checkout'),
    path('place-order/',views.place_order,name='place-order'),
    path('payment/<int:order_id>/', views.order_payment, name='order-payment'),
    path('payment/<int:order_id>/start/', views.start_payment, name='start-payment'),
    path('payment/callback/', views.payment_callback, name='payment-callback'),
    path('payment/webhook/', views.payment_webhook, name='payment-webhook'),
    path('order-success/',views.order_success,name='order-success'),
    path('order-failed/',views.order_failed,name='order-failed'),
    path('orderlist/',views.orders_view,name='order_view'),
    path('checkout-warning/',views.checkout_warning,name='checkout_warning'),
    path('cancel_order/<int:id>/',views.cancel_order,name='cancel_order'),
]
