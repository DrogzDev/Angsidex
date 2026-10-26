from django.urls import path

from . import views

urlpatterns = [
    path('config', views.ConfigView.as_view()),
    path('quotes', views.QuoteRegisterView.as_view()),
]
