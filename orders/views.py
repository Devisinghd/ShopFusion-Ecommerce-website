from decimal import Decimal, InvalidOperation
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import razorpay
from requests.exceptions import RequestException
from razorpay.errors import (
    BadRequestError,
    GatewayError,
    ServerError,
    SignatureVerificationError,
)

from myapp.models import Products
from .forms import AddressForm
from .models import Address, Order, OrderItem

logger = logging.getLogger(__name__)


class CheckoutError(ValueError):
    pass


class PaymentValidationError(ValueError):
    pass


RAZORPAY_API_ERRORS = (BadRequestError, GatewayError, ServerError, RequestException)


def _razorpay_client():
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return None
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def _amount_in_paise(amount):
    return int((amount * Decimal('100')).quantize(Decimal('1')))


def _payment_matches_order(payment, order, *, require_captured=False):
    if not isinstance(payment, dict):
        return False
    accepted_statuses = {'captured'} if require_captured else {'authorized', 'captured'}
    return (
        payment.get('order_id') == order.razorpay_order_id
        and payment.get('amount') == _amount_in_paise(order.total_amount)
        and payment.get('currency') == 'INR'
        and payment.get('status') in accepted_statuses
    )


def _mark_order_paid(order_id, payment_id):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.is_paid:
            if order.razorpay_payment_id == payment_id:
                return order
            raise PaymentValidationError('A different payment is already recorded for this order.')
        if order.status != Order.Status.PENDING:
            raise PaymentValidationError('This order is no longer awaiting payment.')
        if order.razorpay_payment_id and order.razorpay_payment_id != payment_id:
            raise PaymentValidationError('A different payment is already associated with this order.')

        order.razorpay_payment_id = payment_id
        order.is_paid = True
        order.status = Order.Status.PAID
        order.paid_at = timezone.now()
        order.save(update_fields=['razorpay_payment_id', 'is_paid', 'status', 'paid_at'])
        return order


def _requested_lines(request, *, from_checkout_session=False):
    if from_checkout_session:
        raw_lines = request.session.get('checkout_items')
        if not isinstance(raw_lines, list) or not raw_lines:
            raise CheckoutError('No items were found in your cart.')
        source_lines = [
            (line.get('product_id'), line.get('quantity'))
            for line in raw_lines
            if isinstance(line, dict)
        ]
        if len(source_lines) != len(raw_lines):
            raise CheckoutError('Your cart contains invalid item data. Please review it.')
    elif request.GET.get('product_id'):
        source_lines = [(request.GET.get('product_id'), request.GET.get('quantity') or 1)]
    else:
        cart_items = request.session.get('cart', {})
        if not isinstance(cart_items, dict):
            raise CheckoutError('Your cart data is invalid. Please review your cart.')
        source_lines = [
            (product_id, item.get('qty'))
            for product_id, item in cart_items.items()
            if isinstance(item, dict)
        ]
        if len(source_lines) != len(cart_items):
            raise CheckoutError('Your cart contains invalid item data. Please review it.')

    if not source_lines:
        raise CheckoutError('Your cart is empty.')

    requested = {}
    for product_id, raw_quantity in source_lines:
        try:
            parsed_id = Decimal(str(product_id))
            parsed_quantity = Decimal(str(raw_quantity))
            if (
                not parsed_id.is_finite()
                or parsed_id != parsed_id.to_integral_value()
                or not parsed_quantity.is_finite()
                or parsed_quantity != parsed_quantity.to_integral_value()
            ):
                raise InvalidOperation
            product_id = int(parsed_id)
            quantity = int(parsed_quantity)
        except (TypeError, ValueError, InvalidOperation, OverflowError) as exc:
            raise CheckoutError('Your cart contains invalid item data. Please review it.') from exc
        if product_id < 1 or quantity < 1:
            raise CheckoutError('Quantities must be greater than zero.')
        requested[product_id] = requested.get(product_id, 0) + quantity
    return requested


