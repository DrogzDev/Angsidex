from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from . import views

admin.site.site_header = 'Angside · Panel de administración'
admin.site.site_title = 'Angside'
admin.site.index_title = 'Prospectos, conversaciones y precios'

urlpatterns = [
    path('healthz', views.healthz),
    path(settings.ADMIN_URL, admin.site.urls),
    path('api/ai/', include('angside_ai.urls')),
    path('api/commercial/', include('commercial.urls')),
    path('api/panel/', include('panel.urls')),
]
