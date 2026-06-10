# Monitor COES → ORYGEN → WhatsApp

Te avisa por WhatsApp apenas aparece un **evento relevante de ORYGEN** en la
página de Eventos Relevantes del COES, sin que tengas que estar revisando.

---

## Cómo funciona (en simple)

1. Un script abre la página del COES con un navegador automático (Playwright).
2. Lee la tabla de eventos y se queda solo con los de **ORYGEN**.
3. Compara contra lo que ya vio antes (guardado en `seen_events.json`).
4. Si hay algo **nuevo**, te manda un WhatsApp por cada evento.

No hay "tiempo real" puro porque el COES no avisa a nadie: es una página de
consulta. Lo que hacemos es **revisar cada X minutos**. Como tú mismo dijiste
que los eventos no son a cada minuto, revisar cada 30 min está bien y aun así
le ganas al comunicado oficial, que suele salir después de que el evento ya
aparece en esta tabla.

---

## PASO 1 — Activar tu WhatsApp en CallMeBot (5 minutos, gratis)

CallMeBot es un servicio gratuito para mandar WhatsApp desde un programa.

1. Agrega este número a tus contactos del celular: **+34 644 51 95 23**
   (CallMeBot rota el número cada cierto tiempo; si no responde, busca el número
   actualizado en https://www.callmebot.com/blog/free-api-whatsapp-messages/ ).
   Ponle el nombre que quieras, por ejemplo "CallMeBot".
2. Desde TU WhatsApp, mándale este mensaje exacto a ese contacto:
   ```
   I allow callmebot to send me messages
   ```
3. En menos de 2 minutos te responde con tu **APIKEY** (algo como `123456`).
   Guárdala.

> Si no llega en 2 minutos, espera 24 h y reintenta. Si pierdes la apikey,
> mándale al bot el mensaje `Recover APIKey`.

> Nota: CallMeBot es gratis y para uso personal / volumen bajo, perfecto para
> tu caso. Si algún día necesitas algo de "producción" empresarial formal, el
> camino oficial sería WhatsApp Cloud API de Meta (más burocrático pero
> respaldado por Meta). Para empezar, CallMeBot está bien.

---

## PASO 2 — Elegir DÓNDE corre

### Opción A (RECOMENDADA): GitHub Actions — gratis, en la nube, 24/7

Ventaja: no depende de tu laptop encendida. Corre solo en los servidores de
GitHub. Ideal porque tu intervalo es de 30 min.

1. Crea una cuenta en https://github.com (gratis) si no tienes.
2. Crea un repositorio **privado** nuevo (ej: `coes-orygen-alert`).
3. Sube todos estos archivos al repo (puedes arrastrarlos en la web de GitHub:
   botón "Add file" → "Upload files").
4. En el repo, ve a **Settings → Secrets and variables → Actions → New repository secret**
   y crea dos secrets:
   - `WHATSAPP_PHONE` = tu número con código de país, sin "+". Ej: `51987654321`
   - `WHATSAPP_APIKEY` = la apikey que te dio CallMeBot.
5. Ve a la pestaña **Actions**, acepta activar los workflows.
6. Listo. El workflow `monitor.yml` correrá cada 30 min automáticamente.
   Para probarlo ya mismo: Actions → "Monitor COES ORYGEN" → "Run workflow".

> El historial (`seen_events.json`) se guarda solo, con un commit automático
> cada vez que corre. Así no te repite eventos viejos.

> Para cambiar el intervalo: edita la línea `cron:` en
> `.github/workflows/monitor.yml`. Ejemplos:
> - cada 15 min: `*/15 * * * *`
> - cada hora: `0 * * * *`
> (GitHub usa hora UTC; Lima es UTC-5. Para un intervalo fijo no importa.)

### Opción B: tu PC / laptop (corre mientras esté prendida)

Útil para probar o si tienes una PC siempre encendida. Si tu laptop es
corporativa y se apaga, las alertas se cortan cuando está apagada.

```bash
# 1. Instalar Python 3.10+ (si no lo tienes)
# 2. En la carpeta del proyecto:
pip install -r requirements.txt
python -m playwright install chromium

# 3. Abre coes_monitor.py y edita arriba:
#    WHATSAPP_PHONE, WHATSAPP_APIKEY, INTERVALO_MINUTOS
# 4. Corre:
python coes_monitor.py
```

Déjalo abierto y revisará cada 30 min. Para que sobreviva reinicios podrías
usar el Programador de Tareas de Windows (pero ojo con permisos en equipo
corporativo).

---

## PASO 3 — Verificar que captura bien la tabla (importante)

El script asume que la tabla del COES tiene las columnas en este orden:

```
[Ver detalle] | Empresa | Ubicación | Equipo | Inicio | Final | Descripción
```

que es lo que se ve hoy en la página. **La primera vez, corre el script en tu
PC con `MOSTRAR_NAVEGADOR = True`** para ver que efectivamente lee los eventos
de ORYGEN. En la consola debe decir algo como:
`Eventos de ORYGEN: 2`.

Si el COES cambia el diseño y deja de capturar, hay que ajustar los índices de
columna dentro de la función `extraer_eventos` (está comentado dónde).

---

## Archivos del proyecto

| Archivo | Para qué |
|---|---|
| `coes_monitor.py` | El monitor principal (config arriba del archivo). |
| `coes_monitor_ci.py` | Variante para GitHub Actions (lee secrets, corre 1 vez). |
| `.github/workflows/monitor.yml` | Programa la corrida cada 30 min en GitHub. |
| `requirements.txt` | Dependencias (Playwright). |
| `seen_events.json` | Se crea solo: historial de lo ya notificado. |

---

## Preguntas que probablemente tengas

**¿Y si quiero avisar a varios del equipo?**
Cada persona activa CallMeBot con su propio WhatsApp (Paso 1) y agregas sus
pares `(phone, apikey)` en `WHATSAPP_EXTRA_RECIPIENTS` dentro de `coes_monitor.py`.

**¿Puedo monitorear otras empresas además de ORYGEN?**
Sí. Cambia `EMPRESA_FILTRO`. Para varias, habría que ajustar un poco el filtro
(te lo armo si lo necesitas).

**¿Me va a repetir el mismo evento?**
No. Cada evento tiene un ID por contenido; una vez notificado no se repite.

**¿Cuánto cuesta?**
GitHub Actions gratis (muy por debajo del límite mensual gratuito) + CallMeBot
gratis. Costo total: 0.
