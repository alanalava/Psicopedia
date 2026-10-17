from django.urls import path
from . import views


urlpatterns = [
    path('', views.vista_escritorio, name='escritorio'), 
    path('quiz/', views.vista_inicio, name='quiz'),
    path('biblioteca/', views.vista_biblioteca, name='biblioteca'),
    path('expedientes/', views.vista_expedientes, name='expedientes'), # NUEVA RUTA
    path('api/cuestionario/', views.obtener_cuestionario_api, name='api_cuestionario'),
    path('api/expedientes/', views.obtener_expedientes_api, name='api_expedientes'), # NUEVA API
    path('login/', views.vista_login, name='login'),
    path('registro/', views.vista_registro, name='registro'),
    path('logout/', views.vista_logout, name='logout'),
    # Rutas del Minijuego (Racha Psicopédica)
    path('minijuego/', views.vista_minijuego, name='minijuego'),
    path('api/minijuego/reto/', views.api_reto_minijuego, name='api_reto_minijuego'),
    path('api/minijuego/responder/', views.api_responder_minijuego, name='api_responder_minijuego'),
]