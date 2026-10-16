import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from myapp.models import Products
from razorpay.errors import SignatureVerificationError
from .models import Address, Order, OrderItem


class OrdersViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="orderviewer",
            email="orderviewer@example.com",
            password="strong-pass-123",
        )
        self.client.force_login(self.user)

    def test_order_history_page_renders_professionally(self):
        response = self.client.get(reverse("order_view"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Order history")
        self.assertContains(response, "Your recent purchases")


class CheckoutViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester",
            email="tester@example.com",
            password="strong-pass-123",
        )
        self.client.force_login(self.user)
        self.product = Products.objects.create(
            seller=self.user,
            name='Checkout watch',
            price=125,
            description='Test product',
            image='images/checkout-watch.jpg',
            stock=5,
        )

    def test_checkout_shows_selected_address_and_opens_saved_addresses_on_request(self):
        Address.objects.create(
            user=self.user,
            full_name="Jane Doe",
            phone="9800000000",
            line1="123 Main Street",
            line2="",
            city="Mumbai",
            state="Maharashtra",
            postal_code="400001",
            country="India",
        )
        Address.objects.create(
            user=self.user,
            full_name="Alex Doe",
            phone="9800000001",
            line1="456 Other Street",
            line2="",
            city="Pune",
            state="Maharashtra",
            postal_code="411001",
            country="India",
        )

        response = self.client.get(reverse("checkout"))

        self.assertIn("addresses", response.context)
        self.assertEqual(len(response.context["addresses"]), 2)
        self.assertContains(response, 'id="change-address-button"')
        self.assertContains(response, '<dialog class="address-dialog" id="address-dialog"', html=False)
        self.assertContains(response, 'id="selected-address-summary"', html=False)
        self.assertContains(response, "Alex Doe")
        self.assertNotContains(response, "Choose this address")

    def test_add_address_returns_to_checkout_with_product_query(self):
        response = self.client.post(
            reverse("add_address") + "?next=%2Forders%2Fcheckout%2F%3Fproduct_id%3D1%26quantity%3D1",
            {
                "full_name": "Jane Doe",
                "phone": "9800000000",
                "line1": "123 Main Street",
                "line2": "Unit 1",
                "city": "Mumbai",
                "state": "Maharashtra",
                "postal_code": "400001",
                "country": "India",
            },
        )

        self.assertRedirects(
            response,
            "/orders/checkout/?product_id=1&quantity=1",
            fetch_redirect_response=False,
        )

    def test_checkout_shows_prompt_when_no_address_is_saved(self):
        response = self.client.get(reverse("checkout"))

        self.assertContains(response, "No delivery address yet")
        self.assertContains(response, "Add address")

    def test_checkout_creates_order_with_address_and_clears_cart(self):
        address = Address.objects.create(
            user=self.user,
            full_name='Jane Doe',
            phone='9800000000',
            line1='123 Main Street',
            line2='',
            city='Mumbai',
            state='Maharashtra',
            postal_code='400001',
            country='India',
        )
        session = self.client.session
        session['cart'] = {str(self.product.id): {'price': '1.00', 'qty': 2}}
        session.save()

        response = self.client.post(reverse('checkout'), {'selected_address_id': address.id})

        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order-payment', args=[order.pk]))
        self.assertEqual(order.delivery_address, address)
        self.assertEqual(order.total_amount, 250)
        order_item = OrderItem.objects.get(order=order)
        self.assertEqual(order_item.quantity, 2)
        self.assertEqual(order_item.unit_price, 125)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(self.client.session.get('cart'), {})

    def test_checkout_refuses_quantity_above_current_stock(self):
        address = Address.objects.create(
            user=self.user,
            full_name='Jane Doe',
            phone='9800000000',
            line1='123 Main Street',
            line2='',
            city='Mumbai',
            state='Maharashtra',
            postal_code='400001',
            country='India',
        )
        session = self.client.session
        session['cart'] = {str(self.product.id): {'price': '125.00', 'qty': 6}}
        session.save()

        response = self.client.post(reverse('checkout'), {'selected_address_id': address.id})

        self.assertRedirects(response, reverse('checkout_warning'))
        self.assertFalse(Order.objects.filter(user=self.user).exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)

    def test_cancel_order_restores_reserved_stock_and_keeps_order_history(self):
        address = Address.objects.create(
            user=self.user,
            full_name='Jane Doe',
            phone='9800000000',
            line1='123 Main Street',
            line2='',
            city='Mumbai',
            state='Maharashtra',
            postal_code='400001',
            country='India',
        )
        session = self.client.session
        session['cart'] = {str(self.product.id): {'price': '125.00', 'qty': 2}}
        session.save()
        self.client.post(reverse('checkout'), {'selected_address_id': address.id})

        order_item = OrderItem.objects.get(order__user=self.user)
        response = self.client.post(reverse('cancel_order', args=[order_item.id]))

        self.assertRedirects(response, reverse('order_view'))
        order_item.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order_item.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.product.stock, 5)
        self.assertTrue(OrderItem.objects.filter(pk=order_item.pk).exists())

    def test_place_order_endpoint_ignores_session_price_and_checks_stock(self):
        address = Address.objects.create(
            user=self.user,
            full_name='Jane Doe',
            phone='9800000000',
            line1='123 Main Street',
            line2='',
            city='Mumbai',
            state='Maharashtra',
            postal_code='400001',
            country='India',
        )
        session = self.client.session
        session['checkout_items'] = [{
            'product_id': str(self.product.id),
            'quantity': 2,
            'unit_price': '0.01',
        }]
        session.save()

        response = self.client.post(
            reverse('place-order'),
            {'selected_address_id': address.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['payment_url'], reverse('order-payment', args=[response.json()['order_id']]))
        order = Order.objects.get(user=self.user)
        order_item = OrderItem.objects.get(order=order)
        self.assertEqual(order.total_amount, 250)
        self.assertEqual(order_item.unit_price, 125)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def _create_order_with_gateway_id(self, gateway_order_id='order_test_1'):
        address = Address.objects.create(
            user=self.user,
            full_name='Jane Doe',
            phone='9800000000',
            line1='123 Main Street',
            line2='',
            city='Mumbai',
            state='Maharashtra',
            postal_code='400001',
            country='India',
        )
        order = Order.objects.create(
            user=self.user,
            delivery_address=address,
            total_amount=Decimal('250.00'),
            razorpay_order_id=gateway_order_id,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=2,
            unit_price=Decimal('125.00'),
        )
        return order

    @override_settings(
        RAZORPAY_KEY_ID='rzp_test_key',
        RAZORPAY_KEY_SECRET='test-secret',
    )
    @patch('orders.views.razorpay.Client')
    def test_start_payment_creates_gateway_order_with_server_calculated_amount(self, razorpay_client):
        order = self._create_order_with_gateway_id(gateway_order_id=None)
        client = razorpay_client.return_value
        client.order.create.return_value = {'id': 'order_generated'}

        response = self.client.post(reverse('start-payment', args=[order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['amount'], 25000)
        self.assertEqual(response.json()['order_id'], 'order_generated')
        client.order.create.assert_called_once_with(data={
            'amount': 25000,
            'currency': 'INR',
            'receipt': f'shopfusion-{order.pk}',
            'notes': {'shopfusion_order_id': str(order.pk)},
        })
        order.refresh_from_db()
        self.assertEqual(order.razorpay_order_id, 'order_generated')
        self.assertFalse(order.is_paid)

    @override_settings(
        RAZORPAY_KEY_ID='rzp_test_key',
        RAZORPAY_KEY_SECRET='test-secret',
    )
    @patch('orders.views.razorpay.Client')
    def test_callback_verifies_and_captures_payment_before_marking_order_paid(self, razorpay_client):
        order = self._create_order_with_gateway_id()
        client = razorpay_client.return_value
        client.payment.fetch.return_value = {
            'id': 'pay_test_1',
            'order_id': order.razorpay_order_id,
            'amount': 25000,
            'currency': 'INR',
            'status': 'authorized',
        }
        client.payment.capture.return_value = {
            'id': 'pay_test_1',
            'order_id': order.razorpay_order_id,
            'amount': 25000,
            'currency': 'INR',
            'status': 'captured',
        }

        response = self.client.post(reverse('payment-callback'), {
            'razorpay_order_id': order.razorpay_order_id,
            'razorpay_payment_id': 'pay_test_1',
            'razorpay_signature': 'valid-signature',
        })

        self.assertEqual(response.status_code, 302)
        self.assertIn(f'order_id={order.pk}', response['Location'])
        client.utility.verify_payment_signature.assert_called_once()
        client.payment.capture.assert_called_once_with(
            'pay_test_1',
            {'amount': 25000, 'currency': 'INR'},
        )
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.razorpay_payment_id, 'pay_test_1')
        self.assertIsNotNone(order.paid_at)

    @override_settings(
        RAZORPAY_KEY_ID='rzp_test_key',
        RAZORPAY_KEY_SECRET='test-secret',
    )
    @patch('orders.views.razorpay.Client')
    def test_callback_confirms_payment_without_a_login_cookie(self, razorpay_client):
        order = self._create_order_with_gateway_id()
        self.client.logout()
        client = razorpay_client.return_value
        client.payment.fetch.return_value = {
            'id': 'pay_anonymous_callback',
            'order_id': order.razorpay_order_id,
            'amount': 25000,
            'currency': 'INR',
            'status': 'captured',
        }

        response = self.client.post(reverse('payment-callback'), {
            'razorpay_order_id': order.razorpay_order_id,
            'razorpay_payment_id': 'pay_anonymous_callback',
            'razorpay_signature': 'valid-signature',
        })
        confirmation = self.client.get(response['Location'])

        self.assertEqual(response.status_code, 302)
        self.assertContains(confirmation, 'Payment confirmed')
        order.refresh_from_db()
        self.assertTrue(order.is_paid)

    @override_settings(
        RAZORPAY_KEY_ID='rzp_test_key',
        RAZORPAY_KEY_SECRET='test-secret',
    )
    @patch('orders.views.razorpay.Client')
    def test_callback_rejects_a_payment_with_a_mismatched_amount(self, razorpay_client):
        order = self._create_order_with_gateway_id()
        client = razorpay_client.return_value
        client.payment.fetch.return_value = {
            'id': 'pay_wrong_amount',
            'order_id': order.razorpay_order_id,
            'amount': 1,
            'currency': 'INR',
            'status': 'captured',
        }

        response = self.client.post(reverse('payment-callback'), {
            'razorpay_order_id': order.razorpay_order_id,
            'razorpay_payment_id': 'pay_wrong_amount',
            'razorpay_signature': 'valid-signature',
        })

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertFalse(order.is_paid)
        client.payment.capture.assert_not_called()

    @override_settings(
        RAZORPAY_KEY_ID='rzp_test_key',
        RAZORPAY_KEY_SECRET='test-secret',
    )
    @patch('orders.views.razorpay.Client')
    def test_callback_rejects_forged_signature(self, razorpay_client):
        order = self._create_order_with_gateway_id()
        client = razorpay_client.return_value
        client.utility.verify_payment_signature.side_effect = SignatureVerificationError('invalid')

        response = self.client.post(reverse('payment-callback'), {
            'razorpay_order_id': order.razorpay_order_id,
            'razorpay_payment_id': 'pay_forged',
            'razorpay_signature': 'forged',
        })

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertFalse(order.is_paid)
        client.payment.fetch.assert_not_called()

    @override_settings(
        RAZORPAY_KEY_ID='rzp_test_key',
        RAZORPAY_KEY_SECRET='test-secret',
        RAZORPAY_WEBHOOK_SECRET='webhook-secret',
    )
    @patch('orders.views.razorpay.Client')
    def test_captured_webhook_marks_order_paid_and_is_idempotent(self, razorpay_client):
        order = self._create_order_with_gateway_id()
        client = razorpay_client.return_value
        payload = {
            'event': 'payment.captured',
            'payload': {'payment': {'entity': {
                'id': 'pay_webhook_1',
                'order_id': order.razorpay_order_id,
                'amount': 25000,
                'currency': 'INR',
                'status': 'captured',
            }}},
        }
        data = json.dumps(payload)

        response = self.client.post(
            reverse('payment-webhook'),
            data,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='valid-signature',
        )
        retry_response = self.client.post(
            reverse('payment-webhook'),
            data,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='valid-signature',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(retry_response.status_code, 200)
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertEqual(order.razorpay_payment_id, 'pay_webhook_1')
        client.utility.verify_webhook_signature.assert_called()

    @override_settings(
        RAZORPAY_KEY_ID='rzp_test_key',
        RAZORPAY_KEY_SECRET='test-secret',
        RAZORPAY_WEBHOOK_SECRET='webhook-secret',
    )
    @patch('orders.views.razorpay.Client')
    def test_webhook_rejects_forged_signature(self, razorpay_client):
        client = razorpay_client.return_value
        client.utility.verify_webhook_signature.side_effect = SignatureVerificationError('invalid')

        response = self.client.post(
            reverse('payment-webhook'),
            '{}',
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='forged-signature',
        )

        self.assertEqual(response.status_code, 400)

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_start_payment_reports_missing_gateway_configuration(self):
        order = self._create_order_with_gateway_id(gateway_order_id=None)

        response = self.client.post(reverse('start-payment', args=[order.pk]))

        self.assertEqual(response.status_code, 503)
        order.refresh_from_db()
        self.assertIsNone(order.razorpay_order_id)

    def test_order_cannot_be_cancelled_after_payment_is_started(self):
        order = self._create_order_with_gateway_id()
        item = order.items.first()

        response = self.client.post(reverse('cancel_order', args=[item.pk]))

        self.assertRedirects(response, reverse('order_view'))
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(self.product.stock, 5)

    def test_checkout_rejects_another_users_address(self):
        Address.objects.create(
            user=self.user,
            full_name='Jane Doe',
            phone='9800000000',
            line1='123 Main Street',
            line2='',
            city='Mumbai',
            state='Maharashtra',
            postal_code='400001',
            country='India',
        )
        other_user = get_user_model().objects.create_user(username='other-user', password='test-pass-123')
        other_address = Address.objects.create(
            user=other_user,
            full_name='Other User',
            phone='9800000001',
            line1='456 Other Street',
            line2='',
            city='Pune',
            state='Maharashtra',
            postal_code='411001',
            country='India',
        )
        session = self.client.session
        session['cart'] = {str(self.product.id): {'price': str(self.product.price), 'qty': 1}}
        session.save()

        response = self.client.post(reverse('checkout'), {'selected_address_id': other_address.id})

        self.assertRedirects(response, reverse('checkout'))
        self.assertFalse(Order.objects.filter(user=self.user).exists())
