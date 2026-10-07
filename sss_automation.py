import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv()

class SSSAutomation:
    def __init__(self):
        self.url= os.getenv("URL_SSS")
        self.chrome_driver_path = None
        self.inicializar_driver_path()
        
        if not self.url:
            raise ValueError("URL_SSS no configurada en variables de entorno")
    
    def inicializar_driver_path(self):
        """Inicializa el path del ChromeDriver una sola vez"""
        if not self.chrome_driver_path:
            print("🔧 Inicializando ChromeDriver...")
            self.chrome_driver_path = ChromeDriverManager().install()
            print(f"✅ ChromeDriver listo: {self.chrome_driver_path}")

    def crear_driver(self):
        """Crea una instancia de ChromeDriver con configuración optimizada"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--log-level=3")
        service = Service(self.chrome_driver_path)
        return webdriver.Chrome(service=service, options=chrome_options)
    
    def formatear_cuil(self, cuil_sin_formato):
        """Toma un CUIL como string de 11 dígitos y lo devuelve en formato XX-XXXXXXXX-X."""
        s_cuil = str(cuil_sin_formato).strip()
        if not s_cuil.isdigit():
            return None
        if len(s_cuil) not in (10, 11):
            return None
        return f"{s_cuil[:2]}-{s_cuil[2:-1]}-{s_cuil[-1]}"

    def consultar_cuil(self, cuil, captcha_solver):
        """
        Consulta un CUIL en el sitio de SSS usando el captcha_solver para resolver CAPTCHAs
        
        Args:
            cuil (str): CUIL a consultar
            captcha_solver (CaptchaSolver): Instancia del solucionador de CAPTCHA
        Returns:
            dict: Resultado de la consulta con información de la obra social
            None: Si hubo error en la consulta
            str: "CUOTA_AGOTADA" si se agotaron todas las cuotas de CAPTCHA
        """
        driver = None
        
        try:
            # Formatear CUIL
            cuil_formateado = self.formatear_cuil(cuil)
            if not cuil_formateado:
                return None
            
            # Crear driver
            driver = self.crear_driver()
            
            # Navegar al sitio
            print(f"🌐 Navegando a SSS para CUIL: {cuil}")
            driver.get(self.url)
            
            # Llenar formulario de CUIL
            cuil_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "nro_cuil"))
            )
            cuil_input.clear()
            cuil_input.send_keys(cuil_formateado)
            
            # Resolver CAPTCHA usando el solver
            print(f"🔍 Resolviendo CAPTCHA para CUIL: {cuil}")
            codigo_captcha = captcha_solver.resolver_captcha(driver)
            
            if codigo_captcha == "CUOTA_AGOTADA":
                print(f"🚫 Cuotas agotadas para CUIL: {cuil}")
                return "CUOTA_AGOTADA"
            
            if not codigo_captcha:
                print(f"❌ No se pudo resolver CAPTCHA para CUIL: {cuil}")
                return None
            
            # Enviar formulario
            driver.find_element(By.NAME, "code").send_keys(codigo_captcha)
            driver.find_element(By.NAME, "buscar").click()
            
            try:
                time.sleep(3)

                page_source = driver.page_source
                # Detectar variantes del mismo error
                captcha_error_patterns = [
                    "Ingrese correctamente el código mostrado",
                    "El código mostrado no es correcto"
                ]
                
                page_lower = page_source.lower()
                for pattern in captcha_error_patterns:
                    if pattern.lower() in page_lower:
                        print(f"❌ CAPTCHA incorrecto (variante) para CUIL: {cuil}: {pattern}")
                        return "CAPTCHA_INCORRECTO"
            
                # Procesar respuesta
                return self.procesar_respuesta_sss(driver, cuil)

            except TimeoutException:
                print(f"⏰ Timeout esperando respuesta para CUIL: {cuil}")
                try:
                    page_source = driver.page_source
                    if "Ingrese correctamente el código mostrado" in page_source:
                        print(f"❌ CAPTCHA incorrecto detectado en timeout para CUIL: {cuil}")
                        return "CAPTCHA_INCORRECTO"
                except:
                    pass
                return None
            
        except TimeoutException:
            print(f"⏰ Timeout procesando CUIL: {cuil}")
            return None
            
        except Exception as e:
            print(f"❌ Error procesando CUIL {cuil}: {str(e)}")
            return None
            
        finally:
            if driver:
                driver.quit()
    
    def procesar_respuesta_sss(self, driver, cuil):
        """
        Procesa la respuesta del sitio SSS y extrae los datos
        
        Args:
            driver: Instancia de Selenium WebDriver
            cuil (str): CUIL consultado (para logging)
            
        Returns:
            dict: Datos extraídos de la obra social
        """
        try:
            # Buscar resultados con timeout
            TABLA_SELECTOR = (By.TAG_NAME, "table")  
            SINDATOS_SELECTOR = (By.XPATH, "//b[contains(text(), 'No existen datos para el CUIL')]")
            
            elemento_resultado = WebDriverWait(driver, 10).until(
                EC.any_of(
                    EC.visibility_of_element_located(TABLA_SELECTOR),
                    EC.visibility_of_element_located(SINDATOS_SELECTOR)
                )
            )
        
            
            if elemento_resultado.tag_name == "table":
                # Hay datos en tabla
                print(f"📊 Tabla encontrada para CUIL: {cuil}")
                
                filas = elemento_resultado.find_elements(By.TAG_NAME, "tr")
                celdas = filas[-1].find_elements(By.TAG_NAME, "td")
                
                resultado = {
                    "Estado Chequeo": "OK",
                    "Obra Social": celdas[1].text.strip() if len(celdas) > 1 else "S/D",
                    "Fecha Alta": celdas[2].text.strip() if len(celdas) > 2 else "S/D",
                    "Fecha Baja": celdas[3].text.strip() if len(celdas) > 3 else "S/D",
                    "Tipo": celdas[4].text.strip() if len(celdas) > 4 else "S/D",
                    "Estado": celdas[5].text.strip() if len(celdas) > 5 else "S/D"
                }
                
                print(f"✅ Datos OK para CUIL {cuil}: {resultado['Obra Social']}")
                return resultado
                
            elif elemento_resultado.tag_name == "b":
                # Mensaje sin datos
                msg = elemento_resultado.text.strip()
                
                resultado = {
                    "Estado Chequeo": "NO", 
                    "Obra Social": msg,
                    "Fecha Alta": "N/A",
                    "Fecha Baja": "N/A",
                    "Tipo": "N/A",
                    "Estado": "N/A"
                }
                
                print(f"📝 Sin datos para CUIL {cuil}: {msg}")
                return resultado
                
        except TimeoutException:
            print(f"⏰ Timeout esperando respuesta para CUIL: {cuil}")
            return None
            
        except Exception as e:
            print(f"❌ Error procesando respuesta para CUIL {cuil}: {str(e)}")
            return None
    
