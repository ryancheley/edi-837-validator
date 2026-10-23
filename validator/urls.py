from django.urls import path

from . import views

urlpatterns = [
    path("", views.validate_view, name="validate"),
    path("healthz/", views.healthz, name="healthz"),
    path("plans/", views.plan_list, name="plans"),
    path("plans/new/", views.plan_create, name="plan_create"),
    path("plans/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("plans/<int:pk>/upload/", views.guide_upload, name="guide_upload"),
    path("guides/<int:pk>/status/", views.guide_status, name="guide_status"),
    path("rulesets/<int:pk>/review/", views.ruleset_review, name="ruleset_review"),
]
