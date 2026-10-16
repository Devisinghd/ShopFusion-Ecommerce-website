from rest_framework import serializers
from .models import Products
from django.contrib.auth.models import User
from orders.models import Order, OrderItem, Address

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']


class ProductSerializer(serializers.ModelSerializer):
    seller = UserSerializer(read_only=True)

    class Meta:
        model = Products
        fields = ['id', 'name', 'price', 'description', 'image', 'slug', 'stock', 'active', 'seller']
        read_only_fields = ['id', 'slug', 'seller']

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price can not be less than zero")
        return value

    def validate(self, data):
        if data.get('name') == data.get('description'):
            raise serializers.ValidationError("Product name and description can not be same")
        return data


class AddressSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Address
        fields = '__all__'
        read_only_fields = ['user']


class OrderItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Products.objects.all(), source='product', write_only=True
    )
    total_price = serializers.DecimalField(max_digits=22, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'order', 'product', 'product_id', 'quantity', 'unit_price', 'total_price']
        read_only_fields = ['id', 'product', 'unit_price', 'total_price']

    def validate_order(self, value):
        request = self.context.get('request')
        if request and request.user != value.user:
            raise serializers.ValidationError("Order must belong to the authenticated user.")
        return value


class OrderSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ['id', 'user', 'total_amount', 'is_paid', 'status', 'created_at', 'items']
        read_only_fields = ['id', 'user', 'total_amount', 'is_paid', 'status', 'created_at', 'items']