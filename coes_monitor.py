#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 MONITOR DE EVENTOS RELEVANTES COES - FILTRO ORYGEN -> NOTIFICACION WHATSAPP
============================================================================

Que hace:
  1. Abre la pagina de Eventos Relevantes del COES con Playwright.
  2. Extrae la tabla de eventos.
  3. Filtra solo los eventos de ORYGEN.
  4. Compara contra los eventos que ya vio antes (guardados en seen_events.json).
  5. Si hay eventos NUEVOS de ORYGEN, manda un WhatsApp por cada uno via CallMeBot.

Pensado para correr en bucle (cada X minutos) o como tarea programada / GitHub Actions.

Autor: armado para Luis F. Falcon
============================================================================
"""

import json
import time
import re
import hashlib
import sys
import os
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime

from playwright.sync_api import sync_playwright

# ===========================================================================
# CONFIGURACION  -- AJUSTA ESTOS VALORES
# ===========================================================================

# --- COES ---
COES_URL = "https://www.coes.org.pe/Portal/Eventos/Relevantes"

# Texto exacto que aparece en la columna "Empresa" para ORYGEN.
# Segun tu captura es "ORYGEN PERU S.A.A.". Si el COES lo escribe distinto,
# basta con que el nombre contenga "ORYGEN" (la comparacion es por substring).
EMPRESA_FILTRO = "ORYGEN"

# Nombre EXACTO de la empresa en el dropdown del COES (select id="cbEmpresa").
# El script lo selecciona en la pagina y da "Buscar", para ver SOLO los eventos
# de ORYGEN (asi evita el problema de paginacion: la tabla muestra 10 por pagina).
EMPRESA_NOMBRE_EXACTO = "ORYGEN PERU S.A.A."
# Si True, filtra en la pagina por la empresa (recomendado). Si False, lee la
# vista por defecto y filtra en Python (puede perder eventos por paginacion).
FILTRAR_EN_PAGINA = True

# --- WhatsApp (CallMeBot) ---
# Pon aqui tu numero con codigo de pais, sin "+", sin espacios.
# Ejemplo Peru: 51987654321
WHATSAPP_PHONE = "51XXXXXXXXX"
# Tu APIKEY de CallMeBot (te la da el bot por WhatsApp, ver README).
WHATSAPP_APIKEY = "TU_APIKEY_AQUI"

# Si quieres avisar a varios numeros, agrega aqui mas pares (phone, apikey).
# Cada destinatario debe haber activado CallMeBot por su cuenta.
WHATSAPP_EXTRA_RECIPIENTS = [
    # ("51900000000", "APIKEY_DE_OTRA_PERSONA"),
]

# --- WhatsApp Cloud API (Meta) ---
# Canal rapido (entrega instantanea). Se completa via variables de entorno
# (secrets en GitHub): WHATSAPP_CLOUD_TOKEN y WHATSAPP_CLOUD_PHONE_ID.
WHATSAPP_CLOUD_TOKEN = ""        # token permanente del system user
WHATSAPP_CLOUD_PHONE_ID = ""     # Phone Number ID del numero de prueba/produccion
# Numero(s) destino para Cloud API, con codigo de pais, sin "+".
WHATSAPP_CLOUD_RECIPIENTS = ["51997904671"]
# Version de la API de Meta.
WHATSAPP_CLOUD_API_VERSION = "v21.0"
# Plantilla aprobada para enviar fuera de la ventana de 24h.
# Nombre e idioma EXACTOS como los registraste en Meta.
WHATSAPP_CLOUD_TEMPLATE = "alerta_coes_orygen"
WHATSAPP_CLOUD_TEMPLATE_LANG = "es"
# Si True, usa la plantilla (funciona siempre). Si False, intenta texto libre
# (solo funciona dentro de la ventana de 24h). Activar cuando Meta apruebe.
WHATSAPP_CLOUD_USAR_PLANTILLA = True

# --- Comportamiento ---
# Cada cuanto consultar, en MINUTOS. Cambia esto a gusto (30 = cada media hora).
INTERVALO_MINUTOS = 30

# Si True corre en bucle infinito. Si False corre UNA vez y termina
# (usa False para GitHub Actions / tarea programada de Windows).
MODO_BUCLE = True

# Archivo donde se guarda el historial de eventos ya notificados.
SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_events.json")

# Mostrar el navegador (True) o correr oculto/headless (False).
# En servidor/GitHub Actions DEBE ser False.
MOSTRAR_NAVEGADOR = False

# Cuantos eventos guardar como maximo en el historial (para que no crezca infinito).
MAX_HISTORIAL = 500

# ===========================================================================
# UTILIDADES
# ===========================================================================

def log(msg):
    """Imprime con timestamp."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def cargar_vistos():
    """Carga el set de IDs de eventos ya notificados."""
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("ids", []))
    except Exception as e:
        log(f"AVISO: no se pudo leer {SEEN_FILE} ({e}). Empiezo de cero.")
        return set()


