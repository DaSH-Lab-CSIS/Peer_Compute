from django import forms
from profiles.models import User


class ProviderForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('ram', 'cpu')
