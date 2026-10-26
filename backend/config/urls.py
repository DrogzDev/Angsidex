from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'Angside · Panel de administración'
admin.site.site_title = 'Angside'
admin.site.index_title = 'Prospectos, conversaciones y precios'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/ai/', include('angside_ai.urls')),
    path('api/commercial/', include('commercial.urls')),
    path('api/panel/', include('panel.urls')),
]