def _checkout_items(request):
    requested = _requested_lines(request)
    products = Products.objects.filter(
        id__in=requested,
        active=True,
        is_deleted=False,
    )
    product_by_id = {product.pk: product for product in products}
    if len(product_by_id) != len(requested):
        raise CheckoutError('One or more selected products are no longer available.')

    items = []
    for product_id, quantity in requested.items():
        product = product_by_id[product_id]
        if product.price <= 0:
            raise CheckoutError(f'{product.name} has an invalid price and cannot be ordered.')
        if quantity > product.stock:
            raise CheckoutError(f'Only {product.stock} of {product.name} are currently available.')
        unit_price = Decimal(product.price)
        items.append({
            'product': product,
            'qty': quantity,
            'price': unit_price,
            'total': unit_price * quantity,
        })
    return items


def _place_order(*, user, address, requested):
    with transaction.atomic():
        products = Products.objects.select_for_update().filter(
            id__in=requested,
            active=True,
            is_deleted=False,
        ).order_by('pk')
        product_by_id = {product.pk: product for product in products}
        if len(product_by_id) != len(requested):
            raise CheckoutError('One or more selected products are no longer available.')

        total_amount = Decimal('0.00')
        for product_id, quantity in requested.items():
            product = product_by_id[product_id]
            if product.price <= 0:
                raise CheckoutError(f'{product.name} has an invalid price and cannot be ordered.')
            if quantity > product.stock:
                raise CheckoutError(f'Only {product.stock} of {product.name} are currently available.')
            total_amount += product.price * quantity

        order = Order.objects.create(
            user=user,
            total_amount=total_amount,
            delivery_address=address,
        )
        for product_id, quantity in requested.items():
            product = product_by_id[product_id]
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantity,
                unit_price=product.price,
            )
            Products.objects.filter(pk=product.pk).update(stock=F('stock') - quantity)
    return order


@login_required
def add_address(request):
    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.save()
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('checkout')
    else:
        form = AddressForm()
    return render(request, 'orders/add_address.html', {'form': form})


@login_required
def address_list(request):
    addresses = Address.objects.filter(user=request.user).order_by('-id')
    return render(request, 'orders/address_list.html', {'addresses': addresses})


@login_required
def checkout(request):
    addresses = Address.objects.filter(user=request.user).order_by('-id')
    selected_address = addresses.first()
    checkout_items = []
    checkout_error = ''
    try:
        checkout_items = _checkout_items(request)
    except CheckoutError as exc:
        checkout_error = str(exc)

    total_amount = sum((item['total'] for item in checkout_items), Decimal('0.00'))
    if checkout_items:
        request.session['checkout_items'] = [
            {'product_id': str(item['product'].id), 'quantity': item['qty']}
            for item in checkout_items
        ]

    if request.method == 'POST':
        selected_address_id = request.POST.get('selected_address_id')
        selected_address = addresses.filter(id=selected_address_id).first() if selected_address_id else None
        if checkout_error:
            messages.error(request, checkout_error)
            return redirect('checkout_warning')
        if not addresses:
            messages.error(request, 'Add a delivery address before placing your order.')
            return redirect('add_address')
        if not selected_address:
            messages.error(request, 'Please select a valid delivery address before placing your order.')
            return redirect('checkout')

        try:
            order = _place_order(
                user=request.user,
                address=selected_address,
                requested=_requested_lines(request),
            )
        except CheckoutError as exc:
            messages.error(request, str(exc))
            return redirect('checkout')

        request.session.pop('checkout_items', None)
        if not request.GET.get('product_id'):
            request.session['cart'] = {}
            request.session.modified = True
        return redirect('order-payment', order_id=order.pk)

    selected_address_id = str(selected_address.id) if selected_address else None
    return render(
        request,
        'orders/checkout.html',
        {
            'addresses': addresses,
            'address': selected_address,
            'checkout_items': checkout_items,
            'total_amount': total_amount,
            'selected_address_id': selected_address_id,
            'checkout_error': checkout_error,
        },
    )


@login_required
def place_order(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)

    selected_address_id = request.POST.get('selected_address_id')
    selected_address = Address.objects.filter(
        user=request.user,
        id=selected_address_id,
    ).first() if selected_address_id else None
    if not selected_address:
        return JsonResponse({'error': 'Please select a valid delivery address.'}, status=400)

    try:
        requested = _requested_lines(request, from_checkout_session=True)
        order = _place_order(user=request.user, address=selected_address, requested=requested)
    except CheckoutError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    request.session.pop('checkout_items', None)
    request.session['cart'] = {}
    request.session.modified = True
    return JsonResponse({
        'message': 'Order created. Complete payment to confirm it.',
        'order_id': order.pk,
        'payment_url': reverse('order-payment', args=[order.pk]),
    })


