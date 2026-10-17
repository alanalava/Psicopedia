from django.contrib import admin
from .models import Sintoma, Signo, Sindrome, DiagnosticoDiferencial, CasoClinico, Cuestionario, Pregunta, Opcion

# Esto permite agregar las opciones directamente dentro de la pantalla de la pregunta
class OpcionInline(admin.TabularInline):
    model = Opcion
    extra = 3 # Muestra 3 campos vacíos por defecto

class PreguntaAdmin(admin.ModelAdmin):
    inlines = [OpcionInline]

# Registramos los modelos de Psicopatología
admin.site.register(Sintoma)
admin.site.register(Signo)
admin.site.register(Sindrome)
admin.site.register(DiagnosticoDiferencial)
admin.site.register(CasoClinico)

# Registramos los modelos del Cuestionario
admin.site.register(Cuestionario)
admin.site.register(Pregunta, PreguntaAdmin)