import json
import random
import re
import unicodedata
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
# SANITIZACIÓN DE DATOS Y DIFICULTAD CLÍNICA
# ==========================================
DEFINICIONES_RESPALDO = {
    "desorientacion alopsiquica en espacio": "Incapacidad para identificar correctamente el lugar físico, entorno o ubicación geográfica en la que se encuentra.",
    "desorientacion alopsiquica en tiempo": "Pérdida de la noción de la fecha actual, el día de la semana, el mes, el año o el momento del día.",
    "desorientacion autopsiquica o en persona": "Alteración en el reconocimiento de la propia identidad, datos biográficos básicos o rol personal.",
}


def _normalizar_clave(texto):
    if not texto:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def _es_texto_generico(texto):
    clave = _normalizar_clave(texto)
    return (
        not clave
        or clave.startswith("fenomeno descrito dentro de esta clasificacion")
        or clave.startswith("concepto semiologico evaluado en la unidad")
        or clave.startswith("informacion clinica extraida directamente del banco oficial")
    )


def _es_pregunta_clasificacion(texto):
    clave = _normalizar_clave(texto)
    return (
        "en cual de las siguientes clasificaciones se ubica" in clave
        or clave.startswith("en cual de las siguientes clasificaciones")
    )


def _ocultar_nombre_en_texto(texto, nombre_concepto):
    if not texto or not nombre_concepto:
        return texto
    patron = re.compile(rf"\b{re.escape(nombre_concepto.strip())}(?:s|es)?\b", re.IGNORECASE)
    return patron.sub("[...]", texto)


def _limpiar_sindrome(s):
    """Normaliza cada registro de Biblioteca para corregir filas invertidas o textos de relleno."""
    nombre = (s.nombre or "").strip()
    que_es = (s.que_es or "").strip()
    caracteristicas = (s.caracteristicas or "").strip()
    resumen = (s.resumen_30s or "").strip()
    categoria = (s.categoria or "General").strip()

    # Descartar encabezados de unidad o preguntas de clasificación guardadas como concepto
    if _normalizar_clave(nombre).startswith("psicopatologia de") or _es_pregunta_clasificacion(que_es):
        return None

    # Corregir registros invertidos:
    # nombre = "Estado de ánimo equilibrado..." | que_es = "¿Cuál de los siguientes enunciados corresponde al término Eutimia?"
    match_inv = re.match(
        r"^¿?\s*Cu[aá]l de los siguientes enunciados corresponde al t[eé]rmino\s+(.+?)\s*\??$",
        que_es,
        re.IGNORECASE,
    )
    if match_inv:
        termino_real = match_inv.group(1).strip(" .?¿")
        definicion_real = nombre
        nombre = termino_real
        que_es = definicion_real

    # Si aún queda una pregunta en que_es, intentar rescatar desde resumen_30s o descartar
    if que_es.startswith("¿"):
        if resumen and not resumen.startswith("¿") and not _es_texto_generico(resumen):
            que_es = resumen
        else:
            return None

    # Reemplazar placeholder genérico por definición clínica real si aplica
    if _es_texto_generico(que_es):
        respaldo = DEFINICIONES_RESPALDO.get(_normalizar_clave(nombre))
        if respaldo:
            que_es = respaldo
        elif resumen and not resumen.startswith("¿") and not _es_texto_generico(resumen):
            que_es = resumen
        else:
            que_es = ""

    if _es_texto_generico(caracteristicas) or caracteristicas.startswith("¿"):
        caracteristicas = ""

    if _es_texto_generico(resumen) or resumen.startswith("¿"):
        resumen = que_es

    # Evitar que una definición larga quede como nombre de opción
    es_nombre_corto = len(nombre) <= 75 and not nombre.startswith("¿")

    return {
        "id": s.id,
        "nombre": nombre,
        "que_es": que_es,
        "caracteristicas": caracteristicas,
        "resumen_30s": resumen,
        "categoria": categoria,
        "cat_norm": _normalizar_clave(categoria),
        "es_nombre_corto": es_nombre_corto,
    }