def guardar_vistos(ids_set):
    """Guarda el set de IDs (recortando al maximo configurado)."""
    ids_list = list(ids_set)
    if len(ids_list) > MAX_HISTORIAL:
        ids_list = ids_list[-MAX_HISTORIAL:]
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump({"ids": ids_list, "actualizado": datetime.now().isoformat()},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"ERROR guardando historial: {e}")


def hacer_id_evento(evento):
    """
    Crea un identificador unico y estable para un evento, a partir de su
    contenido. Asi, si el mismo evento aparece de nuevo, no se vuelve a notificar.
    """
    base = "|".join([
        evento.get("empresa", ""),
        evento.get("ubicacion", ""),
        evento.get("equipo", ""),
        evento.get("inicio", ""),
        evento.get("descripcion", ""),
    ])
    return hashlib.md5(base.encode("utf-8")).hexdigest()


# ===========================================================================
# SCRAPING
# ===========================================================================

def extraer_eventos(page):
    """
    Lee la tabla de Eventos Relevantes y devuelve una lista de dicts.

    IMPORTANTE: el COES usa una tabla. Esta funcion asume el orden de columnas
    que se ve en la pagina:
        [Ver detalle (+)] | Empresa | Ubicacion | Equipo | Inicio | Final | Descripcion

    Si el COES cambia el orden, ajusta los indices abajo (celdas[1], celdas[2]...).

    Devuelve una lista de dicts. Cada dict incluye "_indice_fila": la posicion
    de su fila en la tabla, para poder luego abrir su popup por indice (mas
    robusto que guardar referencias, que se invalidan al abrir/cerrar modales).
    """
    eventos = []

    filas = page.query_selector_all("table tbody tr")

    for i, fila in enumerate(filas):
        celdas = fila.query_selector_all("td")
        if len(celdas) < 7:
            # No es una fila de datos valida (puede ser cabecera o vacia).
            continue

        textos = [c.inner_text().strip() for c in celdas]

        evento = {
            "empresa":     textos[1],
            "ubicacion":   textos[2],
            "equipo":      textos[3],
            "inicio":      textos[4],
            "final":       textos[5],
            "descripcion": textos[6],
            "detalle":     "",      # se llena despues, al abrir el popup
            "_indice_fila": i,      # posicion de la fila en la tabla
        }

        if not evento["empresa"] and not evento["descripcion"]:
            continue

        eventos.append(evento)

    return eventos


