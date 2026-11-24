import json
import random
import re
import uuid
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages

# Modelos
from .models import Sindrome, Cuestionario, Pregunta, Opcion, ModuloExpediente, CasoExpediente, PerfilJugador


# ==========================================
# UTILIDADES PARA DIFICULTAD CLÍNICA
# ==========================================
def _ocultar_nombre_en_texto(texto, nombre_concepto):
    """Evita que el enunciado regale la respuesta mencionando el nombre del concepto."""
    if not texto or not nombre_concepto:
        return texto

    patron_exacto = re.compile(rf'\b{re.escape(nombre_concepto.strip())}(?:s|es)?\b', re.IGNORECASE)
    texto_limpio = patron_exacto.sub('[...]', texto)
    return texto_limpio


def _obtener_distractores_misma_categoria(categoria, excluir_nombres, cantidad=3):
    """Obtiene distractores de la misma unidad/categoría para forzar diagnóstico diferencial."""
    excluir_lower = {n.strip().lower() for n in excluir_nombres if n}
    distractores = []

    if categoria:
        candidatos_cat = list(Sindrome.objects.filter(categoria__iexact=categoria.strip()))
        random.shuffle(candidatos_cat)
        for s in candidatos_cat:
            if s.nombre.strip().lower() not in excluir_lower:
                distractores.append(s.nombre)
                excluir_lower.add(s.nombre.strip().lower())
            if len(distractores) == cantidad:
                return distractores

    # Respaldo solo si la unidad tiene menos de 4 conceptos en total
    candidatos_global = list(Sindrome.objects.order_by('?'))
    for s in candidatos_global:
        if s.nombre.strip().lower() not in excluir_lower:
            distractores.append(s.nombre)
            excluir_lower.add(s.nombre.strip().lower())
        if len(distractores) == cantidad:
            break

    return distractores


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
        
    # ==========================================
    # AUTO-LOGIN INVISIBLE PARA LA PRESENTACIÓN
    # ==========================================
    nombre_invitado = f"invitado_{str(uuid.uuid4())[:4]}"
    nuevo_usuario = User.objects.create_user(username=nombre_invitado, password='123')
    nuevo_usuario.perfiljugador.avatar = '👨‍🏫'
    nuevo_usuario.perfiljugador.save()
    login(request, nuevo_usuario)
    return redirect('escritorio')


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
    todos = list(Sindrome.objects.all())
    if len(todos) < 4:
        return JsonResponse({'error': 'No hay suficientes datos en la biblioteca.'})
    
    sindrome_correcto = random.choice(todos)
    distractores = _obtener_distractores_misma_categoria(
        sindrome_correcto.categoria,
        [sindrome_correcto.nombre],
        cantidad=3
    )
    
    opciones = distractores + [sindrome_correcto.nombre]
    random.shuffle(opciones)
    
    fuentes_enunciado = [
        t for t in [sindrome_correcto.caracteristicas, sindrome_correcto.que_es, sindrome_correcto.resumen_30s]
        if t and t.strip()
    ]
    pregunta_cruda = random.choice(fuentes_enunciado)
    pregunta_texto = _ocultar_nombre_en_texto(pregunta_cruda, sindrome_correcto.nombre)
    
    return JsonResponse({
        'id_reto': sindrome_correcto.id,
        'pregunta': pregunta_texto,
        'opciones': opciones
    })


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
    por_categoria = {}
    for s in todos_sindromes:
        cat = s.categoria if s.categoria else "General"
        por_categoria.setdefault(cat, []).append(s)

    # Seleccionar 4 conceptos de la MISMA unidad clínica para exigir precisión conceptual
    categorias_validas = [cat for cat, lista in por_categoria.items() if len(lista) >= 4]
    if categorias_validas:
        cat_elegida = random.choice(categorias_validas)
        pool = por_categoria[cat_elegida][:]
        random.shuffle(pool)
        seleccion = pool[:4]
    else:
        random.shuffle(todos_sindromes)
        seleccion = todos_sindromes[:4]
            
    cartas = []
    for s in seleccion:
        texto_limpio = re.sub(r'\s*\(.*?\)', '', s.resumen_30s).strip()
        texto_limpio = _ocultar_nombre_en_texto(texto_limpio, s.nombre)
        cartas.append({'id_match': s.id, 'texto': s.nombre})
        cartas.append({'id_match': s.id, 'texto': texto_limpio})
        
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

    nombres_biblioteca = {n.strip().lower() for n in Sindrome.objects.values_list('nombre', flat=True)}
    secciones_agrupadas = {}

    for p in cuestionario.preguntas.all():
        nombre_seccion = p.seccion if p.seccion else "General"
        opciones_db = list(p.opciones.all())
        opcion_correcta = next((op for op in opciones_db if op.es_correcta), None)

        # Si las opciones son nombres de conceptos clínicos, forzamos distractores de la misma unidad
        if (
            opcion_correcta
            and opcion_correcta.texto.strip().lower() in nombres_biblioteca
        ):
            distractores = _obtener_distractores_misma_categoria(
                nombre_seccion,
                [opcion_correcta.texto],
                cantidad=3
            )
            opciones_data = [{"texto": opcion_correcta.texto, "es_correcta": True}] + [
                {"texto": d, "es_correcta": False} for d in distractores
            ]
        else:
            opciones_data = [{"texto": op.texto, "es_correcta": op.es_correcta} for op in opciones_db]

        random.shuffle(opciones_data)

        texto_pregunta = p.texto
        if opcion_correcta:
            texto_pregunta = _ocultar_nombre_en_texto(texto_pregunta, opcion_correcta.texto)

        pregunta_data = {
            "texto": texto_pregunta,
            "explicacion": p.explicacion,
            "opciones": opciones_data
        }
        secciones_agrupadas.setdefault(nombre_seccion, []).append(pregunta_data)

    secciones_data = []
    for nombre, preguntas_lista in secciones_agrupadas.items():
        random.shuffle(preguntas_lista)
        secciones_data.append({"nombre": nombre, "preguntas": preguntas_lista})

    return JsonResponse({"secciones": secciones_data})


