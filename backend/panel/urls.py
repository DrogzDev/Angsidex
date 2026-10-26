from django.urls import path

from . import views

urlpatterns = [
    path('csrf', views.csrf),
    path('me', views.me),
    path('login', views.login_view),
    path('logout', views.logout_view),
    path('overview', views.overview),
    path('leads', views.leads_list),
    path('leads/<int:pk>', views.lead_detail),
    path('quotes', views.quotes_list),
]
