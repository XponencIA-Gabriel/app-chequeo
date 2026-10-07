import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv() 

class SSSPadronAutomation:
    def __init__(self):
        self.url = os.getenv("URL_SSS_PADRON")
        self.chrome_driver_path = None
        self.inicializar_driver_path()

        if not self.url:
                raise ValueError("URL_SSS_PADRON no configurada en variables de entorno")
    
    def inicializar_driver_path(self):
        """Inicializa el path del ChromeDriver una sola vez"""
        if not self.chrome_driver_path:
            print("🔧 Inicializando ChromeDriver...")
            self.chrome_driver_path = ChromeDriverManager().install()
            print(f"✅ ChromeDriver listo: {self.chrome_driver_path}")
    
    def crear_driver(self):
        """Mismo driver que SSS principal (probado y estable)"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--log-level=3")
        service = Service(self.chrome_driver_path)
        return webdriver.Chrome(service=service, options=chrome_options)
    
    def formatear_cuil(self, cuil):
        """Toma un CUIL como string de 11 dígitos y lo devuelve en formato XX-XXXXXXXX-X."""
        if not cuil:
            return None
        
        # Limpiar
        cuil_numerico = ''.join(filter(str.isdigit, str(cuil)))
        
        if len(cuil_numerico) != 11:
            return None
        
        # Formatear XX-XXXXXXXX-X
        return f"{cuil_numerico[:2]}-{cuil_numerico[2:10]}-{cuil_numerico[10]}"
    
    def consultar_cuil(self, cuil, captcha_solver):
        """
        Consulta CUIL en SSS Padrón
        Returns:
            dict: Resultado con datos o sin datos
            "CAPTCHA_INCORRECTO": CAPTCHA mal resuelto
            "CUOTA_AGOTADA": APIs agotadas
            None: Error
        """
        driver = None
        
        try:
            cuil_formateado = self.formatear_cuil(cuil)
            if not cuil_formateado:
                return None
            
            driver = self.crear_driver()
            
            print(f"🌐 Navegando a SSS Padrón para CUIL: {cuil}")
            driver.get(self.url)
            
            # PASO 1: Llenar CUIL
            cuil_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "cuil_b"))
            )
            cuil_input.clear()
            cuil_input.send_keys(cuil_formateado)
            
            # PASO 2: Resolver CAPTCHA
            print(f"🔍 Resolviendo CAPTCHA SSS Padrón para CUIL: {cuil}")
            codigo_captcha = captcha_solver.resolver_captcha(driver)
            
            if codigo_captcha == "CUOTA_AGOTADA":
                print(f"🚫 Cuotas agotadas en SSS Padrón")
                return "CUOTA_AGOTADA"
            
            if not codigo_captcha:
                print(f"❌ No se pudo resolver CAPTCHA SSS Padrón")
                return None
            
            # PASO 3: Enviar formulario
            driver.find_element(By.NAME, "code").send_keys(codigo_captcha)
            driver.find_element(By.NAME, "B1").click()
            
            # PASO 4: Procesar respuesta
            return self.procesar_respuesta(driver, cuil)
            
        except Exception as e:
            print(f"❌ Error en SSS Padrón para CUIL {cuil}: {str(e)}")
            return None
            
        finally:
            if driver:
                driver.quit()
    
    def procesar_respuesta(self, driver, cuil):
        """
        Procesa respuesta usando EC.any_of() (estrategia probada de SSS)
        """
        try:
            # ⭐ DEFINIR SELECTORES
            TABLAS_SELECTOR = (By.CLASS_NAME, "tablaconsultas")
            SINDATOS_SELECTOR = (By.XPATH, "//b[contains(text(), 'No se reportan datos para el CUIL')]")
            
            # ⭐ ESPERAR A QUE APAREZCA ALGUNO DE LOS DOS
            try:
                elemento_resultado = WebDriverWait(driver, 10).until(
                    EC.any_of(
                        EC.visibility_of_element_located(TABLAS_SELECTOR),
                        EC.visibility_of_element_located(SINDATOS_SELECTOR)
                    )
                )
                
                # ⭐ VERIFICAR QUÉ APARECIÓ
                # Caso 1: Mensaje sin datos
                if elemento_resultado.tag_name == "b":
                    mensaje = elemento_resultado.text.strip()
                    print(f"📝 SSS Padrón - Sin datos: {mensaje}")
                    return {
                        "Estado Chequeo": "NO",
                        "Obra Social": mensaje,
                        "Fecha Alta": "N/A",
                        "Fecha Baja": "N/A",
                        "Tipo": "N/A",
                        "Estado": "N/A"
                    }
                
                # Caso 2: Tabla con datos
                elif "tablaconsultas" in elemento_resultado.get_attribute("class"):
                    print(f"📊 SSS Padrón - Tabla encontrada para {cuil}")
                    # Buscar TODAS las tablas (puede haber 2: Personales + Afiliación)
                    tablas = driver.find_elements(By.CLASS_NAME, "tablaconsultas")
                    return self.extraer_datos_tablas(tablas, cuil)
            
            except TimeoutException:
                # ⭐ TIMEOUT = Ni tablas ni mensaje → CAPTCHA INCORRECTO
                print(f"❌ SSS Padrón - CAPTCHA incorrecto para {cuil} (timeout sin resultados)")
                return "CAPTCHA_INCORRECTO"
            
        except Exception as e:
            print(f"❌ Error procesando respuesta SSS Padrón: {str(e)}")
            return None

    def extraer_datos_tablas(self, tablas, cuil):
        """Extrae datos de las tablas"""
        try:
            datos = {}
            
            for tabla in tablas:
                filas = tabla.find_elements(By.TAG_NAME, "tr")
                
                for fila in filas:
                    celdas_th = fila.find_elements(By.TAG_NAME, "th")
                    celdas_td = fila.find_elements(By.TAG_NAME, "td")
                    
                    if len(celdas_th) > 0 and len(celdas_td) > 0:
                        label = celdas_th[0].text.strip()
                        valor = celdas_td[0].text.strip()
                        datos[label] = valor
            
            if not datos:
                print(f"❓ SSS Padrón - Tablas vacías para {cuil}")
                return None
            
            # Mapear a Excel
            resultado = {
                "Estado Chequeo": "OK",
                "Obra Social": datos.get("Denominación Obra Social", "S/D").strip(),
                "Fecha Alta": datos.get("Fecha Alta Obra Social", "S/D").strip(),
                "Fecha Baja": "S/D",
                "Tipo": datos.get("Tipo beneficiario", "S/D").strip(),
                "Estado": datos.get("Parentesco", "S/D").strip()
            }
            
            print(f"✅ SSS Padrón - Datos OK: {resultado['Obra Social']}")
            return resultado
            
        except Exception as e:
            print(f"❌ Error extrayendo datos: {str(e)}")
            return None