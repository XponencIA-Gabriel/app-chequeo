# Servicios de resolución de CAPTCHA

La app resuelve el CAPTCHA de SSS (la imagen `#siimage`) con varios servicios.
Si uno falla, prueba el siguiente con la **misma imagen**, sin recargar la página.

## Configuración (`.env`)

Para activar un servicio, cargá su key. Los que quedan vacíos no se usan.

| Servicio      | Variable                              | Tipo                     | Dónde sacar la key        |
|---------------|---------------------------------------|--------------------------|---------------------------|
| NopeCHA       | `NOPECHA_API_KEY`                     | OCR automático           | https://nopecha.com       |
| CapSolver     | `CAPSOLVER_API_KEY`                   | OCR automático, rápido   | https://capsolver.com     |
| CapMonster    | `CAPMONSTER_API_KEY`                  | OCR automático, rápido   | https://capmonster.cloud  |
| Anti-Captcha  | `ANTICAPTCHA_API_KEY`                 | Personas, lento y preciso | https://anti-captcha.com |
| 2Captcha      | `TWOCAPTCHA_API_KEY`                  | Personas, lento y preciso | https://2captcha.com     |
| Gemini        | `GEMINI_API_KEY0` … `GEMINI_API_KEY19` | IA, gratis con límite   | https://aistudio.google.com |

Variables opcionales:

- `CAPTCHA_PROVIDERS`: orden en que se prueban, separado por comas. Por defecto:
  `nopecha,capsolver,capmonster,anticaptcha,2captcha,gemini`.
  Ejemplo para usar CapSolver primero: `CAPTCHA_PROVIDERS=capsolver,nopecha,gemini`.
  Un servicio que no aparece en la lista no se usa, aunque tenga key.
- `CAPTCHA_TIMEOUT`: segundos máximos de espera por servicio antes de pasar al
  siguiente. Por defecto `60`. Los servicios con personas (Anti-Captcha, 2Captcha)
  suelen tardar entre 5 y 15 s.

Hay que reiniciar la app para que tome los cambios del `.env`.

## Cómo funciona

En cada intento, `CaptchaSolver.resolver_captcha(driver)` en [captcha_solver.py](captcha_solver.py):

1. Captura la imagen del CAPTCHA **en memoria** (sin guardar archivos).
2. La manda al primer servicio disponible.
3. Según el resultado:
   - **Texto recibido**: lo devuelve.
   - **Error temporal** (timeout, caída del servidor, rate limit, "no se pudo leer"):
     prueba el siguiente servicio. El que falló sigue activo para el próximo captcha.
   - **Sin crédito o key inválida**: lo marca como no disponible y no lo vuelve a
     usar hasta reiniciar la app. Prueba el siguiente.
4. Si no queda ningún servicio disponible, devuelve `"CUOTA_AGOTADA"` y el
   procesamiento se detiene (igual que antes).

Para Gemini, cuando una key se queda sin cuota se pasa a la siguiente. Gemini
queda como no disponible recién cuando se agotan todas.

Si el sitio después rechaza el código ("CAPTCHA incorrecto"), `business_engine.py`
reintenta el CUIL completo como antes. El servicio no se entera del error, porque
no se reporta.

### En la interfaz

- El panel **"🤖 Servicios de captcha"** (antes "Nopecha") lista cada servicio
  pago configurado con 🟢 (disponible) o 🔴 (sin crédito). Su cantidad de
  procesos se usa mientras haya **algún** servicio pago disponible.
- El panel **"🧠 Gemini"** no cambió. Su cantidad de procesos se usa solo cuando
  no queda ningún servicio pago.

## Detalle técnico por servicio

- **NopeCHA**: API HTTP directa (`POST`/`GET https://api.nopecha.com/v1/recognition/textcaptcha`).
  Ya no se usa la librería `nopecha` de Python. Se quitó de `requirements.txt`.
  Errores 15 (key inválida) y 16 (sin crédito) deshabilitan el servicio.
