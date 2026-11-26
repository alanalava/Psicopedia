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
# SANITIZACIÓN DE DATOS, CACHÉ Y DIFICULTAD
# ==========================================
DEFINICIONES_RESPALDO = {
    "desorientacion alopsiquica en espacio": "Incapacidad para identificar correctamente el lugar físico, entorno o ubicación geográfica en la que se encuentra.",
    "desorientacion alopsiquica en tiempo": "Pérdida de la noción de la fecha actual, el día de la semana, el mes, el año o el momento del día.",
    "desorientacion autopsiquica o en persona": "Alteración en el reconocimiento de la propia identidad, datos biográficos básicos o rol personal.",
    "desorientacion global": "Pérdida conjunta de la orientación en tiempo, espacio y respecto a la propia persona.",
    "doble orientacion": "Coexistencia de una orientación correcta respecto a la realidad con referencias delirantes o erróneas.",
}

EXCLUSIONES_POR_UNIDAD = {
    "funciones de relacion": {"autoscopia", "autoscopia externa", "autoscopia interna"},
}

_CACHE_BIBLIOTECA = {
    "firma": None,
    "items": [],
    "por_unidad": {},
    "mapa_definiciones": {},
}


def _normalizar_clave(texto):
    if not texto:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def _quitar_prefijo_opcion(texto):
    """Elimina prefijos como 'A) ', 'B) ', 'C) ', 'D) ' guardados en la base de datos."""
    if not texto:
        return ""
    return re.sub(r"^\s*[A-Da-d][\)\.\-:]\s*", "", texto).strip()


def _normalizar_unidad(texto):
    """Unifica nombres como 'Unidad: Orientación' y 'Psicopatología De La Orientación'."""
    clave = _normalizar_clave(texto)
    clave = re.sub(r"^(unidad\s*\d*\s*[:\-]?\s*)", "", clave)
    clave = re.sub(r"^psicopatologia\s+(de\s+las|de\s+los|de\s+la|del|de)\s+", "", clave)
    return clave.strip()


def _es_texto_generico_o_con_respuesta(texto):
    """Detecta textos de relleno o frases que revelan la respuesta/literal del banco."""
    clave = _normalizar_clave(texto)
    return (
        not clave
        or clave.startswith("fenomeno descrito dentro de esta clasificacion")
        or clave.startswith("concepto semiologico evaluado en la unidad")
        or clave.startswith("informacion clinica extraida directamente del banco oficial")
        or "banco oficial" in clave
        or "opcion correcta" in clave
        or "respuesta correcta" in clave
        or "la respuesta es" in clave
        or bool(re.search(r"\b(literal|inciso|opcion)\s+[a-d]\b", clave))
    )


def _es_pregunta_clasificacion(texto):
    clave = _normalizar_clave(texto)
    return (
        "en cual de las siguientes clasificaciones se ubica" in clave
        or clave.startswith("en cual de las siguientes clasificaciones")
    )


def _es_termino_excluido_en_unidad(unidad_norm, nombre_texto):
    excluidos = EXCLUSIONES_POR_UNIDAD.get(unidad_norm)
    if not excluidos:
        return False
    nombre_norm = _normalizar_clave(_quitar_prefijo_opcion(nombre_texto))
    return any(ex in nombre_norm for ex in excluidos)


def _ocultar_nombre_en_texto(texto, nombre_concepto):
    if not texto or not nombre_concepto:
        return texto
    nombre_limpio = _quitar_prefijo_opcion(nombre_concepto)
    patron = re.compile(rf"\b{re.escape(nombre_limpio)}(?:s|es)?\b", re.IGNORECASE)
    return patron.sub("[...]", texto)


def _limpiar_sindrome(s):
    """Normaliza cada registro de Biblioteca para corregir filas invertidas o textos de relleno."""
    nombre = _quitar_prefijo_opcion((s.nombre or "").strip())
    que_es = (s.que_es or "").strip()
    caracteristicas = (s.caracteristicas or "").strip()
    resumen = (s.resumen_30s or "").strip()
    categoria = (s.categoria or "General").strip()
    unidad_norm = _normalizar_unidad(categoria)

    if (
        _normalizar_clave(nombre).startswith("psicopatologia de")
        or _es_pregunta_clasificacion(que_es)
        or _es_termino_excluido_en_unidad(unidad_norm, nombre)
    ):
        return None

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

    if que_es.startswith("¿"):
        if resumen and not resumen.startswith("¿") and not _es_texto_generico_o_con_respuesta(resumen):
            que_es = resumen
        else:
            return None

    if _es_texto_generico_o_con_respuesta(que_es):
        respaldo = DEFINICIONES_RESPALDO.get(_normalizar_clave(nombre))
        if respaldo:
            que_es = respaldo
        elif resumen and not resumen.startswith("¿") and not _es_texto_generico_o_con_respuesta(resumen):
            que_es = resumen
        else:
            que_es = ""

    if _es_texto_generico_o_con_respuesta(caracteristicas) or caracteristicas.startswith("¿"):
        caracteristicas = ""

    if _es_texto_generico_o_con_respuesta(resumen) or resumen.startswith("¿"):
        resumen = que_es

    es_nombre_corto = len(nombre) <= 75 and not nombre.startswith("¿")

    return {
        "id": s.id,
        "nombre": nombre,
        "que_es": que_es,
        "caracteristicas": caracteristicas,
        "resumen_30s": resumen,
        "categoria": categoria,
        "unidad_norm": unidad_norm,
        "es_nombre_corto": es_nombre_corto,
    }


