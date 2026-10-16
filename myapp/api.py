import logging
import secrets
import smtplib
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from razorpay.errors import SignatureVerificationError

from orders.models import Address, Order, OrderItem
from orders.views import (
    CheckoutError,
    PaymentValidationError,
    RAZORPAY_API_ERRORS,
    _amount_in_paise,
    _mark_order_paid,
    _payment_matches_order,
    _place_order,
    _razorpay_client,
)
from users.models import EmailVerificationCode, UserProfile
from .models import Products
from .serializers import OrderSerializer, ProductSerializer, UserSerializer

logger = logging.getLogger(__name__)
User = get_user_model()


class EmailDeliveryUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'We could not send the verification email. Please try again later.'
    default_code = 'email_delivery_unavailable'


class RegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={'input_type': 'password'},
    )

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_password(self, value):
        from django.contrib.auth.password_validation import validate_password

        user = User(
            username=self.initial_data.get('username', ''),
            email=self.initial_data.get('email', ''),
        )
        validate_password(value, user)
        return value


class EmailVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(r'^\d{6}$')


class RegisterResponseSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False)
    user = UserSerializer(required=False)
    access = serializers.CharField(required=False)
    refresh = serializers.CharField(required=False)


class ApiErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ProfileSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(source='profile.phone_number', required=False, allow_blank=True)
    gender = serializers.ChoiceField(
        source='profile.gender',
        choices=UserProfile.Gender.choices,
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'phone_number', 'gender']
        read_only_fields = ['id', 'username']

    def validate_email(self, value):
        user = self.instance
        if User.objects.filter(email__iexact=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        instance = super().update(instance, validated_data)
        profile, _ = UserProfile.objects.get_or_create(user=instance)
        for field, value in profile_data.items():
            setattr(profile, field, value)
        if profile_data:
            profile.save(update_fields=list(profile_data))
        return instance


class CartLineSerializer(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(
        source='product',
        queryset=Products.objects.filter(active=True),
    )
    quantity = serializers.IntegerField(min_value=1)


class CartQuoteRequestSerializer(serializers.Serializer):
    items = CartLineSerializer(many=True, allow_empty=False, max_length=100)

    def validate_items(self, items):
        quantities = {}
        products = {}
        for item in items:
            product = item['product']
            products[product.pk] = product
            quantities[product.pk] = quantities.get(product.pk, 0) + item['quantity']
        for product_id, quantity in quantities.items():
            product = products[product_id]
            if quantity > product.stock:
                raise serializers.ValidationError(
                    f'Only {product.stock} of {product.name} are currently available.'
                )
        return [
            {'product': products[product_id], 'quantity': quantity}
            for product_id, quantity in quantities.items()
        ]


class CartQuoteItemSerializer(serializers.Serializer):
    product = ProductSerializer(read_only=True)
    quantity = serializers.IntegerField()
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    line_total = serializers.DecimalField(max_digits=24, decimal_places=2)


class CartQuoteResponseSerializer(serializers.Serializer):
    items = CartQuoteItemSerializer(many=True)
    total = serializers.DecimalField(max_digits=24, decimal_places=2)


class CheckoutResponseSerializer(serializers.Serializer):
    order = OrderSerializer()
    payment_url = serializers.URLField()


class CheckoutSerializer(CartQuoteRequestSerializer):
    address_id = serializers.PrimaryKeyRelatedField(
        source='address',
        queryset=Address.objects.none(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            self.fields['address_id'].queryset = Address.objects.filter(user=request.user)


class RegisterAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=RegistrationSerializer,
        responses={201: RegisterResponseSerializer, 503: ApiErrorSerializer},
        description='Create an account. When email verification is enabled, the account remains inactive until verified.',
    )
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = None
        verification_required = settings.EMAIL_VERIFICATION
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=serializer.validated_data['username'],
                    email=serializer.validated_data['email'],
                    password=serializer.validated_data['password'],
                    is_active=not verification_required,
                )
                if verification_required:
                    code = f'{secrets.randbelow(1_000_000):06d}'
                    EmailVerificationCode.objects.update_or_create(
                        user=user,
                        defaults={
                            'code_hash': make_password(code),
                            'expires_at': EmailVerificationCode.expiry_time(
                                settings.EMAIL_OTP_EXPIRY_MINUTES
                            ),
                            'attempts': 0,
                        },
                    )
                    sent = send_mail(
                        subject='Your ShopFusion email verification code',
                        message=(
                            f'Your ShopFusion verification code is {code}. '
                            f'It expires in {settings.EMAIL_OTP_EXPIRY_MINUTES} minutes.'
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                    if sent != 1:
                        raise smtplib.SMTPException('The email backend did not send the verification message.')
        except (smtplib.SMTPException, OSError):
            logger.exception('Could not send an email verification message for a new account.')
            raise EmailDeliveryUnavailable()

        if verification_required:
            return Response(
                {'detail': 'Account created. Check your email for a verification code.'},
                status=status.HTTP_201_CREATED,
            )
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'user': UserSerializer(user).data,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=EmailVerificationSerializer, responses={200: UserSerializer})
    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']

        with transaction.atomic():
            user = User.objects.select_for_update().filter(
                email__iexact=email,
                is_active=False,
            ).first()
            verification = (
                EmailVerificationCode.objects.select_for_update().filter(user=user).first()
                if user
                else None
            )
            if (
                verification is None
                or verification.is_expired()
                or verification.attempts >= 5
                or not check_password(code, verification.code_hash)
            ):
                if verification:
                    verification.attempts += 1
                    if verification.attempts >= 5 or verification.is_expired():
                        verification.delete()
                    else:
                        verification.save(update_fields=['attempts'])
                raise ValidationError({'code': 'That code is invalid or expired.'})

            user.is_active = True
            user.save(update_fields=['is_active'])
            verification.delete()

        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })


class ProfileAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=ProfileSerializer)
    def get(self, request):
        UserProfile.objects.get_or_create(user=request.user)
        return Response(ProfileSerializer(request.user).data)

    @extend_schema(request=ProfileSerializer, responses=ProfileSerializer)
    def patch(self, request):
        UserProfile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class CartQuoteAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=CartQuoteRequestSerializer, responses=CartQuoteResponseSerializer)
    def post(self, request):
        serializer = CartQuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = [
            {
                'product': item['product'],
                'quantity': item['quantity'],
                'unit_price': item['product'].price,
                'line_total': item['product'].price * item['quantity'],
            }
            for item in serializer.validated_data['items']
        ]
        total = sum((item['line_total'] for item in items), Decimal('0.00'))
        return Response(CartQuoteResponseSerializer(
            {'items': items, 'total': total},
            context={'request': request},
        ).data)


class CheckoutAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=CheckoutSerializer,
        responses={201: CheckoutResponseSerializer, 400: ApiErrorSerializer},
        description='Create a pending order using current product prices and reserve available stock.',
    )
    def post(self, request):
        serializer = CheckoutSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        quantities = {
            item['product'].pk: item['quantity']
            for item in serializer.validated_data['items']
        }
        try:
            order = _place_order(
                user=request.user,
                address=serializer.validated_data['address'],
                requested=quantities,
            )
        except CheckoutError as exc:
            raise ValidationError({'detail': str(exc)}) from exc

        return Response(
            {
                'order': OrderSerializer(order, context={'request': request}).data,
                'payment_url': request.build_absolute_uri(
                    reverse('api-order-start-payment', kwargs={'order_id': order.pk})
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class PaymentRequestSerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=64)
    razorpay_payment_id = serializers.CharField(max_length=64)
    razorpay_signature = serializers.CharField(max_length=128)


class PaymentPrefillSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True)
    email = serializers.EmailField(allow_blank=True)
    contact = serializers.CharField(allow_blank=True)


class PaymentStartResponseSerializer(serializers.Serializer):
    key = serializers.CharField()
    amount = serializers.IntegerField()
    currency = serializers.CharField()
    order_id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    prefill = PaymentPrefillSerializer()


class StartOrderPaymentAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: PaymentStartResponseSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
            503: ApiErrorSerializer,
            502: ApiErrorSerializer,
        },
        description='Create or reuse the Razorpay order for a pending customer order.',
    )
    def post(self, request, order_id):
        client = _razorpay_client()
        if client is None:
            return Response(
                {'detail': 'Online payment is not configured yet.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        with transaction.atomic():
            order = Order.objects.select_for_update().filter(
                pk=order_id,
                user=request.user,
            ).first()
            if order is None:
                return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
            if order.is_paid or order.status == Order.Status.PAID:
                return Response(
                    {'detail': 'This order has already been paid.'},
                    status=status.HTTP_409_CONFLICT,
                )
            if order.status != Order.Status.PENDING:
                return Response(
                    {'detail': 'This order is no longer awaiting payment.'},
                    status=status.HTTP_409_CONFLICT,
                )

            if not order.razorpay_order_id:
                try:
                    gateway_order = client.order.create(data={
                        'amount': _amount_in_paise(order.total_amount),
                        'currency': 'INR',
                        'receipt': f'shopfusion-{order.pk}',
                        'notes': {'shopfusion_order_id': str(order.pk)},
                    })
                except RAZORPAY_API_ERRORS as exc:
                    logger.exception('Razorpay order creation failed for API order %s.', order.pk)
                    return Response(
                        {'detail': 'The payment service could not start your payment. Please try again.'},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
                gateway_order_id = gateway_order.get('id') if isinstance(gateway_order, dict) else None
                if not gateway_order_id:
                    logger.error('Razorpay returned no order ID for API order %s.', order.pk)
                    return Response(
                        {'detail': 'The payment service returned an invalid response. Please try again.'},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
                order.razorpay_order_id = gateway_order_id
                order.save(update_fields=['razorpay_order_id'])

        address = order.delivery_address
        return Response({
            'key': settings.RAZORPAY_KEY_ID,
            'amount': _amount_in_paise(order.total_amount),
            'currency': 'INR',
            'order_id': order.razorpay_order_id,
            'name': 'ShopFusion',
            'description': f'Order #{order.pk}',
            'prefill': {
                'name': address.full_name if address else request.user.get_full_name(),
                'email': request.user.email,
                'contact': address.phone if address else '',
            },
        })


class VerifyOrderPaymentAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=PaymentRequestSerializer,
        responses={
            200: OrderSerializer,
            400: ApiErrorSerializer,
            404: ApiErrorSerializer,
            502: ApiErrorSerializer,
            503: ApiErrorSerializer,
        },
        description='Verify, capture if necessary, and confirm a Razorpay payment.',
    )
    def post(self, request, order_id):
        order = Order.objects.filter(pk=order_id, user=request.user).first()
        if order is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = PaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment_data = serializer.validated_data
        if payment_data['razorpay_order_id'] != order.razorpay_order_id:
            raise ValidationError({'detail': 'The payment does not belong to this order.'})

        client = _razorpay_client()
        if client is None:
            return Response(
                {'detail': 'Payment verification is not configured yet.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            client.utility.verify_payment_signature(payment_data)
            payment = client.payment.fetch(payment_data['razorpay_payment_id'])
            if not _payment_matches_order(payment, order):
                raise PaymentValidationError('The payment details did not match this order.')
            if payment.get('status') == 'authorized':
                payment = client.payment.capture(
                    payment_data['razorpay_payment_id'],
                    {'amount': _amount_in_paise(order.total_amount), 'currency': 'INR'},
                )
            if not _payment_matches_order(payment, order, require_captured=True):
                raise PaymentValidationError('The payment has not been captured for this order.')
            _mark_order_paid(order.pk, payment_data['razorpay_payment_id'])
        except SignatureVerificationError as exc:
            logger.warning('Invalid Razorpay API payment signature for order %s.', order.pk)
            raise ValidationError({'detail': 'Payment verification failed.'}) from exc
        except PaymentValidationError as exc:
            logger.warning('Razorpay API payment rejected for order %s: %s', order.pk, exc)
            raise ValidationError({'detail': 'We could not confirm this payment.'}) from exc
        except RAZORPAY_API_ERRORS as exc:
            logger.exception('Razorpay API payment verification failed for order %s.', order.pk)
            return Response(
                {'detail': 'Payment verification is temporarily unavailable. Please try again shortly.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        order.refresh_from_db()
        return Response(OrderSerializer(order, context={'request': request}).data)


class CancelOrderAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: OrderSerializer, 404: ApiErrorSerializer, 409: ApiErrorSerializer},
    )
    def post(self, request, order_id):
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(
                pk=order_id,
                user=request.user,
            ).first()
            if order is None:
                return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
            if (
                order.status != Order.Status.PENDING
                or order.is_paid
                or order.razorpay_order_id
            ):
                return Response(
                    {'detail': 'This order can no longer be cancelled.'},
                    status=status.HTTP_409_CONFLICT,
                )

            items = list(OrderItem.objects.filter(order=order))
            for item in items:
                Products.all_objects.select_for_update().get(pk=item.product_id)
                Products.all_objects.filter(pk=item.product_id).update(
                    stock=F('stock') + item.quantity
                )
            order.status = Order.Status.CANCELLED
            order.save(update_fields=['status'])

        return Response(OrderSerializer(order, context={'request': request}).data)
