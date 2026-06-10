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

base.MOSTRAR_NAVEGADOR = False
base.MODO_BUCLE = False

if __name__ == "__main__":
    base.log("=== Monitor COES-ORYGEN (modo CI / una vez) ===")
    base.ejecutar_una_vez()
    base.log("Listo.")