def _obtener_sindromes_limpios():
    limpios = []
    vistos = set()
    for s in Sindrome.objects.all().order_by("categoria", "nombre"):
        item = _limpiar_sindrome(s)
        if not item:
            continue
        clave = (item["cat_norm"], _normalizar_clave(item["nombre"]))
        if clave in vistos:
            continue
        vistos.add(clave)
        limpios.append(item)
    return limpios


def _obtener_distractores_misma_categoria(categoria, excluir_nombres, cantidad=3, permitir_sindromes=True):
    """Obtiene distractores exclusivamente de la misma unidad/categoría (sin rellenar con otras unidades)."""
    cat_norm = _normalizar_clave(categoria)
    excluir_norm = {_normalizar_clave(n) for n in excluir_nombres if n}
    candidatos = [
        item["nombre"]
        for item in _obtener_sindromes_limpios()
        if item["cat_norm"] == cat_norm
        and item["es_nombre_corto"]
        and _normalizar_clave(item["nombre"]) not in excluir_norm
        and (permitir_sindromes or "sindrome" not in _normalizar_clave(item["nombre"]))
    ]
    random.shuffle(candidatos)
    return candidatos[:cantidad]


# ==========================================
# VISTAS DE AUTENTICACIÓN Y NAVEGACIÓN
# ==========================================
def vista_registro(request):
    if request.user.is_authenticated:
        return redirect('escritorio')
        
    if request.method == 'POST':
        usuario_nombre = request.POST.get('username')
        clave = request.POST.get('password')
        clave_conf = request.POST.get('password_conf')
        avatar = request.POST.get('avatar', '👻')

        if clave != clave_conf:
            messages.error(request, "Las contraseñas no coinciden.")
            return redirect('registro')
            
        if User.objects.filter(username=usuario_nombre).exists():
            messages.error(request, "Ese nombre de usuario ya está en uso.")
            return redirect('registro')

        user = User.objects.create_user(username=usuario_nombre, password=clave)
        user.perfiljugador.avatar = avatar
        user.perfiljugador.save()

        login(request, user)
        return redirect('escritorio')

    return render(request, 'registro.html')


def vista_login(request):
    if request.user.is_authenticated:
        return redirect('escritorio')
        
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


# ==========================================
# BIBLIOTECA
# ==========================================
@login_required
def vista_biblioteca(request):
    biblioteca_agrupada = {}
    for item in _obtener_sindromes_limpios():
        if not item["que_es"] and not item["caracteristicas"]:
            continue
        cat = item["categoria"] or "General"
        biblioteca_agrupada.setdefault(cat, []).append(item)
        
    return render(request, 'biblioteca.html', {'biblioteca_agrupada': biblioteca_agrupada})


# ==========================================
# EXPEDIENTES CLÍNICOS
# ==========================================
@login_required
def vista_expedientes(request):
    return render(request, 'expedientes.html')


@login_required
def obtener_expedientes_api(request):
    mapa_definiciones = {
        _normalizar_clave(item["nombre"]): item["que_es"]
        for item in _obtener_sindromes_limpios()
        if item["que_es"]
    }

    modulos = ModuloExpediente.objects.all()
    data = []
    for modulo in modulos:
        casos_list = []
        for caso in modulo.casos.all():
            seccion = caso.seccion if caso.seccion else "General"
            desc = (caso.descripcion_caso or "").strip()

            # Reemplazar texto genérico repetido por el concepto clínico real
            if _es_texto_generico(desc):
                clave_resp = _normalizar_clave(caso.respuesta_correcta)
                desc = mapa_definiciones.get(clave_resp) or DEFINICIONES_RESPALDO.get(clave_resp) or desc

            desc_segura = _ocultar_nombre_en_texto(desc, caso.respuesta_correcta)
            distractores = _obtener_distractores_misma_categoria(
                seccion,
                [caso.respuesta_correcta],
                cantidad=3,
                permitir_sindromes=("sindrome" in _normalizar_clave(seccion)),
            )
            opciones = distractores + [caso.respuesta_correcta]
            random.shuffle(opciones)

            casos_list.append({
                "seccion": seccion,
                "descripcion": desc_segura,
                "pregunta": caso.pregunta,
                "respuesta_correcta": caso.respuesta_correcta,
                "opciones": opciones,
            })

        random.shuffle(casos_list)
        data.append({"nombre": modulo.nombre, "descripcion": modulo.descripcion, "casos": casos_list})
    return JsonResponse({"modulos": data})