@login_required
def order_payment(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product'),
        pk=order_id,
        user=request.user,
    )
    return render(request, 'orders/order-payment.html', {
        'order': order,
        'razorpay_enabled': bool(_razorpay_client()),
    })


@login_required
@require_POST
def start_payment(request, order_id):
    client = _razorpay_client()
    if client is None:
        return JsonResponse({'error': 'Online payment is not configured yet.'}, status=503)

    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(),
            pk=order_id,
            user=request.user,
        )
        if order.is_paid or order.status == Order.Status.PAID:
            return JsonResponse({'error': 'This order has already been paid.'}, status=409)
        if order.status != Order.Status.PENDING:
            return JsonResponse({'error': 'This order is no longer awaiting payment.'}, status=409)

        if not order.razorpay_order_id:
            try:
                gateway_order = client.order.create(data={
                    'amount': _amount_in_paise(order.total_amount),
                    'currency': 'INR',
                    'receipt': f'shopfusion-{order.pk}',
                    'notes': {'shopfusion_order_id': str(order.pk)},
                })
            except RAZORPAY_API_ERRORS:
                logger.exception('Razorpay order creation failed for order %s.', order.pk)
                return JsonResponse(
                    {'error': 'The payment service could not start your payment. Please try again.'},
                    status=502,
                )

            gateway_order_id = gateway_order.get('id') if isinstance(gateway_order, dict) else None
            if not gateway_order_id:
                logger.error('Razorpay returned no order ID for ShopFusion order %s.', order.pk)
                return JsonResponse(
                    {'error': 'The payment service returned an invalid response. Please try again.'},
                    status=502,
                )
            order.razorpay_order_id = gateway_order_id
            order.save(update_fields=['razorpay_order_id'])

    return JsonResponse({
        'key': settings.RAZORPAY_KEY_ID,
        'amount': _amount_in_paise(order.total_amount),
        'currency': 'INR',
        'order_id': order.razorpay_order_id,
        'callback_url': request.build_absolute_uri(reverse('payment-callback')),
        'redirect': True,
        'name': 'ShopFusion',
        'description': f'Order #{order.pk}',
        'prefill': {
            'name': order.delivery_address.full_name if order.delivery_address else request.user.get_full_name(),
            'email': request.user.email,
            'contact': order.delivery_address.phone if order.delivery_address else '',
        },
    })


@csrf_exempt
@require_POST
def payment_callback(request):
    gateway_order_id = request.POST.get('razorpay_order_id', '')
    order = get_object_or_404(
        Order,
        razorpay_order_id=gateway_order_id,
    )
    client = _razorpay_client()
    if client is None:
        messages.error(request, 'Payment verification is temporarily unavailable.')
        return redirect('order-payment', order_id=order.pk)

    payment_id = request.POST.get('razorpay_payment_id', '')
    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': gateway_order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': request.POST.get('razorpay_signature', ''),
        })
        payment = client.payment.fetch(payment_id)
        if not _payment_matches_order(payment, order):
            raise PaymentValidationError('The payment details did not match this order.')
        if payment.get('status') == 'authorized':
            payment = client.payment.capture(
                payment_id,
                {'amount': _amount_in_paise(order.total_amount), 'currency': 'INR'},
            )
        if not _payment_matches_order(payment, order, require_captured=True):
            raise PaymentValidationError('The payment has not been captured for this order.')
        _mark_order_paid(order.pk, payment_id)
    except SignatureVerificationError:
        logger.warning('Invalid Razorpay callback signature for order %s.', order.pk)
        messages.error(request, 'Payment verification failed. Please contact support if money was deducted.')
        return redirect('order-payment', order_id=order.pk)
    except PaymentValidationError as exc:
        logger.warning('Razorpay payment rejected for order %s: %s', order.pk, exc)
        messages.error(request, 'We could not confirm this payment. Please contact support if money was deducted.')
        return redirect('order-payment', order_id=order.pk)
    except RAZORPAY_API_ERRORS:
        logger.exception('Razorpay verification failed for order %s.', order.pk)
        messages.error(request, 'Payment verification is temporarily unavailable. Please try again shortly.')
        return redirect('order-payment', order_id=order.pk)

    request.session['payment_confirmation_order_id'] = order.pk
    return redirect(f'{reverse("order-success")}?order_id={order.pk}')


