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
import hashlib
import sys
import os
import urllib.parse
import urllib.request
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
    que se ve en tu captura:
        [Ver detalle] | Empresa | Ubicacion | Equipo | Inicio | Final | Descripcion

    Si el COES cambia el orden, ajusta los indices abajo (cells[1], cells[2]...).
    """
    eventos = []

    # Buscamos todas las filas de la tabla. Se prueban varios selectores
    # por robustez (la pagina puede tener una sola tabla principal).
    filas = page.query_selector_all("table tbody tr")

    for fila in filas:
        celdas = fila.query_selector_all("td")
        if len(celdas) < 7:
            # No es una fila de datos valida (puede ser cabecera o vacia).
            continue

        textos = [c.inner_text().strip() for c in celdas]

        # Mapeo segun el orden visto en la captura.
        evento = {
            "empresa":     textos[1],
            "ubicacion":   textos[2],
            "equipo":      textos[3],
            "inicio":      textos[4],
            "final":       textos[5],
            "descripcion": textos[6],
        }

        # Ignorar filas claramente vacias.
        if not evento["empresa"] and not evento["descripcion"]:
            continue

        eventos.append(evento)

    return eventos


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

            # Pequena espera extra por si la carga es dinamica.
            page.wait_for_timeout(2000)

            todos = extraer_eventos(page)
            log(f"Eventos totales leidos en la pagina: {len(todos)}")

            # Filtrar ORYGEN (por substring, sin importar mayus/minus).
            for ev in todos:
                if EMPRESA_FILTRO.upper() in ev["empresa"].upper():
                    eventos_orygen.append(ev)

            log(f"Eventos de {EMPRESA_FILTRO}: {len(eventos_orygen)}")

        except Exception as e:
            log(f"ERROR durante el scraping: {e}")
        finally:
            contexto.close()
            navegador.close()

    return eventos_orygen


# ===========================================================================
# WHATSAPP
# ===========================================================================

def enviar_whatsapp(texto, phone, apikey):
    """Manda un mensaje de WhatsApp via CallMeBot (una sola llamada GET)."""
    try:
        url = (
            "https://api.callmebot.com/whatsapp.php?"
            + urllib.parse.urlencode({
                "phone": phone,
                "text": texto,
                "apikey": apikey,
            })
        )
        with urllib.request.urlopen(url, timeout=30) as resp:
            cuerpo = resp.read().decode("utf-8", errors="ignore")
        log(f"WhatsApp enviado a {phone}. Respuesta servidor: {cuerpo[:120]}")
        return True
    except Exception as e:
        log(f"ERROR enviando WhatsApp a {phone}: {e}")
        return False


def notificar_evento(ev):
    """Arma el texto de la alerta y la manda a todos los destinatarios."""
    texto = (
        "🔔 *ALERTA COES - ORYGEN*\n"
        f"🏭 Empresa: {ev['empresa']}\n"
        f"📍 Ubicacion: {ev['ubicacion']}\n"
        f"⚙️ Equipo: {ev['equipo']}\n"
        f"🕐 Inicio: {ev['inicio']}\n"
        f"🕐 Final: {ev['final']}\n"
        f"📝 {ev['descripcion']}"
    )

    destinatarios = [(WHATSAPP_PHONE, WHATSAPP_APIKEY)] + WHATSAPP_EXTRA_RECIPIENTS
    for phone, apikey in destinatarios:
        enviar_whatsapp(texto, phone, apikey)
        time.sleep(2)  # CallMeBot pide un pequeno espacio entre mensajes.


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
    for ev_id, ev in nuevos:
        notificar_evento(ev)
        vistos.add(ev_id)

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
