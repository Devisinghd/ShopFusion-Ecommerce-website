from django import forms
from myapp.models import Products

class ProductCreateForm(forms.ModelForm):
    class Meta:
        model = Products
        fields = ['name','price','description','image','stock']


    def clean_price(self):
        product_price = self.cleaned_data['price']
        if product_price <= 0:
            raise forms.ValidationError("price must be greater than zero")
        return product_price