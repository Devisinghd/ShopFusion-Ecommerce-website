from django.db import models
from django.contrib.auth.models import User
from myapp.models import Products
# Create your models here.

class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=50)
    phone = models.CharField( max_length=20)
    line1 = models.CharField( max_length=250)
    line2 = models.CharField( max_length=250)
    city = models.CharField( max_length=50)
    state = models.CharField( max_length=50)
    postal_code = models.CharField(max_length=50)
    country = models.CharField(max_length=50)


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        CANCELLED = 'cancelled', 'Cancelled'
        FULFILLED = 'fulfilled', 'Fulfilled'

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    delivery_address = models.ForeignKey(
        Address,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    total_amount = models.DecimalField(max_digits=24, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    razorpay_order_id = models.CharField(max_length=64, blank=True, null=True, unique=True)
    razorpay_payment_id = models.CharField(max_length=64, blank=True, null=True, unique=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE,related_name="items")
    product = models.ForeignKey(Products, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)


    @property
    def total_price(self):
        return self.unit_price * self.quantity