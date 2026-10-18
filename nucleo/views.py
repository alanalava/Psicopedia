import json
import random
import re
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages

# Modelos
from .models import Sindrome, Cuestionario, Pregunta, Opcion, ModuloExpediente, CasoExpediente, PerfilJugador

def vista_registro(request):
    if request.user.is_authenticated:
        return redirect('escritorio')
        
    if request.method == 'POST':
        usuario_nombre = request.POST.get('username')
        clave = request.POST.get('password')
        clave_conf = request.POST.get('password_conf')
        avatar = request.POST.get('avatar', '👻')

        # 1. Validar que las contraseñas sean iguales
        if clave != clave_conf:
            messages.error(request, "Las contraseñas no coinciden.")
            return redirect('registro')
            
        # 2. Validar que el usuario no exista ya
        if User.objects.filter(username=usuario_nombre).exists():
            messages.error(request, "Ese nombre de usuario ya está en uso.")
            return redirect('registro')

        # 3. Crear el usuario en la base de datos
        user = User.objects.create_user(username=usuario_nombre, password=clave)
        
        # 4. Guardar el avatar que eligió en su perfil (creado por tu signal)
        user.perfiljugador.avatar = avatar
        user.perfiljugador.save()

        # 5. INICIAR SESIÓN AUTOMÁTICAMENTE
        login(request, user)
        
        # 6. Redirigir directo al Escritorio sin pasar por el Login
        return redirect('escritorio')

    # Si entra normal por la URL, le mostramos el formulario
    return render(request, 'registro.html')

def vista_login(request):
    if request.user.is_authenticated:
        return redirect('escritorio')
        
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            usuario = form.get_user()
            login(request, usuario)
            return redirect('escritorio')
    else:
        form = AuthenticationForm()
        
    return render(request, 'login.html', {'form': form})

def vista_logout(request):
    logout(request)
    return redirect('login')

@login_required
def vista_escritorio(request):
    return render(request, 'escritorio.html')

@login_required
def vista_inicio(request):
    return render(request, 'cuestionario.html')

@login_required
def vista_biblioteca(request):
    todos_los_sindromes = Sindrome.objects.all().order_by('categoria', 'nombre')
    biblioteca_agrupada = {}
    for s in todos_los_sindromes:
        cat = s.categoria if s.categoria else "General"
        if cat not in biblioteca_agrupada:
            biblioteca_agrupada[cat] = []
        biblioteca_agrupada[cat].append(s)
        
    return render(request, 'biblioteca.html', {'biblioteca_agrupada': biblioteca_agrupada})

@login_required
def vista_expedientes(request):
    return render(request, 'expedientes.html')

@login_required
def vista_minijuego(request):
    perfil, created = PerfilJugador.objects.get_or_create(usuario=request.user)
    return render(request, 'minijuego.html', {'perfil': perfil})

@login_required
def api_reto_minijuego(request):
    sindromes = list(Sindrome.objects.order_by('?')[:4])
    if len(sindromes) < 4:
        return JsonResponse({'error': 'No hay suficientes datos en la biblioteca.'})
    
    sindrome_correcto = sindromes[0]
    opciones = [s.nombre for s in sindromes]
    random.shuffle(opciones)
    
    pregunta_texto = random.choice([sindrome_correcto.que_es, sindrome_correcto.resumen_30s])
    return JsonResponse({'id_reto': sindrome_correcto.id, 'pregunta': pregunta_texto, 'opciones': opciones})