def extraer_detalle_popup(page, indice_fila):
    """
    Abre el popup "Detalle del Evento" de la fila en la posicion 'indice_fila',
    lee el campo "Detalle" y cierra el popup.

    Estructura del popup (segun el HTML del COES):
      - Modal:  div#popupEdicion
      - Contenido:  div.modal-body > div#contenidoEdicion
      - Tabla con filas <tr> donde:
          <td class="registro-label">Detalle</td>
          <td class="registro-control"> ...texto... </td>
      - Cierre:  boton id="btnCancelar"

    Devuelve el texto del detalle, o "" si no se pudo obtener.
    """
    detalle = ""
    try:
        # Reconsultar las filas (el DOM pudo cambiar) y tomar la del indice.
        filas = page.query_selector_all("table tbody tr")
        if indice_fila >= len(filas):
            return ""
        fila = filas[indice_fila]

        # El boton "+" esta en la primera celda de la fila.
        boton = fila.query_selector("td button, td a, td input[type='button']")
        if boton is None:
            boton = fila.query_selector("td")
        boton.click()

        # Esperar a que el popup este visible con su contenido.
        page.wait_for_selector("#popupEdicion .registro-control", timeout=10000)
        page.wait_for_timeout(500)

        # Buscar la fila "Detalle" dentro del popup.
        filas_popup = page.query_selector_all("#popupEdicion table tr")
        for fp in filas_popup:
            label_el = fp.query_selector("td.registro-label")
            control_el = fp.query_selector("td.registro-control")
            if label_el and control_el:
                label = label_el.inner_text().strip().lower()
                if "detalle" in label:
                    detalle = control_el.inner_text().strip()
                    break

    except Exception as e:
        log(f"AVISO: no se pudo leer el detalle de un evento ({e}).")
    finally:
        # Cerrar el popup para continuar con el siguiente.
        try:
            cerrar = page.query_selector("#btnCancelar")
            if cerrar:
                cerrar.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(700)
        except Exception:
            pass

    return detalle


def consultar_coes():
    """
    Abre el navegador, carga la pagina y devuelve la lista de eventos ORYGEN.
    """
    eventos_orygen = []

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=not MOSTRAR_NAVEGADOR)
        contexto = navegador.new_context(
            locale="es-PE",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"),
        )
        page = contexto.new_page()

        try:
            log("Cargando pagina del COES...")
            page.goto(COES_URL, timeout=60000, wait_until="domcontentloaded")

            # Esperar a que aparezca la tabla. Le damos margen porque a veces
            # la tabla se llena via JavaScript despues de cargar.
            try:
                page.wait_for_selector("table tbody tr", timeout=30000)
            except Exception:
                log("AVISO: la tabla tardo o no aparecio. Intento extraer igual.")

            # Filtrar en la pagina por la empresa (selecciona ORYGEN + Buscar).
            # Esto evita el problema de paginacion: al filtrar, la tabla muestra
            # SOLO los eventos de ORYGEN, que caben todos en la primera pagina.
            if FILTRAR_EN_PAGINA:
                try:
                    log(f"Seleccionando empresa '{EMPRESA_NOMBRE_EXACTO}' en el filtro...")
                    page.select_option("#cbEmpresa", label=EMPRESA_NOMBRE_EXACTO)
                    page.wait_for_timeout(500)
                    page.click("#btnBuscar")
                    # Esperar a que la tabla se recargue con el filtro aplicado.
                    page.wait_for_timeout(3000)
                    log("Filtro aplicado.")
                except Exception as e:
                    log(f"AVISO: no se pudo aplicar el filtro de empresa ({e}). "
                        f"Sigo con la vista por defecto.")

            # Pequena espera extra por si la carga es dinamica.
            page.wait_for_timeout(2000)

            # Leer tabla.
            todos = extraer_eventos(page)
            log(f"Eventos totales leidos en la pagina: {len(todos)}")

            # DIAGNOSTICO: listar que esta leyendo el script (empresa + inicio).
            # Util para detectar si un evento esperado no aparece en la carga.
            for idx, ev in enumerate(todos):
                log(f"  [{idx}] {ev['empresa'][:25]:25} | {ev['inicio']} | "
                    f"{ev['equipo']} | {ev['descripcion'][:40]}")

            # Quedarnos solo con los de ORYGEN.
            eventos_filtrados = [
                ev for ev in todos
                if EMPRESA_FILTRO.upper() in ev["empresa"].upper()
            ]
            log(f"Eventos de {EMPRESA_FILTRO}: {len(eventos_filtrados)}")

            # Para cada evento de ORYGEN, abrir su popup y sacar el detalle.
            for ev in eventos_filtrados:
                ev["detalle"] = extraer_detalle_popup(page, ev["_indice_fila"])
                if ev["detalle"]:
                    log("  Detalle capturado para un evento de ORYGEN.")
                else:
                    log("  (Sin detalle disponible para un evento.)")
                eventos_orygen.append(ev)

        except Exception as e:
            log(f"ERROR durante el scraping: {e}")
        finally:
            contexto.close()
            navegador.close()

    return eventos_orygen


