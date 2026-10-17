from django.contrib import admin
from django.urls import path
from nucleo import views
from nucleo.views import api_ranking
urlpatterns = [
    path('admin/', admin.site.urls),

    # ==========================================
    # RUTAS DE AUTENTICACIÓN
    # ==========================================
    path('login/', views.vista_login, name='login'),
    path('registro/', views.vista_registro, name='registro'),
    path('logout/', views.vista_logout, name='logout'),

    # ==========================================
    # RUTAS PRINCIPALES
    # ==========================================
    path('', views.vista_escritorio, name='escritorio'),
    path('quiz/', views.vista_inicio, name='quiz'),
    path('biblioteca/', views.vista_biblioteca, name='biblioteca'),
    path('expedientes/', views.vista_expedientes, name='expedientes'),

    # ==========================================
    # RUTAS DE MINIJUEGOS
    # ==========================================
    path('minijuego/', views.vista_minijuego, name='minijuego'),
    path('memoria/', views.vista_memoria, name='memoria'),

    # ==========================================
    # RUTAS DE LAS APIS (COMUNICACIÓN CON JAVASCRIPT)
    # ==========================================
    path('api/cuestionario/', views.obtener_cuestionario_api, name='api_cuestionario'),
    path('api/expedientes/', views.obtener_expedientes_api, name='api_expedientes'),
    
    # APIs Racha Psicopédica
    path('api/minijuego/reto/', views.api_reto_minijuego, name='api_reto_minijuego'),
    path('api/minijuego/responder/', views.api_responder_minijuego, name='api_responder_minijuego'),
    
    # APIs Parejas Clínicas (Memorama)
    path('api/memoria/cartas/', views.api_cartas_memoria, name='api_cartas_memoria'),
    path('api/memoria/victoria/', views.api_victoria_memoria, name='api_victoria_memoria'),
    # API Ranking
    path('api/ranking/', api_ranking, name='api_ranking'),
    # Agrega estas líneas donde tienes las demás rutas:
    path('flashcards/', views.vista_flashcards, name='flashcards'),
    path('api/flashcards/', views.api_flashcards, name='api_flashcards'),
]