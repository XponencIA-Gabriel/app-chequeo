"""
CAPA DE NEGOCIO - Motor de procesamiento principal
Orquesta ExcelManager + Adapters + lógica de fallback
Reemplaza ProcessingEngine separando GUI de business logic
"""

import random
import threading
import queue
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import concurrent.futures

from excel_manager import ExcelManager
from captcha_solver import CaptchaSolver
from sss_automation import SSSAutomation
from sss_padron_automation import SSSPadronAutomation

class BusinessEngine:

    def __init__(self, callback_gui=None):
        # Managers de capas inferiores
        self.excel_manager: Optional[ExcelManager] = None
        self.captcha_solver: Optional[CaptchaSolver] = None
        self.sss_automation: Optional[SSSAutomation] = None
        self.sss_padron_automation: Optional[SSSPadronAutomation] = None
        
        # Estado de procesamiento
        self.proceso_activo = False
        self.proceso_pausado = False
        self.detener_solicitado = False
        
        # Estadísticas
        self.registros_procesados = 0
        self.registros_exitosos = 0
        self.errores_detectados = 0
        self.tiempo_inicio = None
        
        # Guardado periódico
        self.contador_guardados = 0
        self.intervalo_guardado = 5  # Cada 5 registros como en adapters
        
        # Comunicación con GUI (opcional)
        self.callback_gui = callback_gui
        self.control_queue = queue.Queue()
        
        # Thread safety
        self.lock = threading.Lock()
    
    def cargar_archivo(self, archivo_path: str) -> Dict:
        """
        Carga archivo Excel y prepara recursos necesarios
        
        Args:
            archivo_path: Ruta al archivo Excel
            
        Returns:
            dict: Resultado de la carga
        """
        try:
            # Crear ExcelManager y cargar archivo
            self.excel_manager = ExcelManager(archivo_path)
            resultado = self.excel_manager.cargar_archivo()
            
            if not resultado["success"]:
                return resultado
            
            # Notificar GUI si existe callback
            self.notificar_gui("archivo_cargado", resultado["stats"], resultado["message"])
            
            return resultado
            
        except Exception as e:
            mensaje_error = f"Error cargando archivo: {str(e)}"
            self.notificar_gui("error", {"error": str(e)}, mensaje_error)
            return {"success": False, "message": mensaje_error}
    
    def iniciar_procesamiento(self, num_workers: int = 6) -> Dict:
        """
        Inicia el procesamiento completo de CUILs pendientes
        Args:
            num_workers: Número de workers concurrentes
            
        Returns:
            dict: Resultado del procesamiento
        """
        if not self.excel_manager:
            return {"success": False, "message": "No hay archivo cargado"}
        
        if num_workers <= 0:
            return {
                "success": False, 
                "message": f"Workers inválidos: {num_workers}. Debe ser mayor a 0."
            }

        try:
            # Inicializar otros managers
            if not self.captcha_solver:
                self.captcha_solver= CaptchaSolver()
                self.notificar_gui("info", {}, "🔧 CaptchaSolver inicializado")

            if not self.sss_automation:
                self.sss_automation = SSSAutomation()
                self.notificar_gui("info", {}, "🌐  SSSAutomation inicializado")
            
            if not self.sss_padron_automation:
                self.sss_padron_automation = SSSPadronAutomation()
                self.notificar_gui("info", {}, "🌐  SSS Padron inicializado")
            # Obtener CUILs pendientes
            cuils_pendientes = self.excel_manager.obtener_cuils_pendientes()
            
            if not cuils_pendientes:
                mensaje = "No hay CUILs pendientes para procesar"
                self.notificar_gui("info", {}, mensaje)
                return {"success": True, "message": mensaje, "procesados": 0}
            
            # Inicializar procesamiento
            with self.lock:
                self.proceso_activo = True
                self.detener_solicitado = False
                self.tiempo_inicio = time.time()
                self.registros_procesados = 0
                self.registros_exitosos = 0
                self.errores_detectados = 0
                self.contador_guardados = 0
            
            self.notificar_gui("inicio_procesamiento", {
                "total": len(cuils_pendientes),
                "workers": num_workers,
                "fuente": "SSS"
            })
            
            # Procesamiento con workers concurrentes
            resultado_procesamiento = self.procesar_cuils_concurrentes(
                cuils_pendientes, 
                num_workers
            )
            
            # Guardado final obligatorio
            self.excel_manager.guardar_excel()
            self.notificar_gui("guardado_final", {"archivo": self.excel_manager.archivo_salida})
            
            # Estadísticas finales
            tiempo_total = time.time() - self.tiempo_inicio if self.tiempo_inicio else 0
            
            return {
                "success": True,
                "message": "Procesamiento completado",
                "procesados": self.registros_exitosos,
                "errores": self.errores_detectados,
                "tiempo_total": tiempo_total,
                "detalles": resultado_procesamiento
            }
            
        except Exception as e:
            self.notificar_gui("error", {"error": str(e)}, f"Error en procesamiento: {str(e)}")
            return {"success": False, "message": str(e)}
        
        finally:
            with self.lock:
                self.proceso_activo = False

    def procesar_cuils_concurrentes(self, cuils_pendientes: List[Tuple[int, str]], num_workers: int) -> Dict:
        """
        Procesa CUILs usando ThreadPoolExecutor
        Maneja guardado periódico basado en lógica actual [attached_file:1]
        """
        cuota_agotada_detectada = False
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            # Enviar tareas
            futuros = {
                executor.submit(self.procesar_cuil_individual, index, cuil): (index, cuil)
                for index, cuil in cuils_pendientes
            }
            
            for futuro in concurrent.futures.as_completed(futuros):
                if self.detener_solicitado or cuota_agotada_detectada:
                    self.notificar_gui("info", {}, "Deteniendo procesamiento...")
                    
                    # Cancelar futuros pendientes
                    cancelados = 0
                    for f in futuros:
                        if not f.done():
                            f.cancel()
                            cancelados += 1
                    
                    self.notificar_gui("info", {}, f"{cancelados} tareas canceladas")
                    break
                
                try:
                    index, cuil = futuros[futuro]
                    resultado = futuro.result()
                    
                    if resultado == "CUOTA_AGOTADA":
                        cuota_agotada_detectada = True
                        self.notificar_gui("cuota_agotada", {"proveedor": "CAPTCHA"})
                        break
                    
                    if resultado is not None:
                        with self.lock:
                            self.contador_guardados += 1
                            
                            # **GUARDADO PERIÓDICO** - Lógica extraída de adapters
                            if self.contador_guardados % self.intervalo_guardado == 0:
                                self.excel_manager.guardar_excel()
                                self.notificar_gui("guardado_periodico", {
                                    "registros": self.contador_guardados
                                })
                    
                    with self.lock:
                        self.registros_procesados += 1
                
                except concurrent.futures.CancelledError:
                    pass
                except Exception as e:
                    self.notificar_gui("error", {"error": str(e)}, f"Error en worker: {str(e)}")
        
        return {
            "cuota_agotada": cuota_agotada_detectada,
            "procesados": self.registros_procesados,
            "exitosos": self.registros_exitosos,
            "errores": self.errores_detectados
        }
    
    def procesar_cuil_individual(self, index: int, cuil: str, max_intentos: int = 50):
        """
        Distingue entre "sin datos" (válido) y errores (reintentar)
        """
        if self.detener_solicitado:
            return None

        self.notificar_gui("procesando_cuil", {"cuil": cuil, "index": index})           

        for intento in range(1, max_intentos + 1):
            if self.detener_solicitado:
                self.notificar_gui("info", {}, f"Proceso detenido en intento {intento} para CUIL {cuil}")
                return None
            
            print(f"🔄 Intento {intento}/{max_intentos} para CUIL: {cuil}")
            
            try:
                # ========================================
                # PASO 1: INTENTAR SSS
                # ========================================
                resultado_sss = self.sss_automation.consultar_cuil(cuil, self.captcha_solver)
                
                if resultado_sss == "CUOTA_AGOTADA":
                    self.notificar_gui("cuota_agotada", {"proveedor": "CAPTCHA"})
                    return "CUOTA_AGOTADA"
                
                if resultado_sss == "CAPTCHA_INCORRECTO":
                    # ERROR TÉCNICO → REINTENTAR
                    self.notificar_gui("info", {}, f"❌ CAPTCHA incorrecto - Intento {intento}/{max_intentos}")
                    time.sleep(1)
                    continue  # REINTENTAR
                
                if resultado_sss is not None and isinstance(resultado_sss, dict):
                    estado_sss = resultado_sss.get("Estado Chequeo", "NO")
                    
                    if estado_sss == "OK":
                        # ✅ SSS CON DATOS → GUARDAR Y FINALIZAR
                        resultado_sss["Fuente Datos"] = "SSS"
                        guardado = self.excel_manager.guardar_resultado(index, resultado_sss)
                        
                        if guardado:
                            with self.lock:
                                self.registros_exitosos += 1
                            
                            self.notificar_gui("cuil_procesado", {
                                "cuil": cuil,
                                "resultado": "OK",
                                "obra_social": resultado_sss.get("Obra Social", "N/A"),
                                "fuente": "SSS",
                                "intento": intento
                            })
                            
                            print(f"✅ ÉXITO SSS: {resultado_sss.get('Obra Social', 'N/A')}")
                            return resultado_sss
                
                # ========================================
                # PASO 2: SSS SIN DATOS → FALLBACK SSS PADRÓN
                # ========================================
                print(f"🔄 SSS sin datos - Fallback a SSS PADRÓN")
                self.notificar_gui("info", {}, f"🔄 Consultando en SSS Padrón para {cuil}")
                
                resultado_padron = self.sss_padron_automation.consultar_cuil(cuil, self.captcha_solver)
                
                if resultado_padron == "CAPTCHA_INCORRECTO":
                    self.notificar_gui("info", {}, 
                        f"❌ SSS Padrón CAPTCHA incorrecto - Intento {intento}/{max_intentos}")
                    time.sleep(1)
                    continue  # ⭐ REINTENTAR todo
            
                # Manejar cuota agotada en Padrón
                if resultado_padron == "CUOTA_AGOTADA":
                    self.notificar_gui("cuota_agotada", {"proveedor": "CAPTCHA"})
                    return "CUOTA_AGOTADA"

                # SSS Padrón retornó resultado válido
                if resultado_padron is not None and isinstance(resultado_padron, dict):
                    estado_padron = resultado_padron.get("Estado Chequeo", "NO")
                    
                    # ✅ SSS PADRÓN CON DATOS → GUARDAR Y FINALIZAR
                    if estado_padron == "OK":
                        resultado_padron["Fuente Datos"] = "SSS Padrón"
                        
                        guardado = self.excel_manager.guardar_resultado(index, resultado_padron)
                        
                        if guardado:
                            with self.lock:
                                self.registros_exitosos += 1
                            
                            self.notificar_gui("cuil_procesado", {
                                "cuil": cuil,
                                "resultado": "OK",
                                "obra_social": resultado_padron.get("Obra Social", "N/A"),
                                "fuente": "SSS Padrón",
                                "intento": intento
                            })
                            
                            print(f"✅ ÉXITO SSS Padrón en intento {intento}: {resultado_padron.get('Obra Social', 'N/A')}")
                            return resultado_padron
                        else:
                            # Error guardando → REINTENTAR
                            self.notificar_gui("info", {}, f"⚠️ Error guardando SSS Padrón - Reintentando")
                            time.sleep(1)
                            continue
                
                # ========================================
                # ⭐ CASO ESPECIAL: AMBOS SIN DATOS (RESULTADO VÁLIDO)
                # ========================================
                print(f"📝 Sin datos en SSS y SSS Padrón para {cuil} - Guardando")
                
                resultado_sin_datos = {
                    "Estado Chequeo": "NO",
                    "Obra Social": "Sin datos en SSS y SSS Padrón",
                    "Fecha Alta": "N/A",
                    "Fecha Baja": "N/A",
                    "Tipo": "N/A",
                    "Estado": "N/A",
                    "Fuente Datos": "SSS+Padrón"
                }
                
                guardado = self.excel_manager.guardar_resultado(index, resultado_sin_datos)
                
                if guardado:
                    with self.lock:
                        self.registros_exitosos += 1
                    
                    self.notificar_gui("cuil_procesado", {
                        "cuil": cuil,
                        "resultado": "NO",
                        "obra_social": "Sin datos",
                        "fuente": "SSS+Padrón",
                        "intento": intento
                    })
                    
                    print(f"✅ Sin datos confirmado para {cuil}")
                    return resultado_sin_datos
                else:
                    # Error guardando → REINTENTAR
                    self.notificar_gui("info", {}, f"⚠️ Error guardando 'Sin datos' - Reintentando")
                    time.sleep(1)
                    continue
                
            except Exception as e:
                # ERROR TÉCNICO → REINTENTAR
                self.notificar_gui("info", {}, f"⚠️ Excepción técnica intento {intento}: {str(e)}")
                print(f"❌ Excepción en intento {intento}: {str(e)}")
                time.sleep(1)
        
        # SOLO DESPUÉS DE AGOTAR INTENTOS POR ERRORES TÉCNICOS
        with self.lock:
            self.errores_detectados += 1
        
        self.notificar_gui("error_no_guardado", 
                        {"cuil": cuil}, 
                        f"❌ CUIL {cuil} falló después de {max_intentos} intentos - NO SE GUARDARÁ")
        return None

    def detener_procesamiento(self):
        """Solicita detener el procesamiento de forma thread-safe"""
        with self.lock:
            self.detener_solicitado = True
            self.proceso_activo = False
        
        self.notificar_gui("info", {}, "Comando DETENER recibido")
    
    def obtener_estadisticas(self) -> Dict:
        """Obtiene estadísticas actuales del procesamiento"""
        with self.lock:
            estadisticas_excel = self.excel_manager.obtener_estadisticas() if self.excel_manager else {}
            estadisticas_captcha = self.captcha_solver.obtener_estadisticas() if self.captcha_solver else {}
            
            return {
                **estadisticas_excel,
                "registros_procesados": self.registros_procesados,
                "registros_exitosos": self.registros_exitosos,
                "errores_detectados": self.errores_detectados,
                "proceso_activo": self.proceso_activo,
                "tiempo_inicio": self.tiempo_inicio,
                "contador_guardados": self.contador_guardados,
                "captcha_stats": estadisticas_captcha
            }
    
    def notificar_gui(self, tipo: str, data: Dict = None, mensaje: str = ""):
        """Notifica eventos a la GUI si hay callback configurado"""
        if self.callback_gui:
            try:
                self.callback_gui({
                    "tipo": tipo,
                    "data": data or {},
                    "mensaje": mensaje,
                    "timestamp": datetime.now()
                })
            except Exception as e:
                print(f"❌ Error notificando GUI: {e}")
    
def crear_business_engine(callback_gui=None) -> BusinessEngine:
    """Crea una instancia del BusinessEngine con callback opcional para GUI"""
    return BusinessEngine(callback_gui=callback_gui)  

