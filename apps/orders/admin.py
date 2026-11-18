from django.contrib import admin

from . models import *
from django.apps import apps


class DynamicFilterAdmin(admin.ModelAdmin):
    def get_list_display(self, request):
        """
        Dynamically set list_display to include all fields of the model.
        """
        return [field.name for field in self.model._meta.get_fields() if hasattr(field, 'attname')]


    def get_list_filter(self, request):
        """
        Dynamically create filters for all fields that are filterable (e.g., ForeignKey, BooleanField, etc.)
        """
        filterable_fields = []
        for field in self.model._meta.get_fields():
            if isinstance(field, (models.ForeignKey, models.BooleanField, models.DateField, models.DateTimeField)):
                filterable_fields.append(field.name)
        return filterable_fields

    def get_search_fields(self, request):
        """
        Dynamically create search fields for all CharField, TextField, and other searchable fields.
        """
        searchable_fields = []
        for field in self.model._meta.get_fields():
            if isinstance(field, (models.CharField, models.TextField)):
                searchable_fields.append(field.name)
        return searchable_fields

# Automatically register all models in the app with DynamicFilterAdmin
app_models = apps.get_app_config('orders').get_models()  # Replace 'your_app_name' with your app's name
for model in app_models:
    try:
        admin.site.register(model, DynamicFilterAdmin)
    except admin.sites.AlreadyRegistered:
        pass