@csrf_exempt
@require_POST
def payment_webhook(request):
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        logger.error('Razorpay webhook received while RAZORPAY_WEBHOOK_SECRET is not configured.')
        return HttpResponse('Webhook verification is not configured.', status=503)

    signature = request.headers.get('X-Razorpay-Signature', '')
    client = _razorpay_client()
    if not signature or client is None:
        return HttpResponse('Invalid webhook configuration or signature.', status=400)
    try:
        raw_payload = request.body.decode('utf-8')
        client.utility.verify_webhook_signature(
            raw_payload,
            signature,
            settings.RAZORPAY_WEBHOOK_SECRET,
        )
    except SignatureVerificationError:
        logger.warning('Rejected Razorpay webhook with an invalid signature.')
        return HttpResponse('Invalid signature.', status=400)
    except UnicodeDecodeError:
        return HttpResponse('Invalid webhook payload.', status=400)

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return HttpResponse('Invalid webhook payload.', status=400)

    if not isinstance(payload, dict):
        return HttpResponse('Invalid webhook payload.', status=400)
    if payload.get('event') != 'payment.captured':
        return HttpResponse(status=200)
    event_payload = payload.get('payload')
    payment_payload = event_payload.get('payment') if isinstance(event_payload, dict) else None
    payment = payment_payload.get('entity') if isinstance(payment_payload, dict) else None
    if not isinstance(payment, dict):
        return HttpResponse('Payment details are missing.', status=400)
    gateway_order_id = payment.get('order_id')
    payment_id = payment.get('id')
    if not gateway_order_id or not payment_id:
        return HttpResponse('Payment details are missing.', status=400)

    order = Order.objects.filter(razorpay_order_id=gateway_order_id).first()
    if order is None:
        logger.warning('Razorpay webhook references unknown gateway order %s.', gateway_order_id)
        return HttpResponse('Order not found.', status=404)
    if not _payment_matches_order(payment, order, require_captured=True):
        logger.error('Razorpay webhook payment does not match ShopFusion order %s.', order.pk)
        return HttpResponse('Payment does not match order.', status=400)
    try:
        _mark_order_paid(order.pk, payment_id)
    except PaymentValidationError as exc:
        logger.error('Unable to apply Razorpay webhook to order %s: %s', order.pk, exc)
        return HttpResponse('Payment conflicts with order state.', status=409)
    return HttpResponse(status=200)


def order_success(request):
    order = None
    requested_order_id = request.GET.get('order_id')
    if request.user.is_authenticated:
        order = Order.objects.filter(pk=requested_order_id, user=request.user).first()
    elif str(request.session.get('payment_confirmation_order_id')) == requested_order_id:
        order = Order.objects.filter(pk=requested_order_id, is_paid=True).first()
    if order:
        request.session.pop('payment_confirmation_order_id', None)
    return render(request, 'orders/order-success.html', {'order': order})


def order_failed(request):
    return render(request, 'orders/order-failed.html')


@login_required
def orders_view(request):
    order = OrderItem.objects.filter(order__user=request.user).select_related('order', 'product')
    return render(request, 'orders/orderlist.html', {'order': order})


def checkout_warning(request):
    return render(request, 'orders/checkout_warning.html')


@login_required
def cancel_order(request, id):
    order_item = get_object_or_404(
        OrderItem.objects.select_related('order'),
        id=id,
        order__user=request.user,
    )
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_item.order_id)
        if (
            order.status != Order.Status.PENDING
            or order.is_paid
            or order.razorpay_order_id
        ):
            messages.error(request, 'This order can no longer be cancelled.')
            return redirect('order_view')

        items = list(order.items.all())
        for item in items:
            product = Products.all_objects.select_for_update().get(pk=item.product_id)
            Products.all_objects.filter(pk=product.pk).update(stock=F('stock') + item.quantity)
        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status'])

    messages.success(request, 'Order cancelled and reserved stock restored.')
    return redirect('order_view')