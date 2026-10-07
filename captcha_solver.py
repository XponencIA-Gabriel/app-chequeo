"""
Resolución de CAPTCHAs de texto (imagen #siimage de SSS) con varios proveedores.

Proveedores soportados (variable de entorno con la API key):
    nopecha      NOPECHA_API_KEY
    capsolver    CAPSOLVER_API_KEY
    capmonster   CAPMONSTER_API_KEY
    anticaptcha  ANTICAPTCHA_API_KEY
    2captcha     TWOCAPTCHA_API_KEY
    gemini       GEMINI_API_KEY0 ... GEMINI_API_KEY19 (rotación de keys)

Solo se usan los proveedores que tienen key en el .env. El orden de prueba es
ORDEN_PROVIDERS_DEFAULT, o el que se defina en CAPTCHA_PROVIDERS
(ej: CAPTCHA_PROVIDERS=capsolver,nopecha,gemini).

Funcionamiento de resolver_captcha():
    1. Captura la imagen del CAPTCHA UNA sola vez, en memoria (sin archivos en
       disco, para que los workers en paralelo no se pisen la imagen).
    2. Prueba los proveedores en orden. Si uno falla (timeout, error, respuesta
       vacía), pasa al siguiente con la MISMA imagen.
    3. Si un proveedor se queda sin crédito o su key es inválida, se marca como
       no disponible y no se vuelve a usar hasta reiniciar la app.
    4. Devuelve el texto, None si todos fallaron en este intento, o
       "CUOTA_AGOTADA" si no queda ningún proveedor disponible.
"""
import os
import re
import base64
import threading
import time
from io import BytesIO

import cv2
import numpy as np
import requests
from PIL import Image
import google.generativeai as genai
from dotenv import load_dotenv
from preprocess import limpiar_imagen

load_dotenv()

ORDEN_PROVIDERS_DEFAULT = ["nopecha", "capsolver", "capmonster", "anticaptcha", "2captcha", "gemini"]

# Servicios que usan la API estándar createTask / getTaskResult (formato Anti-Captcha)
PROVIDERS_CREATETASK = {
    "capsolver":   {"env": "CAPSOLVER_API_KEY",   "url": "https://api.capsolver.com",      "nombre": "CapSolver"},
    "capmonster":  {"env": "CAPMONSTER_API_KEY",  "url": "https://api.capmonster.cloud",   "nombre": "CapMonster"},
    "anticaptcha": {"env": "ANTICAPTCHA_API_KEY", "url": "https://api.anti-captcha.com",   "nombre": "Anti-Captcha"},
    "2captcha":    {"env": "TWOCAPTCHA_API_KEY",  "url": "https://api.2captcha.com",       "nombre": "2Captcha"},
}

NOMBRES_PROVIDERS = {
    "nopecha": "NopeCHA",
    "gemini": "Gemini",
    **{p: cfg["nombre"] for p, cfg in PROVIDERS_CREATETASK.items()},
}

# errorCode de la API createTask que significan "este proveedor no sirve más" (sin saldo o key mala)
ERRORES_NO_DISPONIBLE = {
    "ERROR_ZERO_BALANCE",
    "ERROR_KEY_DOES_NOT_EXIST",
    "ERROR_WRONG_USER_KEY",
    "ERROR_KEY_DENIED_ACCESS",
    "ERROR_ACCOUNT_SUSPENDED",
    "ERROR_IP_NOT_ALLOWED",
    "ERROR_IP_BANNED",
}

# Tiempo máximo (segundos) que se espera a un proveedor antes de pasar al siguiente
TIMEOUT_PROVIDER = int(os.getenv("CAPTCHA_TIMEOUT", "60"))
TIMEOUT_HTTP = 30


class ProveedorNoDisponible(Exception):
    """El proveedor se quedó sin crédito o la key es inválida: no reintentar con él."""


def _json(resp):
    """Decodifica la respuesta; si no es JSON (ej. página de error 520 de Cloudflare) lanza un error legible"""
    try:
        return resp.json()
    except ValueError:
        raise RuntimeError(f"respuesta inválida del servidor (HTTP {resp.status_code})")