# ===========================================================================
# WHATSAPP
# ===========================================================================

# Cuantos segundos esperar a CallMeBot antes de rendirse en cada intento.
WHATSAPP_TIMEOUT = 90
# Cuantas veces reintentar si falla (CallMeBot a veces tarda o esta saturado).
WHATSAPP_REINTENTOS = 3
# Cuantos segundos esperar entre reintentos.
WHATSAPP_ESPERA_REINTENTO = 20


def enviar_whatsapp(texto, phone, apikey):
    """
    Manda un mensaje de WhatsApp via CallMeBot.
    Reintenta varias veces porque el servicio a veces tarda o esta saturado.
    """
    # CallMeBot espera la URL con el texto codificado por separado (quote),
    # NO con urlencode de todo el diccionario (eso rompe los saltos de linea
    # y los emojis, y el mensaje no se entrega).
    texto_codificado = urllib.parse.quote(texto)
    phone_codificado = urllib.parse.quote(str(phone))
    apikey_codificada = urllib.parse.quote(str(apikey))
    url = (
        f"https://api.callmebot.com/whatsapp.php?"
        f"phone={phone_codificado}&text={texto_codificado}&apikey={apikey_codificada}"
    )

    for intento in range(1, WHATSAPP_REINTENTOS + 1):
        try:
            with urllib.request.urlopen(url, timeout=WHATSAPP_TIMEOUT) as resp:
                cuerpo = resp.read().decode("utf-8", errors="ignore")
            log(f"WhatsApp enviado a {phone} (intento {intento}). "
                f"Respuesta servidor: {cuerpo[:150]}")
            return True
        except Exception as e:
            log(f"Intento {intento}/{WHATSAPP_REINTENTOS} fallo "
                f"enviando WhatsApp a {phone}: {e}")
            if intento < WHATSAPP_REINTENTOS:
                log(f"Reintentando en {WHATSAPP_ESPERA_REINTENTO} segundos...")
                time.sleep(WHATSAPP_ESPERA_REINTENTO)

    log(f"ERROR: no se pudo enviar WhatsApp a {phone} tras "
        f"{WHATSAPP_REINTENTOS} intentos.")
    return False


def enviar_whatsapp_cloud(texto, phone_destino):
    """
    Manda un mensaje por WhatsApp Cloud API (Meta). Entrega instantanea.

    Dos modos segun WHATSAPP_CLOUD_USAR_PLANTILLA:
      - True  -> usa la plantilla aprobada (funciona SIEMPRE, sin ventana 24h).
                 El contenido de la alerta va en la variable {{1}}.
      - False -> intenta texto libre (solo funciona dentro de la ventana de 24h).
    """
    if not WHATSAPP_CLOUD_TOKEN or not WHATSAPP_CLOUD_PHONE_ID:
        # Cloud API no configurado; se omite silenciosamente.
        return False

    url = (f"https://graph.facebook.com/{WHATSAPP_CLOUD_API_VERSION}/"
           f"{WHATSAPP_CLOUD_PHONE_ID}/messages")

    if WHATSAPP_CLOUD_USAR_PLANTILLA:
        # La variable de plantilla no admite saltos de linea ni tabs ni mas de
        # 4 espacios seguidos (Meta lo rechaza). Limpiamos el texto a una linea.
        texto_plano = texto.replace("\n", " - ").replace("\t", " ")
        texto_plano = re.sub(r"\s{2,}", " ", texto_plano).strip()
        cuerpo = {
            "messaging_product": "whatsapp",
            "to": str(phone_destino),
            "type": "template",
            "template": {
                "name": WHATSAPP_CLOUD_TEMPLATE,
                "language": {"code": WHATSAPP_CLOUD_TEMPLATE_LANG},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": texto_plano}],
                }],
            },
        }
    else:
        cuerpo = {
            "messaging_product": "whatsapp",
            "to": str(phone_destino),
            "type": "text",
            "text": {"body": texto},
        }

    payload = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {WHATSAPP_CLOUD_TOKEN}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8", errors="ignore")
        log(f"Cloud API: mensaje enviado a {phone_destino}. "
            f"Respuesta: {resp_body[:150]}")
        return True
    except urllib.error.HTTPError as e:
        detalle_err = e.read().decode("utf-8", errors="ignore")
        log(f"Cloud API: fallo enviando a {phone_destino} (HTTP {e.code}). "
            f"Detalle: {detalle_err[:250]}")
        return False
    except Exception as e:
        log(f"Cloud API: error enviando a {phone_destino}: {e}")
        return False