# ==========================================
# MINIJUEGO: RACHA PSICOPÉDICA
# ==========================================
@login_required
def vista_minijuego(request):
    perfil, created = PerfilJugador.objects.get_or_create(usuario=request.user)
    return render(request, 'minijuego.html', {'perfil': perfil})


@login_required
def api_reto_minijuego(request):
    candidatos = [
        item for item in _obtener_sindromes_limpios()
        if item["es_nombre_corto"] and item["que_es"] and not _es_texto_generico(item["que_es"])
    ]
    if len(candidatos) < 4:
        return JsonResponse({'error': 'No hay suficientes datos válidos en la biblioteca.'})
    
    # Elegir solo conceptos de categorías que tengan al menos 3 conceptos válidos
    por_cat = {}
    for item in candidatos:
        por_cat.setdefault(item["cat_norm"], []).append(item)
    cats_validas = [c for c, lista in por_cat.items() if len(lista) >= 3]
    cat_elegida = random.choice(cats_validas) if cats_validas else None
    pool = por_cat[cat_elegida] if cat_elegida else candidatos

    correcto = random.choice(pool)
    distractores = _obtener_distractores_misma_categoria(
        correcto["categoria"],
        [correcto["nombre"]],
        cantidad=3,
        permitir_sindromes=("sindrome" in correcto["cat_norm"]),
    )
    
    opciones = distractores + [correcto["nombre"]]
    random.shuffle(opciones)
    
    pregunta_texto = _ocultar_nombre_en_texto(correcto["que_es"], correcto["nombre"])
    return JsonResponse({'id_reto': correcto["id"], 'pregunta': pregunta_texto, 'opciones': opciones})


@login_required
def api_responder_minijuego(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        sindrome = Sindrome.objects.get(id=data.get('id_reto'))
        limpio = _limpiar_sindrome(sindrome)
        nombre_correcto = limpio["nombre"] if limpio else sindrome.nombre
        perfil = PerfilJugador.objects.get(usuario=request.user)
        
        es_correcta = (_normalizar_clave(nombre_correcto) == _normalizar_clave(data.get('respuesta', '')))
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
            'respuesta_correcta': nombre_correcto
        })


# ==========================================
# MINIJUEGO: PAREJAS CLÍNICAS (MEMORIA)
# ==========================================
@login_required
def vista_memoria(request):
    perfil, created = PerfilJugador.objects.get_or_create(usuario=request.user)
    return render(request, 'memoria.html', {'perfil': perfil})


@login_required
def api_cartas_memoria(request):
    candidatos = [
        item for item in _obtener_sindromes_limpios()
        if item["es_nombre_corto"] and item["que_es"] and not _es_texto_generico(item["que_es"])
    ]
    por_categoria = {}
    for item in candidatos:
        por_categoria.setdefault(item["cat_norm"], []).append(item)

    categorias_validas = [cat for cat, lista in por_categoria.items() if len(lista) >= 4]
    if categorias_validas:
        cat_elegida = random.choice(categorias_validas)
        pool = por_categoria[cat_elegida][:]
        random.shuffle(pool)
        seleccion = pool[:4]
    else:
        random.shuffle(candidatos)
        seleccion = candidatos[:4]
            
    cartas = []
    for item in seleccion:
        texto_limpio = re.sub(r'\s*\(.*?\)', '', item["que_es"]).strip()
        texto_limpio = _ocultar_nombre_en_texto(texto_limpio, item["nombre"])
        cartas.append({'id_match': item["id"], 'texto': item["nombre"]})
        cartas.append({'id_match': item["id"], 'texto': texto_limpio})
        
    random.shuffle(cartas)
    return JsonResponse({'cartas': cartas})


