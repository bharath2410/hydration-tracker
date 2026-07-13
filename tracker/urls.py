from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('api/log/', views.log_water_api, name='log_water_api'),
    path('api/profile/', views.update_profile_api, name='update_profile_api'),
    path('friends/add/', views.add_friend, name='add_friend'),
]