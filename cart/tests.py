from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from myapp.models import Products

# Create your tests here.
class CartEndpointTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username='cart-user', password='test-pass-123')
		self.product = Products.objects.create(
			seller=self.user,
			name='Test watch',
			price=120,
			description='Test product',
			image='images/test-watch.jpg',
			stock=3,
		)

	def test_cart_add_update_and_remove(self):
		add_response = self.client.post(reverse('cart:cart_add'), {
			'product_id': self.product.id,
			'product_quantity': 1,
		})
		self.assertEqual(add_response.status_code, 200)
		self.assertEqual(add_response.json()['cart_quantity'], 1)

		update_response = self.client.post(reverse('cart:cart_update'), {
			'product_id': self.product.id,
			'product_quantity': 2,
		})
		self.assertEqual(update_response.status_code, 200)
		self.assertEqual(update_response.json()['cart_quantity'], 2)

		delete_response = self.client.post(reverse('cart:cart_delete'), {
			'product_id': self.product.id,
		})
		self.assertEqual(delete_response.status_code, 200)
		self.assertEqual(delete_response.json()['cart_quantity'], 0)

	def test_cart_rejects_quantity_above_stock(self):
		response = self.client.post(reverse('cart:cart_add'), {
			'product_id': self.product.id,
			'product_quantity': 4,
		})

		self.assertEqual(response.status_code, 400)

	def test_cart_total_uses_current_product_price(self):
		self.client.post(reverse('cart:cart_add'), {
			'product_id': self.product.id,
			'product_quantity': 1,
		})
		self.product.price = 155
		self.product.save(update_fields=['price'])

		response = self.client.post(reverse('cart:cart_update'), {
			'product_id': self.product.id,
			'product_quantity': 1,
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['cart_total'], '155.00')