@login_required
def api_victoria_memoria(request):
    if request.method == 'POST':
        perfil = PerfilJugador.objects.get(usuario=request.user)
        perfil.xp += 50
        perfil.save()
        return JsonResponse({'xp_total': perfil.xp, 'mensaje': '¡+50 XP ganados!'})


# ==========================================
# SIMULADOR / CUESTIONARIO (SOLO TEÓRICO)
# ==========================================
@login_required
def obtener_cuestionario_api(request):
    cuestionario = Cuestionario.objects.first()
    if not cuestionario:
        return JsonResponse({"error": "No hay cuestionarios disponibles."})

    sindromes_limpios = _obtener_sindromes_limpios()
    nombres_biblioteca = {_normalizar_clave(item["nombre"]) for item in sindromes_limpios}
    secciones_agrupadas = {}

    for p in cuestionario.preguntas.all():
        # Eliminar preguntas de clasificación ("¿En cuál de las siguientes clasificaciones se ubica...?")
        if _es_pregunta_clasificacion(p.texto):
            continue

        nombre_seccion = p.seccion if p.seccion else "General"
        es_modulo_sindrome = "sindrome" in _normalizar_clave(nombre_seccion)
        opciones_db = list(p.opciones.all())
        opcion_correcta = next((op for op in opciones_db if op.es_correcta), None)

        if opcion_correcta and _normalizar_clave(opcion_correcta.texto) in nombres_biblioteca:
            distractores = _obtener_distractores_misma_categoria(
                nombre_seccion,
                [opcion_correcta.texto],
                cantidad=3,
                permitir_sindromes=es_modulo_sindrome,
            )
            opciones_data = [{"texto": opcion_correcta.texto, "es_correcta": True}] + [
                {"texto": d, "es_correcta": False} for d in distractores
            ]
        else:
            opciones_data = []
            for op in opciones_db:
                # En módulos de síntomas/procesos, quitar distractores que digan "Síndrome..."
                if (
                    not op.es_correcta
                    and not es_modulo_sindrome
                    and "sindrome" in _normalizar_clave(op.texto)
                ):
                    continue
                opciones_data.append({"texto": op.texto, "es_correcta": op.es_correcta})

        random.shuffle(opciones_data)

        texto_pregunta = p.texto
        if opcion_correcta:
            texto_pregunta = _ocultar_nombre_en_texto(texto_pregunta, opcion_correcta.texto)

        pregunta_data = {
            "texto": texto_pregunta,
            "explicacion": p.explicacion,
            "opciones": opciones_data,
        }
        secciones_agrupadas.setdefault(nombre_seccion, []).append(pregunta_data)

    secciones_data = []
    for nombre, preguntas_lista in secciones_agrupadas.items():
        random.shuffle(preguntas_lista)
        secciones_data.append({"nombre": nombre, "preguntas": preguntas_lista[:10]})

    return JsonResponse({"secciones": secciones_data})


# ==========================================
# RANKING Y TARJETAS DE ESTUDIO (FLASHCARDS)
# ==========================================
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
    candidatos = [
        item for item in _obtener_sindromes_limpios()
        if item["es_nombre_corto"] and item["que_es"] and not _es_texto_generico(item["que_es"])
    ]
    por_categoria = {}
    for item in candidatos:
        por_categoria.setdefault(item["cat_norm"], []).append(item)

    # Seleccionar una sola unidad con al menos 4 conceptos para que los distractores pertenezcan al mismo proceso
    categorias_validas = [cat for cat, lista in por_categoria.items() if len(lista) >= 4]
    if categorias_validas:
        cat_elegida = random.choice(categorias_validas)
        pool = por_categoria[cat_elegida][:]
        random.shuffle(pool)
        seleccion = pool[:10]
    else:
        random.shuffle(candidatos)
        seleccion = candidatos[:10]
    
    mazo = []
    for item in seleccion:
        mazo.append({
            'frente': item["nombre"],
            'dorso': item["que_es"],
            'categoria': item["categoria"],
        })
        
    return JsonResponse({'mazo': mazo})


# ==========================================
# INTERCEPTOR DE ERRORES CSRF (BOTÓN ATRÁS)
# ==========================================
def error_csrf_personalizado(request, reason=""):
    return redirect('login')