def notificar_evento(ev):
    """
    Arma el texto de la alerta y la manda a todos los destinatarios.
    Devuelve True si al menos un envio fue exitoso, False si todos fallaron.
    """
    texto = (
        "🔔 *ALERTA COES - ORYGEN*\n"
        f"🏭 Empresa: {ev['empresa']}\n"
        f"📍 Ubicacion: {ev['ubicacion']}\n"
        f"⚙️ Equipo: {ev['equipo']}\n"
        f"🕐 Inicio: {ev['inicio']}\n"
        f"🕐 Final: {ev['final']}\n"
        f"📝 {ev['descripcion']}"
    )

    # Agregar el detalle del popup si se pudo capturar.
    if ev.get("detalle"):
        texto += f"\n\nℹ️ *Detalle:* {ev['detalle']}"

    algun_exito = False

    # --- Canal 1: Cloud API (rapido) ---
    for destino in WHATSAPP_CLOUD_RECIPIENTS:
        if enviar_whatsapp_cloud(texto, destino):
            algun_exito = True

    # --- Canal 2: CallMeBot (respaldo) ---
    destinatarios = [(WHATSAPP_PHONE, WHATSAPP_APIKEY)] + WHATSAPP_EXTRA_RECIPIENTS
    for phone, apikey in destinatarios:
        if enviar_whatsapp(texto, phone, apikey):
            algun_exito = True
        time.sleep(2)  # CallMeBot pide un pequeno espacio entre mensajes.

    return algun_exito


# ===========================================================================
# CICLO PRINCIPAL
# ===========================================================================

def ejecutar_una_vez():
    """Una pasada completa: consulta, detecta nuevos, notifica."""
    vistos = cargar_vistos()
    eventos = consultar_coes()

    nuevos = []
    for ev in eventos:
        ev_id = hacer_id_evento(ev)
        if ev_id not in vistos:
            nuevos.append((ev_id, ev))

    if not nuevos:
        log("Sin eventos nuevos de ORYGEN.")
        return

    log(f"¡{len(nuevos)} evento(s) NUEVO(S) de ORYGEN! Notificando...")
    hubo_cambios = False
    for ev_id, ev in nuevos:
        # Solo lo marcamos como "visto" si el WhatsApp se envio de verdad.
        # Asi, si el envio falla, en la proxima corrida se vuelve a intentar.
        if notificar_evento(ev):
            vistos.add(ev_id)
            hubo_cambios = True
        else:
            log(f"Aviso no enviado; el evento se reintentara en la proxima corrida.")

    if hubo_cambios:
        guardar_vistos(vistos)


def main():
    log("=== Monitor COES-ORYGEN iniciado ===")
    log(f"Filtro empresa: {EMPRESA_FILTRO} | Intervalo: {INTERVALO_MINUTOS} min | "
        f"Bucle: {MODO_BUCLE}")

    # Validacion basica de configuracion de WhatsApp.
    if "XXXX" in WHATSAPP_PHONE or "TU_APIKEY" in WHATSAPP_APIKEY:
        log("AVISO: configura WHATSAPP_PHONE y WHATSAPP_APIKEY antes de usar en serio.")

    if MODO_BUCLE:
        while True:
            try:
                ejecutar_una_vez()
            except Exception as e:
                log(f"ERROR en el ciclo: {e}")
            log(f"Durmiendo {INTERVALO_MINUTOS} minutos...")
            time.sleep(INTERVALO_MINUTOS * 60)
    else:
        ejecutar_una_vez()
        log("Ejecucion unica terminada.")


if __name__ == "__main__":
    main()
