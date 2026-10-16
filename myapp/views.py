from django.shortcuts import render
from .models import Products
from orders.models import Address, Order, OrderItem
from django.core.paginator import Paginator
import logging
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .serializers import ProductSerializer, OrderSerializer, AddressSerializer, OrderItemSerializer
from rest_framework import permissions, viewsets
from rest_framework_simplejwt.authentication import JWTAuthentication
from .permissions import IsOwnerOrReadOnly
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.throttling import AnonRateThrottle,UserRateThrottle
logger = logging.getLogger(__name__)
# Create your views here.
#@cache_page(60 * 15)
#@vary_on_headers("User-Agent")
def index(request):
    logger.info("getting products from database")
    products = Products.objects.filter(active=True).order_by('pk')
    logger.debug(f"found {products.count()} found")
    paginator = Paginator(products,7)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request,'myapp/index.html',{"page_obj":page_obj})

#@cache_page(60 * 15)
def detail(request, slug):
    logger.info(f"Fetching a product with id")
    product = get_object_or_404(Products, slug=slug, active=True)
    logger.debug(f"founs product{product.name} (${product.price})")
    return render(request,'myapp/detail.html',{'product':product})

#API Views
#Product API
class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer 
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsOwnerOrReadOnly]
    filter_backends = [DjangoFilterBackend, OrderingFilter,SearchFilter]
    filterset_fields = {
        'price': ['exact', 'gte', 'lte'],
        'stock': ['gte'],
        'seller__username': ['exact'],
    }
    ordering_fields = ['name', 'price', 'stock', 'id']
    ordering = ['id']
    search_fields = ['name', 'price', 'description', 'seller__username']
    throttle_classes = [AnonRateThrottle,UserRateThrottle]

    def get_queryset(self):
        queryset = Products.objects.all()
        user = self.request.user
        if user.is_authenticated:
            queryset = queryset.filter(Q(active=True) | Q(seller=user))
        else:
            queryset = queryset.filter(active=True)
        return queryset.select_related('seller').order_by('pk')

    def perform_create(self, serializer):
        serializer.save(seller=self.request.user)
    

#Order API

class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [AnonRateThrottle, UserRateThrottle]

    def get_queryset(self):
        user = self.request.user
        if user and user.is_authenticated:
            return Order.objects.filter(user=user).select_related(
                'user', 'delivery_address'
            ).prefetch_related('items__product').order_by('-created_at')
        return Order.objects.none()

class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [AnonRateThrottle, UserRateThrottle]

    def get_queryset(self):
        user = self.request.user
        if user and user.is_authenticated:
            return Address.objects.filter(user=user).order_by('-id')
        return Address.objects.none()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class OrderItemViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderItemSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [AnonRateThrottle, UserRateThrottle]

    def get_queryset(self):
        user = self.request.user
        if user and user.is_authenticated:
            return OrderItem.objects.filter(order__user=user)
        return OrderItem.objects.none()
