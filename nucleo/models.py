from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class Sintoma(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    def __str__(self): return self.nombre

class Signo(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    def __str__(self): return self.nombre

class Sindrome(models.Model):
    categoria = models.CharField(max_length=100, default='General', help_text="Categoría clínica para agrupar en la biblioteca")
    criterios_diagnosticos = models.TextField(blank=True, null=True, help_text="Criterios principales según DSM-5 o CIE-10")
    notas_clinicas = models.TextField(blank=True, null=True, help_text="Prevalencia, ejemplos clínicos o diagnóstico diferencial")

    nombre = models.CharField(max_length=200, unique=True)
    que_es = models.TextField(verbose_name="¿Qué es?", help_text="Definición principal del síndrome.")
    caracteristicas = models.TextField(help_text="Puntos clave y características principales.")
    resumen_30s = models.TextField(verbose_name="En 30 segundos", help_text="Resumen rápido indispensable.")
    sintomas = models.ManyToManyField(Sintoma, related_name='sindromes', blank=True)
    signos = models.ManyToManyField(Signo, related_name='sindromes', blank=True)
    mapa_mental_url = models.URLField(max_length=500, blank=True, null=True)
    
    def __str__(self): return f"{self.nombre} ({self.categoria})"

class DiagnosticoDiferencial(models.Model):
    sindrome_principal = models.ForeignKey(Sindrome, on_delete=models.CASCADE, related_name='diferenciales_principal')
    sindrome_comparar = models.ForeignKey(Sindrome, on_delete=models.CASCADE, related_name='diferenciales_comparar')
    diferencia_principal = models.TextField(help_text="Ej: Predomina la preocupación (Ansiedad)")
    diferencia_comparar = models.TextField(help_text="Ej: Respuesta ante peligro identificable (Miedo)")
    class Meta:
        unique_together = ('sindrome_principal', 'sindrome_comparar')
        verbose_name_plural = "Diagnósticos Diferenciales"
    def __str__(self): return f"{self.sindrome_principal.nombre} vs {self.sindrome_comparar.nombre}"

class CasoClinico(models.Model):
    sindrome = models.ForeignKey(Sindrome, on_delete=models.CASCADE, related_name='casos')
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(verbose_name="Caso", help_text="Descripción del paciente y situación.")
    analisis_oculto = models.TextField(help_text="Explicación detallada de los signos y síntomas identificados.")
    class Meta:
        verbose_name_plural = "Casos Clínicos"
    def __str__(self): return f"{self.titulo} - {self.sindrome.nombre}"

class Cuestionario(models.Model):
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField()
    def __str__(self): return self.titulo

class Pregunta(models.Model):
    cuestionario = models.ForeignKey(Cuestionario, on_delete=models.CASCADE, related_name='preguntas')
    seccion = models.CharField(max_length=200, default="General", help_text="Ej: PSICOPATOLOGÍA DE LA CONCIENCIA")
    texto = models.TextField()
    explicacion = models.TextField(help_text="Aparece al final para explicar la respuesta.")
    def __str__(self): return self.texto

class Opcion(models.Model):
    pregunta = models.ForeignKey(Pregunta, on_delete=models.CASCADE, related_name='opciones')
    texto = models.CharField(max_length=255)
    es_correcta = models.BooleanField(default=False)
    def __str__(self): return self.texto

class ModuloExpediente(models.Model):
    nombre = models.CharField(max_length=200) 
    descripcion = models.TextField()
    def __str__(self): return self.nombre

class CasoExpediente(models.Model):
    modulo = models.ForeignKey(ModuloExpediente, on_delete=models.CASCADE, related_name='casos')
    seccion = models.CharField(max_length=200, blank=True, null=True)
    descripcion_caso = models.TextField()
    pregunta = models.CharField(max_length=255, default="¿Qué síndrome identificas en este caso?")
    respuesta_correcta = models.CharField(max_length=255)
    def __str__(self): return f"{self.modulo.nombre} - {self.respuesta_correcta}"

# ==========================================
# PERFIL DE JUGADOR (CON AVATAR)
# ==========================================
class PerfilJugador(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE)
    xp = models.IntegerField(default=0)
    racha_actual = models.IntegerField(default=0)
    mejor_racha = models.IntegerField(default=0)
    avatar = models.CharField(max_length=50, default='👻', help_text="Emoji del avatar seleccionado")

    def __str__(self):
        return self.usuario.username

# ==========================================
# ESTA ES LA MAGIA QUE EVITA QUE SE CONGELE EL LOGIN
# (Debe ir afuera de la clase PerfilJugador)
# ==========================================
@receiver(post_save, sender=User)
def crear_o_actualizar_perfil_jugador(sender, instance, created, **kwargs):
    if created:
        PerfilJugador.objects.create(usuario=instance)
    else:
        instance.perfiljugador.save()