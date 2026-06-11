#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Variante de coes_monitor.py pensada para GitHub Actions / tareas programadas.
Diferencias con el original:
  - Lee WHATSAPP_PHONE y WHATSAPP_APIKEY de variables de entorno (secrets).
  - Corre UNA sola vez (no bucle); el cron de GitHub se encarga de repetir.
  - headless siempre True.

Reutiliza toda la logica de coes_monitor.py.
"""

import os
import coes_monitor as base

# Sobrescribir config con variables de entorno (si existen).
base.WHATSAPP_PHONE = os.environ.get("WHATSAPP_PHONE", base.WHATSAPP_PHONE)
base.WHATSAPP_APIKEY = os.environ.get("WHATSAPP_APIKEY", base.WHATSAPP_APIKEY)

# Cloud API (Meta).
base.WHATSAPP_CLOUD_TOKEN = os.environ.get("WHATSAPP_CLOUD_TOKEN", base.WHATSAPP_CLOUD_TOKEN)
base.WHATSAPP_CLOUD_PHONE_ID = os.environ.get("WHATSAPP_CLOUD_PHONE_ID", base.WHATSAPP_CLOUD_PHONE_ID)

# Destinatarios de Cloud API: se leen de un secret con numeros separados por
# coma (ej. "51997904671,51959472759,51920442556"). Si el secret no existe,
# se mantiene la lista que ya tenga el codigo.
_cloud_dest = os.environ.get("WHATSAPP_CLOUD_RECIPIENTS", "").strip()
if _cloud_dest:
    base.WHATSAPP_CLOUD_RECIPIENTS = [
        n.strip() for n in _cloud_dest.split(",") if n.strip()
    ]

# Destinatarios extra de CallMeBot: se leen de un secret con pares
# "numero:apikey" separados por coma (ej. "519xxxx:apikeyA,519yyyy:apikeyB").
# Opcional; si no existe, se mantiene la lista del codigo.
_cmb_extra = os.environ.get("CALLMEBOT_EXTRA", "").strip()
if _cmb_extra:
    pares = []
    for item in _cmb_extra.split(","):
        item = item.strip()
        if ":" in item:
            num, key = item.split(":", 1)
            pares.append((num.strip(), key.strip()))
    if pares:
        base.WHATSAPP_EXTRA_RECIPIENTS = pares

base.MOSTRAR_NAVEGADOR = False
base.MODO_BUCLE = False

if __name__ == "__main__":
    base.log("=== Monitor COES-ORYGEN (modo CI / una vez) ===")
    base.ejecutar_una_vez()
    base.log("Listo.")
