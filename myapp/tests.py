from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from orders.models import Address, Order, OrderItem
from .models import Products


class StoreApiSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='api-customer',
            password='test-pass-123',
        )
        self.product = Products.objects.create(
            seller=self.user,
            name='API watch',
            price='120.00',
            description='API test product',
            image='images/api-watch.jpg',
            stock=4,
        )

    def test_anonymous_user_cannot_create_products(self):
        response = self.client.post(
            reverse('product-list'),
            {
                'name': 'Injected product',
                'price': '1.00',
                'description': 'Attempt to create anonymously',
                'stock': 1,
            },
        )

        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(Products.objects.filter(name='Injected product').exists())

    def test_order_api_does_not_accept_client_supplied_payment_or_total(self):
        response = self.client.post(
            reverse('order-list'),
            {'total_amount': '1.00', 'is_paid': True},
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(Order.objects.filter(user=self.user).exists())

    def test_order_api_does_not_allow_order_creation_for_authenticated_customer(self):
        from rest_framework_simplejwt.tokens import AccessToken

        token = str(AccessToken.for_user(self.user))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        response = self.client.post(
            reverse('order-list'),
            {'total_amount': '1.00', 'is_paid': True},
        )

        self.assertEqual(response.status_code, 405)
        self.assertFalse(Order.objects.filter(user=self.user).exists())

    def test_order_api_only_lists_the_authenticated_customers_orders(self):
        from rest_framework_simplejwt.tokens import AccessToken

        address = Address.objects.create(
            user=self.user,
            full_name='API Customer',
            phone='9800000000',
            line1='123 Main Street',
            line2='',
            city='Mumbai',
            state='Maharashtra',
            postal_code='400001',
            country='India',
        )
        order = Order.objects.create(user=self.user, delivery_address=address, total_amount='120.00')
        OrderItem.objects.create(order=order, product=self.product, quantity=1, unit_price='120.00')
        other_user = get_user_model().objects.create_user(username='other-api-customer')
        Order.objects.create(user=other_user, total_amount='999.00')
        token = str(AccessToken.for_user(self.user))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        response = self.client.get(reverse('order-list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(response.json()['results'][0]['total_amount'], '120.00')
