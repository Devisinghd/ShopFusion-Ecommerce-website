from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from orders.models import Address, Order, OrderItem
from users.models import EmailVerificationCode
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


class ReactStoreApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='react-customer',
            email='react-customer@example.com',
            password='test-pass-123',
        )
        self.address = Address.objects.create(
            user=self.user,
            full_name='React Customer',
            phone='9800000000',
            line1='123 Main Street',
            line2='',
            city='Mumbai',
            state='Maharashtra',
            postal_code='400001',
            country='India',
        )
        self.product = Products.objects.create(
            seller=self.user,
            name='React API watch',
            price='120.00',
            description='Product for React API tests',
            image='images/react-watch.jpg',
            stock=4,
        )

    def test_cart_quote_uses_current_product_price_and_rejects_excess_stock(self):
        response = self.client.post(
            reverse('api-cart-quote'),
            {'items': [{'product_id': self.product.pk, 'quantity': 2}]},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], '240.00')
        self.assertEqual(response.json()['items'][0]['unit_price'], '120.00')

        response = self.client.post(
            reverse('api-cart-quote'),
            {'items': [{'product_id': self.product.pk, 'quantity': 5}]},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_checkout_creates_order_with_server_calculated_total(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            reverse('api-checkout'),
            {
                'address_id': self.address.pk,
                'items': [{'product_id': self.product.pk, 'quantity': 2}],
                'total_amount': '1.00',
                'is_paid': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.total_amount, 240)
        self.assertFalse(order.is_paid)
        self.assertEqual(order.items.get().unit_price, 120)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)
        self.assertEqual(response.json()['order']['delivery_address']['id'], self.address.pk)

    def test_checkout_rejects_another_users_address(self):
        other_user = get_user_model().objects.create_user(username='another-react-customer')
        other_address = Address.objects.create(
            user=other_user,
            full_name='Other Customer',
            phone='9800000001',
            line1='456 Other Street',
            line2='',
            city='Pune',
            state='Maharashtra',
            postal_code='411001',
            country='India',
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            reverse('api-checkout'),
            {
                'address_id': other_address.pk,
                'items': [{'product_id': self.product.pk, 'quantity': 1}],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=self.user).exists())

    @override_settings(EMAIL_VERIFICATION=False)
    def test_registration_returns_tokens_when_email_verification_is_disabled(self):
        response = self.client.post(
            reverse('api-register'),
            {
                'username': 'new-react-customer',
                'email': 'new-react-customer@example.com',
                'password': 'Strong-password-123',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn('access', response.json())
        self.assertTrue(get_user_model().objects.get(username='new-react-customer').is_active)

    def test_profile_update_is_limited_to_authenticated_user(self):
        response = self.client.get(reverse('api-profile'))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get(reverse('order-list')).status_code, 401)
        self.assertEqual(self.client.get(reverse('address-list')).status_code, 401)

        self.client.force_authenticate(self.user)
        response = self.client.patch(
            reverse('api-profile'),
            {'first_name': 'React', 'phone_number': '+91 9800000000'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'React')
        self.assertEqual(self.user.profile.phone_number, '+91 9800000000')

    @override_settings(
        EMAIL_VERIFICATION=True,
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    )
    def test_email_verification_activates_account_and_returns_jwt(self):
        response = self.client.post(
            reverse('api-register'),
            {
                'username': 'pending-react-user',
                'email': 'pending-react-user@example.com',
                'password': 'Strong-password-123',
            },
            format='json',
        )
        user = get_user_model().objects.get(username='pending-react-user')

        self.assertEqual(response.status_code, 201)
        self.assertFalse(user.is_active)
        self.assertTrue(EmailVerificationCode.objects.filter(user=user).exists())
        code = mail.outbox[-1].body.split('code is ')[1].split('.')[0]

        response = self.client.post(
            reverse('api-verify-email'),
            {'email': user.email, 'code': code},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.json())
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(EmailVerificationCode.objects.filter(user=user).exists())

    @patch('myapp.api._razorpay_client')
    @override_settings(RAZORPAY_KEY_ID='rzp_test_key')
    def test_start_payment_creates_razorpay_order_for_the_owner(self, get_client):
        order = Order.objects.create(
            user=self.user,
            delivery_address=self.address,
            total_amount='120.00',
        )
        self.client.force_authenticate(self.user)
        get_client.return_value.order.create.return_value = {'id': 'gateway-order-123'}

        response = self.client.post(
            reverse('api-order-start-payment', kwargs={'order_id': order.pk}),
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['amount'], 12000)
        self.assertEqual(response.json()['order_id'], 'gateway-order-123')
        order.refresh_from_db()
        self.assertEqual(order.razorpay_order_id, 'gateway-order-123')

    @patch('myapp.api._razorpay_client')
    def test_verify_payment_marks_only_a_verified_captured_payment_paid(self, get_client):
        order = Order.objects.create(
            user=self.user,
            delivery_address=self.address,
            total_amount='120.00',
            razorpay_order_id='gateway-order-verified',
        )
        self.client.force_authenticate(self.user)
        client = get_client.return_value
        client.payment.fetch.return_value = {
            'id': 'payment-verified',
            'order_id': 'gateway-order-verified',
            'amount': 12000,
            'currency': 'INR',
            'status': 'captured',
        }

        response = self.client.post(
            reverse('api-order-verify-payment', kwargs={'order_id': order.pk}),
            {
                'razorpay_order_id': 'gateway-order-verified',
                'razorpay_payment_id': 'payment-verified',
                'razorpay_signature': 'valid-signature',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertEqual(order.razorpay_payment_id, 'payment-verified')

    def test_cancel_order_restores_reserved_stock(self):
        order = Order.objects.create(
            user=self.user,
            delivery_address=self.address,
            total_amount='120.00',
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            unit_price='120.00',
        )
        self.product.stock = 3
        self.product.save(update_fields=['stock'])
        self.client.force_authenticate(self.user)

        response = self.client.post(
            reverse('api-order-cancel', kwargs={'order_id': order.pk}),
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.product.stock, 4)