@login_required
def api_responder_minijuego(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        sindrome = Sindrome.objects.get(id=data.get('id_reto'))
        perfil = PerfilJugador.objects.get(usuario=request.user)
        
        es_correcta = (sindrome.nombre == data.get('respuesta'))
        if es_correcta:
            perfil.racha_actual += 1
            multiplicador = 5 if perfil.racha_actual >= 5 else (3 if perfil.racha_actual >= 3 else (2 if perfil.racha_actual >= 2 else 1))
            puntos_ganados = 10 * multiplicador
            perfil.xp += puntos_ganados
            if perfil.racha_actual > perfil.mejor_racha: 
                perfil.mejor_racha = perfil.racha_actual
            mensaje = f"¡Fuego! +{puntos_ganados} XP (Racha x{multiplicador})"
        else:
            perfil.racha_actual = 0
            mensaje = "¡Fallaste! La racha vuelve a 0."
            
        perfil.save()
        return JsonResponse({
            'es_correcta': es_correcta, 
            'xp_total': perfil.xp, 
            'racha_actual': perfil.racha_actual, 
            'mejor_racha': perfil.mejor_racha, 
            'mensaje': mensaje, 
            'respuesta_correcta': sindrome.nombre
        })

@login_required
def vista_memoria(request):
    perfil, created = PerfilJugador.objects.get_or_create(usuario=request.user)
    return render(request, 'memoria.html', {'perfil': perfil})

@login_required
def api_cartas_memoria(request):
    todos_sindromes = list(Sindrome.objects.all())
    random.shuffle(todos_sindromes)
    sindromes_seleccionados = []
    categorias_usadas = set()
    
    for s in todos_sindromes:
        cat = s.categoria if s.categoria else "General"
        if cat not in categorias_usadas:
            texto_limpio = re.sub(r'\s*\(.*?\)', '', s.resumen_30s).strip()
            sindromes_seleccionados.append((s, texto_limpio))
            categorias_usadas.add(cat)
            
        if len(sindromes_seleccionados) == 4:
            break
            
    cartas = []
    for s, texto_carta in sindromes_seleccionados:
        cartas.append({'id_match': s.id, 'texto': s.nombre})
        cartas.append({'id_match': s.id, 'texto': texto_carta})
        
    random.shuffle(cartas)
    return JsonResponse({'cartas': cartas})

@login_required
def api_victoria_memoria(request):
    if request.method == 'POST':
        perfil = PerfilJugador.objects.get(usuario=request.user)
        perfil.xp += 50
        perfil.save()
        return JsonResponse({'xp_total': perfil.xp, 'mensaje': '¡+50 XP ganados!'})

@login_required
def obtener_cuestionario_api(request):
    cuestionario = Cuestionario.objects.first()
    if not cuestionario:
        return JsonResponse({"error": "No hay cuestionarios disponibles."})

    secciones_agrupadas = {}
    for p in cuestionario.preguntas.all():
        nombre_seccion = p.seccion if p.seccion else "General"
        
        # AQUÍ ESTÁ EL CAMBIO: Solo extraemos las opciones, YA NO usamos random.shuffle()
        opciones_data = [{"texto": op.texto, "es_correcta": op.es_correcta} for op in p.opciones.all()]
        
        pregunta_data = {"texto": p.texto, "explicacion": p.explicacion, "opciones": opciones_data}
        if nombre_seccion not in secciones_agrupadas:
            secciones_agrupadas[nombre_seccion] = []
        secciones_agrupadas[nombre_seccion].append(pregunta_data)

    secciones_data = [{"nombre": nombre, "preguntas": preguntas_lista} for nombre, preguntas_lista in secciones_agrupadas.items()]
    return JsonResponse({"secciones": secciones_data})

@login_required
def obtener_expedientes_api(request):
    modulos = ModuloExpediente.objects.all()
    data = []
    for modulo in modulos:
        casos_list = [{"seccion": caso.seccion if caso.seccion else "General", "descripcion": caso.descripcion_caso, "pregunta": caso.pregunta, "respuesta_correcta": caso.respuesta_correcta} for caso in modulo.casos.all()]
        data.append({"nombre": modulo.nombre, "descripcion": modulo.descripcion, "casos": casos_list})
    return JsonResponse({"modulos": data})


# Agrégalo al final de tu views.py
@login_required
def api_ranking(request):
    # Traemos los 10 mejores perfiles ordenados por XP de mayor a menor
    top_jugadores = PerfilJugador.objects.order_by('-xp')[:10]
    
    ranking = []
    for idx, perfil in enumerate(top_jugadores):
        ranking.append({
            'posicion': idx + 1,
            'nombre': perfil.usuario.username.upper(),
            'avatar': perfil.avatar,
            'xp': perfil.xp,
            'racha': perfil.mejor_racha,
            'soy_yo': perfil.usuario == request.user  # Para resaltar al usuario actual en la lista
        })
        
    return JsonResponse({'ranking': ranking})


# --- Añadir al final de nucleo/views.py ---

@login_required
def vista_flashcards(request):
    return render(request, 'flashcards.html')

@login_required
def api_flashcards(request):
    # Traemos 20 síndromes al azar para el mazo de estudio
    sindromes = list(Sindrome.objects.order_by('?')[:20])
    
    mazo = []
    for s in sindromes:
        # Frente: El nombre del síndrome. Dorso: El resumen o definición.
        mazo.append({
            'frente': s.nombre,
            'dorso': s.resumen_30s,
            'categoria': s.categoria if s.categoria else 'General'
        })
        
    return JsonResponse({'mazo': mazo})


# ==========================================
# INTERCEPTOR DE ERRORES CSRF (BOTÓN ATRÁS)
# ==========================================
def error_csrf_personalizado(request, reason=""):
    from django.shortcuts import redirect
    # Redirección totalmente silenciosa, sin mensajes de error
    return redirect('login')