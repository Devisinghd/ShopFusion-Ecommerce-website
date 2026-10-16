import logging
from decimal import Decimal, InvalidOperation

from myapp.models import Products

logger = logging.getLogger(__name__)


class Cart:
    def __init__(self, request):
        self.session = request.session
        cart = self.session.get('cart')
        if not isinstance(cart, dict):
            if cart is not None:
                logger.warning('Discarded invalid cart session data.')
            cart = {}
            self.session['cart'] = cart
            self.session.modified = True
        self.cart = cart
        self._remove_invalid_entries()

    def _remove_invalid_entries(self):
        invalid_ids = []
        for product_id, item in self.cart.items():
            try:
                quantity = Decimal(str(item['qty']))
                valid_id = int(product_id) > 0
                valid_quantity = (
                    quantity.is_finite()
                    and quantity == quantity.to_integral_value()
                    and quantity > 0
                )
            except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
                valid_id = False
                valid_quantity = False
            if not valid_id or not valid_quantity:
                invalid_ids.append(product_id)

        for product_id in invalid_ids:
            self.cart.pop(product_id, None)
            logger.warning('Discarded invalid cart item %s.', product_id)
            self.session.modified = True

    def _available_products(self):
        product_ids = [int(product_id) for product_id in self.cart]
        products = Products.objects.filter(id__in=product_ids, active=True)
        product_by_id = {str(product.id): product for product in products}
        for product_id in list(self.cart):
            if product_id not in product_by_id:
                self.cart.pop(product_id, None)
                logger.info('Removed unavailable product %s from cart.', product_id)
                self.session.modified = True
        return product_by_id

    def __len__(self):
        self._available_products()
        return sum(int(item['qty']) for item in self.cart.values())

    def get_total_price(self):
        products = self._available_products()
        return sum(
            (
                products[product_id].price * int(item['qty'])
                for product_id, item in self.cart.items()
            ),
            Decimal('0.00'),
        )

    def __iter__(self):
        products = self._available_products()
        for product_id, product in products.items():
            item = self.cart[product_id].copy()
            item['product'] = product
            item['price'] = product.price
            item['qty'] = int(item['qty'])
            item['total'] = item['price'] * item['qty']
            yield item

    def add(self, product, product_qty):
        product_id = str(product.id)
        if product_id in self.cart:
            self.cart[product_id]['qty'] += product_qty
        else:
            self.cart[product_id] = {'price': str(product.price), 'qty': product_qty}
        self.session.modified = True

    def delete(self, product_id):
        product_id = str(product_id)
        if product_id in self.cart:
            del self.cart[product_id]
        self.session.modified = True

    def update(self, product, product_qty):
        product_id = str(product.id if isinstance(product, Products) else product)
        if product_id in self.cart:
            self.cart[product_id]['qty'] = int(product_qty)
            if isinstance(product, Products):
                self.cart[product_id]['price'] = str(product.price)
        self.session.modified = True