- **CapSolver, CapMonster, Anti-Captcha, 2Captcha**: comparten el mismo formato
  (`createTask` con `ImageToTextTask` y luego `getTaskResult`), así que usan una
  sola función: `resolver_con_createtask`. CapSolver devuelve el resultado en la
  primera respuesta. Los demás se consultan cada 1 s. Códigos que deshabilitan el
  servicio: `ERROR_ZERO_BALANCE`, `ERROR_KEY_DOES_NOT_EXIST`, `ERROR_WRONG_USER_KEY`,
  `ERROR_KEY_DENIED_ACCESS`, `ERROR_ACCOUNT_SUSPENDED`, `ERROR_IP_NOT_ALLOWED`,
  `ERROR_IP_BANNED`, y la respuesta "clientKey is invalid" de CapSolver.
- **Gemini**: igual que antes (modelo `gemini-2.5-flash`, preprocesado de la
  imagen con `preprocess.limpiar_imagen`), ahora en memoria.

### Agregar otro servicio

1. Si usa el formato `createTask`/`getTaskResult`, alcanza con sumar una entrada
   a `PROVIDERS_CREATETASK` y su nombre a `ORDEN_PROVIDERS_DEFAULT`.
2. Si no, escribir un método `resolver_con_X(self, imagen_b64)` que devuelva el
   texto, `None` si no pudo o lance `ProveedorNoDisponible` si no tiene crédito, y
   agregarlo en `_resolver_con`.

## Cambios realizados (octubre 2026)

### Bugs corregidos

1. **Los workers se pisaban la imagen del CAPTCHA.** Todos los workers
   guardaban la captura en el mismo archivo (`captcha_nopecha.png`). Con varios
   en paralelo, un worker podía mandar al servicio el captcha de **otro** worker y
   recibir un código que no correspondía a su página. Esto causaba muchos "CAPTCHA
   incorrecto" que parecían culpa de NopeCHA. Ahora la imagen se toma en memoria
   (`screenshot_as_base64`) y cada worker usa la suya.
2. **Gemini nunca devolvía resultado.** Usaba `global consultas_gemini`, una
   variable que no existía. Después de recibir la respuesta, el `+= 1` lanzaba un
   error y el código lo trataba como fallo. El respaldo con Gemini no funcionaba
   nunca. Ahora el contador es por instancia.
3. **Gemini procesaba de a un worker por vez.** Toda la llamada a la API estaba
   dentro de un lock. Ahora el lock solo cubre la elección de la key.
4. **Rotación de keys de Gemini salteaba keys.** Si varios workers recibían
   "sin cuota" a la vez, cada uno avanzaba el índice y se salteaban keys que
   todavía servían. Ahora solo avanza si nadie lo avanzó antes.
5. **Sin respaldo ante fallos comunes.** Antes, si NopeCHA fallaba por algo que
   no era la cuota (timeout, servidor caído), el intento se perdía sin probar con
   otro servicio. Ahora se prueba el siguiente con la misma imagen.
6. **Detección de "sin crédito" por palabras sueltas.** Antes se buscaban palabras
   como `limit` o `expired` en el texto del error, lo que podía apagar NopeCHA por
   un simple rate limit. Ahora se usan los códigos de error oficiales de cada API.
7. Detalles menores: `print(..., "red")` imprimía la palabra "red"; en
   `validar_configuracion` había código inalcanzable después de un `raise` (la app
   no arrancaba sin key de NopeCHA aunque hubiera Gemini); el mensaje de
   `preprocess.py` no era f-string.

### Archivos modificados

- `captcha_solver.py`: reescrito con varios servicios y respaldo automático.
  Mantiene la misma interfaz (`resolver_captcha`, `obtener_estadisticas`) y las
  claves de estadísticas que ya usaba la GUI. Se eliminó
  `resolver_captcha_nopecha_only`, que no se usaba en ningún lado.
- `preprocess.py`: nueva función `limpiar_imagen` (en memoria). `edit_image` sigue
  existiendo y la usa por dentro.
- `gui.py`: el panel "Nopecha" pasó a ser "Servicios de captcha" y la elección de
  la cantidad de procesos considera todos los servicios pagos.
- `requirements.txt`: se quitó `nopecha`.
- `.env`: se agregaron las variables nuevas, vacías.

Los archivos `captcha_nopecha.png`, `captcha_gemini.png` y `captcha_clean.png`
de la carpeta ya no se generan. Se pueden borrar.
