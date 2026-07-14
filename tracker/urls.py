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
    path('profile/', views.profile_view, name='profile'),
    path('api/sync-weather/', views.sync_weather_api, name='sync_weather_api'),
    path('api/nudge/dismiss/', views.dismiss_nudges_api, name='dismiss_nudges_api'),
    path('api/nudge/<str:username>/', views.send_nudge_api, name='send_nudge_api'),
    path('api/analytics/<str:range_type>/', views.analytics_data_api, name='analytics_data_api'),
    path('api/nudge/check/', views.check_new_nudges_api, name='check_new_nudges_api'),
]