@login_required
def obtener_expedientes_api(request):
    modulos = ModuloExpediente.objects.all()
    data = []
    for modulo in modulos:
        casos_list = []
        for caso in modulo.casos.all():
            seccion = caso.seccion if caso.seccion else "General"
            descripcion_segura = _ocultar_nombre_en_texto(caso.descripcion_caso, caso.respuesta_correcta)
            distractores = _obtener_distractores_misma_categoria(
                seccion,
                [caso.respuesta_correcta],
                cantidad=3
            )
            opciones = distractores + [caso.respuesta_correcta]
            random.shuffle(opciones)

            casos_list.append({
                "seccion": seccion,
                "descripcion": descripcion_segura,
                "pregunta": caso.pregunta,
                "respuesta_correcta": caso.respuesta_correcta,
                "opciones": opciones,
            })

        random.shuffle(casos_list)
        data.append({"nombre": modulo.nombre, "descripcion": modulo.descripcion, "casos": casos_list})
    return JsonResponse({"modulos": data})


@login_required
def api_ranking(request):
    top_jugadores = PerfilJugador.objects.order_by('-xp')[:10]
    
    ranking = []
    for idx, perfil in enumerate(top_jugadores):
        ranking.append({
            'posicion': idx + 1,
            'nombre': perfil.usuario.username.upper(),
            'avatar': perfil.avatar,
            'xp': perfil.xp,
            'racha': perfil.mejor_racha,
            'soy_yo': perfil.usuario == request.user
        })
        
    return JsonResponse({'ranking': ranking})


@login_required
def vista_flashcards(request):
    return render(request, 'flashcards.html')


@login_required
def api_flashcards(request):
    sindromes = list(Sindrome.objects.order_by('?')[:20])
    
    mazo = []
    for s in sindromes:
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
    return redirect('login')