def _obtener_indice_biblioteca():
    """Carga y cachea en memoria la biblioteca depurada para evitar consultas repetidas en bucles."""
    total = Sindrome.objects.count()
    ultimo_id = Sindrome.objects.order_by("-id").values_list("id", flat=True).first()
    firma = (total, ultimo_id)

    if _CACHE_BIBLIOTECA["firma"] == firma and _CACHE_BIBLIOTECA["items"]:
        return _CACHE_BIBLIOTECA

    limpios = []
    por_unidad = {}
    mapa_definiciones = dict(DEFINICIONES_RESPALDO)
    vistos = set()

    for s in Sindrome.objects.all().order_by("categoria", "nombre"):
        item = _limpiar_sindrome(s)
        if not item:
            continue
        clave_nombre = _normalizar_clave(item["nombre"])
        clave = (item["unidad_norm"], clave_nombre)
        if clave in vistos:
            continue
        vistos.add(clave)
        limpios.append(item)
        por_unidad.setdefault(item["unidad_norm"], []).append(item)
        if item["que_es"] and not _es_texto_generico_o_con_respuesta(item["que_es"]):
            mapa_definiciones[clave_nombre] = item["que_es"]

    _CACHE_BIBLIOTECA["firma"] = firma
    _CACHE_BIBLIOTECA["items"] = limpios
    _CACHE_BIBLIOTECA["por_unidad"] = por_unidad
    _CACHE_BIBLIOTECA["mapa_definiciones"] = mapa_definiciones
    return _CACHE_BIBLIOTECA