class CaptchaSolver:
    def __init__(self):
        self.keys = {p: os.getenv(cfg["env"], "").strip() for p, cfg in PROVIDERS_CREATETASK.items()}
        self.keys["nopecha"] = os.getenv("NOPECHA_API_KEY", "").strip()
        self.gemini_keys = self.cargar_gemini_keys()

        # Proveedores configurados, en orden de prioridad
        orden = os.getenv("CAPTCHA_PROVIDERS", "")
        orden = [p.strip().lower() for p in orden.split(",") if p.strip()] or ORDEN_PROVIDERS_DEFAULT
        self.providers = [p for p in orden if p in NOMBRES_PROVIDERS and self._tiene_key(p)]

        self.no_disponibles = set()
        self.consultas = {p: 0 for p in NOMBRES_PROVIDERS}  # resueltos con texto
        self.fallos = {p: 0 for p in NOMBRES_PROVIDERS}     # errores / sin respuesta
        self.indice_gemini_actual = 0

        # Thread safety
        self.key_lock = threading.Lock()
        self.quota_lock = threading.Lock()

        print("🔍 CaptchaSolver inicializado:")
        for p in ORDEN_PROVIDERS_DEFAULT:
            extra = f" ({len(self.gemini_keys)} keys)" if p == "gemini" else ""
            print(f"  - {NOMBRES_PROVIDERS[p]}: {'✅' if p in self.providers else '❌'}{extra}")
        print(f"  - Orden: {' → '.join(NOMBRES_PROVIDERS[p] for p in self.providers)}")

        self.validar_configuracion()

    def cargar_gemini_keys(self):
        """Carga las API keys de Gemini dinámicamente (GEMINI_API_KEY0..19), sin duplicados"""
        keys_unicas = []
        for i in range(20):
            key_value = os.getenv(f"GEMINI_API_KEY{i}", "").strip()
            if key_value and key_value not in keys_unicas:
                keys_unicas.append(key_value)
        return keys_unicas

    def _tiene_key(self, provider):
        if provider == "gemini":
            return bool(self.gemini_keys)
        return bool(self.keys.get(provider))

    def validar_configuracion(self):
        """Valida la configuración inicial"""
        if not self.providers:
            raise ValueError("No hay APIs de Captcha configuradas en .env")

    def limpiar_respuesta_captcha(self, texto_sucio):
        """Deja solo letras y números"""
        if not isinstance(texto_sucio, str):
            return ""
        return re.sub(r'[^a-zA-Z0-9]', '', texto_sucio)

    # ------------------------------------------------------------------
    # Captura de imagen
    # ------------------------------------------------------------------
    def capturar_captcha_base64(self, driver):
        """
        Devuelve el PNG del CAPTCHA en base64, tomado directo de memoria.
        Antes se guardaba en un archivo fijo (captcha_nopecha.png) compartido por
        todos los workers, y un worker podía terminar enviando el captcha de otro.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        captcha_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "siimage"))
        )
        return captcha_element.screenshot_as_base64

    # ------------------------------------------------------------------
    # Proveedores. Cada uno recibe la imagen en base64 y devuelve el texto,
    # None si no pudo resolverlo, o lanza ProveedorNoDisponible.
    # ------------------------------------------------------------------
    def resolver_con_nopecha(self, imagen_b64):
        """API HTTP de NopeCHA: POST crea el trabajo, GET consulta hasta que esté listo"""
        url = "https://api.nopecha.com/v1/recognition/textcaptcha"
        headers = {"Authorization": f"Basic {self.keys['nopecha']}"}

        resp = _json(requests.post(url, headers=headers, timeout=TIMEOUT_HTTP,
                                   json={"image_data": [f"data:image/png;base64,{imagen_b64}"]}))
        self._verificar_error_nopecha(resp)
        job_id = resp.get("data")
        if not job_id:
            print(f"⚠️ NopeCHA no devolvió id de trabajo: {resp}")
            return None

        limite = time.time() + TIMEOUT_PROVIDER
        while time.time() < limite:
            time.sleep(0.5)
            resp = _json(requests.get(url, headers=headers, params={"id": job_id}, timeout=TIMEOUT_HTTP))
            if resp.get("error") == 14:  # Incomplete job: todavía procesando
                continue
            self._verificar_error_nopecha(resp)
            data = resp.get("data") or [None]
            return data[0]

        print("⏱️ NopeCHA: timeout esperando resultado")
        return None

    def _verificar_error_nopecha(self, resp):
        """Códigos de error de NopeCHA: 15 = key inválida, 16 = sin crédito"""
        error = resp.get("error")
        if error is None:
            return
        if error in (15, 16):
            raise ProveedorNoDisponible(f"NopeCHA error {error}: {resp.get('message', '')}")
        raise RuntimeError(f"NopeCHA error {error}: {resp.get('message', '')}")

    def resolver_con_createtask(self, provider, imagen_b64):
        """
        CapSolver, CapMonster, Anti-Captcha y 2Captcha usan la misma API:
        POST /createTask con un ImageToTextTask y luego POST /getTaskResult
        hasta que status == "ready". CapSolver responde ya resuelto en createTask.
        """
        cfg = PROVIDERS_CREATETASK[provider]
        key = self.keys[provider]
        task = {"type": "ImageToTextTask", "body": imagen_b64}
        if provider == "capsolver":
            task["module"] = "common"
        else:
            task["case"] = True  # respetar mayúsculas/minúsculas

        resp = _json(requests.post(f"{cfg['url']}/createTask", timeout=TIMEOUT_HTTP,
                                   json={"clientKey": key, "task": task}))

        limite = time.time() + TIMEOUT_PROVIDER
        while True:
            if resp.get("errorId"):
                codigo = resp.get("errorCode", "")
                descripcion = resp.get("errorDescription", "") or ""
                mensaje = f"{cfg['nombre']} {codigo}: {descripcion}"
                # CapSolver informa key inválida como ERROR_INVALID_TASK_DATA + "clientKey is invalid"
                key_invalida = "clientkey is invalid" in descripcion.lower()
                if codigo in ERRORES_NO_DISPONIBLE or key_invalida:
                    raise ProveedorNoDisponible(mensaje)
                raise RuntimeError(mensaje)

            if resp.get("status") == "ready":
                return (resp.get("solution") or {}).get("text")

            task_id = resp.get("taskId")
            if not task_id or time.time() > limite:
                print(f"⏱️ {cfg['nombre']}: sin resultado (timeout o sin taskId)")
                return None

            time.sleep(1)
            resp = _json(requests.post(f"{cfg['url']}/getTaskResult", timeout=TIMEOUT_HTTP,
                                       json={"clientKey": key, "taskId": task_id}))
            resp.setdefault("taskId", task_id)

    def resolver_con_gemini(self, imagen_b64):
        """
        Envía la imagen preprocesada a Gemini. Si una key se queda sin cuota pasa
        a la siguiente; si se terminan todas lanza ProveedorNoDisponible.
        """
        # Preprocesar la imagen en memoria (limpiar ruido)
        gris = cv2.imdecode(np.frombuffer(base64.b64decode(imagen_b64), np.uint8), cv2.IMREAD_GRAYSCALE)
        img = Image.fromarray(limpiar_imagen(gris))

        prompt = [
            "Extrae el texto exacto de esta imagen, respetando mayúsculas, minúsculas y números.",
            "Devuelve única y exclusivamente el texto contenido de seis caracteres, sin explicaciones ni frases adicionales.",
            img
        ]

        while True:
            # El lock solo protege la elección de key; la llamada a la API va
            # afuera para que varios workers puedan consultar Gemini en paralelo.
            with self.key_lock:
                indice = self.indice_gemini_actual
                if indice >= len(self.gemini_keys):
                    raise ProveedorNoDisponible("Todas las keys de Gemini agotadas")
                genai.configure(api_key=self.gemini_keys[indice])
                model = genai.GenerativeModel('gemini-2.5-flash')

            try:
                response = model.generate_content(prompt)
                return self.limpiar_respuesta_captcha(response.text.strip())
            except Exception as e:
                if not self._es_error_cuota_gemini(e):
                    raise
                with self.key_lock:
                    # Solo avanza si otro worker no la avanzó ya (evita saltear keys)
                    if self.indice_gemini_actual == indice:
                        self.indice_gemini_actual += 1
                        print(f"⏹️ Key Gemini {indice + 1}/{len(self.gemini_keys)} sin cuota: {e}")

    def _es_error_cuota_gemini(self, e):
        error_str = str(e).lower()
        return any(keyword in error_str for keyword in [
            'quota', 'rate limit', 'ratelimit', 'rate_limit', 'limit exceeded',
            'resource exhausted', 'resourceexhausted', 'resource_exhausted', '429',
            'billing', 'credits', 'usage limit', 'api limit',
            'requests per minute', 'requests per day', 'daily limit',
            'api key not valid', 'api_key_invalid',
        ])

    def _resolver_con(self, provider, imagen_b64):
        if provider == "nopecha":
            return self.resolver_con_nopecha(imagen_b64)
        if provider == "gemini":
            return self.resolver_con_gemini(imagen_b64)
        return self.resolver_con_createtask(provider, imagen_b64)

    # ------------------------------------------------------------------
    # Punto de entrada
    # ------------------------------------------------------------------
    def resolver_captcha(self, driver):
        """
        Resuelve el CAPTCHA probando los proveedores en orden.

        Returns:
            str: código del CAPTCHA resuelto
            None: ningún proveedor pudo resolverlo en este intento
            "CUOTA_AGOTADA": no queda ningún proveedor disponible
        """
        if not self.proveedores_disponibles():
            return "CUOTA_AGOTADA"

        try:
            imagen_b64 = self.capturar_captcha_base64(driver)
        except Exception as e:
            print(f"❌ No se pudo capturar la imagen del CAPTCHA: {e}")
            return None

        for provider in self.proveedores_disponibles():
            nombre = NOMBRES_PROVIDERS[provider]
            try:
                texto = self.limpiar_respuesta_captcha(self._resolver_con(provider, imagen_b64))
            except ProveedorNoDisponible as e:
                with self.quota_lock:
                    self.no_disponibles.add(provider)
                print(f"🚫 {nombre} NO DISPONIBLE (sin crédito o key inválida): {e}")
                continue
            except Exception as e:
                texto = ""
                print(f"❌ Error en {nombre}: {e}")

            with self.quota_lock:
                if texto:
                    self.consultas[provider] += 1
                else:
                    self.fallos[provider] += 1

            if texto:
                print(f"✅ CAPTCHA resuelto con {nombre}: {texto}")
                return texto
            print(f"⚠️ {nombre} no pudo resolver el CAPTCHA, probando el siguiente...")

        return None if self.proveedores_disponibles() else "CUOTA_AGOTADA"

    def proveedores_disponibles(self):
        with self.quota_lock:
            return [p for p in self.providers if p not in self.no_disponibles]

    def obtener_estadisticas(self):
        """Retorna estadísticas de uso (incluye las claves antiguas que usa la GUI)"""
        disponibles = self.proveedores_disponibles()
        return {
            "proveedores": {
                p: {
                    "nombre": NOMBRES_PROVIDERS[p],
                    "configurado": p in self.providers,
                    "disponible": p in disponibles,
                    "consultas": self.consultas[p],
                    "fallos": self.fallos[p],
                }
                for p in ORDEN_PROVIDERS_DEFAULT
            },
            "orden": list(self.providers),
            # Hay algún servicio pago (cualquiera menos Gemini) disponible
            "servicio_pago_disponible": any(p != "gemini" for p in disponibles),
            "provider_actual": disponibles[0] if disponibles else "",
            # Claves históricas
            "consultas_nopecha": self.consultas["nopecha"],
            "consultas_gemini": self.consultas["gemini"],
            "cuota_nopecha_agotada": "nopecha" in self.no_disponibles,
            "todas_keys_gemini_agotadas": "gemini" in self.no_disponibles or not self.gemini_keys,
            "indice_gemini_actual": self.indice_gemini_actual,
            "total_keys_gemini": len(self.gemini_keys)
        }

    def cambiar_provider(self, nuevo_provider):
        """Mueve un proveedor al principio del orden de prueba"""
        if nuevo_provider in self.providers:
            with self.quota_lock:
                self.providers.remove(nuevo_provider)
                self.providers.insert(0, nuevo_provider)
                print(f"🔄 Proveedor prioritario: {NOMBRES_PROVIDERS[nuevo_provider]}")
