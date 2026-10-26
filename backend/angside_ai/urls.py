from django.urls import path

from . import views

urlpatterns = [
    path('sessions', views.SessionCreateView.as_view()),
    path('sessions/<uuid:session_id>', views.SessionDetailView.as_view()),
    path('sessions/<uuid:session_id>/messages', views.MessageView.as_view()),
    path('sessions/<uuid:session_id>/request-contact', views.ContactRequestView.as_view()),
    path('sessions/<uuid:session_id>/profile', views.ProfileView.as_view()),
    path('sessions/<uuid:session_id>/proposals/<int:proposal_id>/payment-mode', views.ProposalPaymentModeView.as_view()),
]