def _obtener_distractores_misma_unidad(
    categoria, excluir_nombres, cantidad=3, permitir_sindromes=True, indice=None
):
    """Obtiene distractores exclusivamente de la misma unidad clínica en O(1)."""
    if indice is None:
        indice = _obtener_indice_biblioteca()

    unidad_norm = _normalizar_unidad(categoria)
    excluir_norm = {_normalizar_clave(_quitar_prefijo_opcion(n)) for n in excluir_nombres if n}
    candidatos = [
        item["nombre"]
        for item in indice["por_unidad"].get(unidad_norm, [])
        if item["es_nombre_corto"]
        and _normalizar_clave(item["nombre"]) not in excluir_norm
        and not _es_termino_excluido_en_unidad(unidad_norm, item["nombre"])
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
    indice = _obtener_indice_biblioteca()
    biblioteca_agrupada = {}
    for item in indice["items"]:
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
    indice = _obtener_indice_biblioteca()
    mapa_definiciones = indice["mapa_definiciones"]

    modulos = ModuloExpediente.objects.prefetch_related('casos').all()
    data = []
    for modulo in modulos:
        casos_list = []
        for caso in modulo.casos.all():
            seccion = caso.seccion if caso.seccion else "General"
            desc = (caso.descripcion_caso or "").strip()
            resp_limpia = _quitar_prefijo_opcion(caso.respuesta_correcta)

            if _es_texto_generico_o_con_respuesta(desc):
                clave_resp = _normalizar_clave(resp_limpia)
                desc = mapa_definiciones.get(clave_resp, "")

            if _es_texto_generico_o_con_respuesta(desc):
                continue

            desc_segura = _ocultar_nombre_en_texto(desc, resp_limpia)
            distractores = _obtener_distractores_misma_unidad(
                seccion,
                [resp_limpia],
                cantidad=3,
                permitir_sindromes=("sindrome" in _normalizar_unidad(seccion)),
                indice=indice,
            )
            opciones = distractores + [resp_limpia]
            random.shuffle(opciones)

            casos_list.append({
                "seccion": seccion,
                "descripcion": desc_segura,
                "pregunta": caso.pregunta,
                "respuesta_correcta": resp_limpia,
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
    indice = _obtener_indice_biblioteca()
    candidatos = [
        item for item in indice["items"]
        if item["es_nombre_corto"] and item["que_es"] and not _es_texto_generico_o_con_respuesta(item["que_es"])
    ]
    if len(candidatos) < 3:
        return JsonResponse({'error': 'No hay suficientes datos válidos en la biblioteca.'})
    
    por_unidad = {}
    for item in candidatos:
        por_unidad.setdefault(item["unidad_norm"], []).append(item)
    unidades_validas = [u for u, lista in por_unidad.items() if len(lista) >= 3]
    unidad_elegida = random.choice(unidades_validas) if unidades_validas else None
    pool = por_unidad[unidad_elegida] if unidad_elegida else candidatos

    correcto = random.choice(pool)
    distractores = _obtener_distractores_misma_unidad(
        correcto["categoria"],
        [correcto["nombre"]],
        cantidad=3,
        permitir_sindromes=("sindrome" in correcto["unidad_norm"]),
        indice=indice,
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
        nombre_correcto = limpio["nombre"] if limpio else _quitar_prefijo_opcion(sindrome.nombre)
        perfil = PerfilJugador.objects.get(usuario=request.user)
        
        es_correcta = (
            _normalizar_clave(nombre_correcto)
            == _normalizar_clave(_quitar_prefijo_opcion(data.get('respuesta', '')))
        )
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
    indice = _obtener_indice_biblioteca()
    candidatos = [
        item for item in indice["items"]
        if item["es_nombre_corto"] and item["que_es"] and not _es_texto_generico_o_con_respuesta(item["que_es"])
    ]
    por_unidad = {}
    for item in candidatos:
        por_unidad.setdefault(item["unidad_norm"], []).append(item)

    unidades_validas = [u for u, lista in por_unidad.items() if len(lista) >= 4]
    if unidades_validas:
        unidad_elegida = random.choice(unidades_validas)
        pool = por_unidad[unidad_elegida][:]
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
    cuestionario = Cuestionario.objects.prefetch_related('preguntas__opciones').first()
    if not cuestionario:
        return JsonResponse({"error": "No hay cuestionarios disponibles."})

    indice = _obtener_indice_biblioteca()
    mapa_definiciones = indice["mapa_definiciones"]
    secciones_agrupadas = {}

    for p in cuestionario.preguntas.all():
        if _es_pregunta_clasificacion(p.texto):
            continue

        nombre_seccion = p.seccion if p.seccion else "General"
        unidad_norm = _normalizar_unidad(nombre_seccion)
        es_modulo_sindrome = "sindrome" in unidad_norm
        opciones_db = list(p.opciones.all())
        opcion_correcta = next((op for op in opciones_db if op.es_correcta), None)
        if not opcion_correcta:
            continue

        texto_correcto_limpio = _quitar_prefijo_opcion(opcion_correcta.texto)
        clave_correcta = _normalizar_clave(texto_correcto_limpio)
        definicion_concepto = mapa_definiciones.get(clave_correcta, "")

        # Construir consigna únicamente desde p.texto válido o la definición clínica (NUNCA desde p.explicacion)
        texto_pregunta = (p.texto or "").strip()
        if _es_texto_generico_o_con_respuesta(texto_pregunta):
            if definicion_concepto:
                texto_pregunta = f"¿A qué alteración psicopatológica corresponde la siguiente definición: «{definicion_concepto.rstrip('.')}»?"
            else:
                continue

        # Distractores estrictos de la misma unidad clínica (mínimo 3 opciones en total)
        distractores = _obtener_distractores_misma_unidad(
            nombre_seccion,
            [texto_correcto_limpio],
            cantidad=3,
            permitir_sindromes=es_modulo_sindrome,
            indice=indice,
        )

        if len(distractores) >= 2:
            opciones_limpias = [{"texto": texto_correcto_limpio, "es_correcta": True}] + [
                {"texto": d, "es_correcta": False} for d in distractores
            ]
        else:
            opciones_validas = [
                op for op in opciones_db
                if op.es_correcta
                or (
                    not _es_termino_excluido_en_unidad(unidad_norm, op.texto)
                    and (es_modulo_sindrome or "sindrome" not in _normalizar_clave(op.texto))
                )
            ]
            if len(opciones_validas) < 3:
                opciones_validas = opciones_db
            opciones_limpias = [
                {"texto": _quitar_prefijo_opcion(op.texto), "es_correcta": op.es_correcta}
                for op in opciones_validas
            ]

        random.shuffle(opciones_limpias)

        # Asignar literales A, B, C, D en orden secuencial tras mezclar
        letras = ["A", "B", "C", "D"]
        opciones_data = []
        for idx, op in enumerate(opciones_limpias[:4]):
            opciones_data.append({
                "texto": f"{letras[idx]}) {op['texto']}",
                "es_correcta": op["es_correcta"],
            })

        texto_pregunta = _ocultar_nombre_en_texto(texto_pregunta, texto_correcto_limpio)

        explicacion_limpia = (p.explicacion or "").strip()
        if _es_texto_generico_o_con_respuesta(explicacion_limpia):
            explicacion_limpia = definicion_concepto or f"Corresponde a {texto_correcto_limpio}."

        pregunta_data = {
            "texto": texto_pregunta,
            "explicacion": explicacion_limpia,
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
    indice = _obtener_indice_biblioteca()
    candidatos = [
        item for item in indice["items"]
        if item["es_nombre_corto"] and item["que_es"] and not _es_texto_generico_o_con_respuesta(item["que_es"])
    ]
    por_unidad = {}
    for item in candidatos:
        por_unidad.setdefault(item["unidad_norm"], []).append(item)

    unidades_validas = [u for u, lista in por_unidad.items() if len(lista) >= 3]
    if unidades_validas:
        unidad_elegida = random.choice(unidades_validas)
        pool = por_unidad[unidad_elegida][:]
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