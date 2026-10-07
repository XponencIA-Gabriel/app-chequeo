"""
Módulo de gestión de archivos Excel
Centraliza toda la lógica de lectura, escritura y manejo de datos Excel
separando completamente del GUI y lógica de automatización web
"""

import pandas as pd
import os
import threading
from datetime import datetime
from typing import Dict, List, Tuple

class ExcelManager:
    def __init__(self, archivo_path: str):
        self.archivo_path = archivo_path
        # El original nunca se sobreescribe: los resultados van a una copia aparte,
        # que también sirve como checkpoint si el proceso se interrumpe a mitad de camino.
        nombre, extension = os.path.splitext(archivo_path)
        self.archivo_salida = f"{nombre}_procesado{extension}"
        self.df = None
        self.lock = threading.Lock()
        
        # Columnas estándar del resultado
        self.nuevas_columnas = [
            "Estado Chequeo", "Obra Social", "Fecha Alta", 
            "Fecha Baja", "Tipo", "Estado", "Fuente Datos"
        ]

        # Estadísticas thread-safe
        self.registros_totales = 0
        self.registros_procesados = 0
        self.registros_exitosos = 0
        self.errores_detectados = 0
    
    def cargar_archivo(self) -> Dict:
        """Carga el archivo Excel y prepara las columnas necesarias"""
        try:
            if not os.path.exists(self.archivo_path):
                return {
                    "success": False,
                    "message": f"Archivo no encontrado: {self.archivo_path}",
                    "stats": {}
                }

            # Si existe una copia con progreso de una corrida anterior (interrumpida o no),
            # se retoma desde ahí para no perder lo ya procesado ni volver a tocar el original.
            retomando = os.path.exists(self.archivo_salida)
            archivo_a_leer = self.archivo_salida if retomando else self.archivo_path

            # Leer Excel con CUIL como string (como ProcessingEngine) [attached_file:3]
            self.df = pd.read_excel(archivo_a_leer, dtype={"CUIL": str})
            self.df.columns = self.df.columns.astype(str).str.strip()
            
            # Verificar columna CUIL obligatoria
            if "CUIL" not in self.df.columns:
                return {
                    "success": False,
                    "error": "No se encontró la columna CUIL en el archivo",
                    "stats": {}
                }
            
            # Crear columnas faltantes
            columnas_creadas = self.crear_columnas_faltantes()

            # Limpiar datos
            self.limpiar_datos()
            
            stats = {
                "total_registros": len(self.df),
                "columnas_creadas": columnas_creadas,
                "archivo_path": self.archivo_path,
                "archivo_salida": self.archivo_salida,
                "retomando": retomando
            }

            mensaje = f"Excel cargado exitosamente: {len(self.df)} registros"
            if retomando:
                mensaje += f" (retomando progreso desde {os.path.basename(self.archivo_salida)})"

            return {
                "success": True,
                "message": mensaje,
                "stats": stats
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Error cargando Excel: {str(e)}"
            }
    
    def crear_columnas_faltantes(self) -> List[str]:
        """Crea columnas que no existen"""
        columnas_creadas = []
        
        for col in self.nuevas_columnas:
            if col not in self.df.columns:
                self.df[col] = ""
                columnas_creadas.append(col)
        
        return columnas_creadas
    
    def limpiar_datos(self):
        """Limpia y normaliza datos"""
        # Limpiar Estado Chequeo
        self.df["Estado Chequeo"] = (
            self.df["Estado Chequeo"]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        
        # Limpiar CUIL
        self.df["CUIL"] = (
            self.df["CUIL"]
            .fillna("")
            .astype(str)
            .str.strip()
        )
    
    def obtener_cuils_pendientes(self) -> List[Tuple[int, str]]:
        """Retorna lista de CUILs pendientes (Estado Chequeo vacío)"""
        if self.df is None:
            return []
        
        try:
            # Filtrar pendientes
            df_pendientes = self.df[
                (self.df["Estado Chequeo"].isna()) | 
                (self.df["Estado Chequeo"] == "")
            ].copy()
            
            return [(index, row["CUIL"]) for index, row in df_pendientes.iterrows()]
            
        except Exception as e:
            print(f"❌ Error obteniendo CUILs pendientes: {e}")
            return []
    
    def guardar_resultado(self, index :int, resultado : Dict[str, str]) -> bool:
        """
        Guarda resultado de un CUIL procesado
        Args:
            index: Índice en el DataFrame
            resultado: Dictionary con campos a guardar
        Returns:
            bool: True si se guardó exitosamente
        """
        with self.lock:
            if self.df is None:
                return False
            
            try:
                # Guardar todos los campos del resultado
                for campo, valor in resultado.items():
                    if campo in self.df.columns:
                        self.df.loc[index, campo] = valor
                
                return True
                
            except Exception as e:
                print(f"❌ Error guardando resultado en índice {index}: {e}")
                return False
            
    def marcar_error(self, index, mensaje_error):
        """Marca error sin guardarlo (filosofía de reprocesamiento)"""
        with self.lock:
            self.errores_detectados += 1
            print(f"⚠️  Error en índice {index}: {mensaje_error}")

    def guardar_excel(self) -> bool:
        """
        Guarda el Excel en disco de forma atómica: escribe primero a un archivo
        temporal y recién al terminar reemplaza el archivo de salida (os.replace).
        Así, si el proceso se interrumpe a mitad del guardado, el peor caso es
        quedar con el temporal a medio escribir (que se descarta), nunca con
        el archivo de salida corrupto o truncado.

        Returns:
            bool: True si se guardó exitosamente
        """
        with self.lock:
            if self.df is not None:
                temp_path = f"{self.archivo_salida}.tmp"
                try:
                    self.df.to_excel(temp_path, index=False)
                    os.replace(temp_path, self.archivo_salida)
                    return True
                except Exception as e:
                    print(f"❌ Error guardando Excel: {e}")
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                    return False
        return False
    
    def obtener_estadisticas(self) -> Dict:
        """
        Obtiene estadísticas del DataFrame
        
        Returns:
            dict: Estadísticas actuales
        """
        if self.df is None:
            return {"error": "No hay datos cargados"}
        
        with self.lock:
            total = len(self.df)
            procesados = len(self.df[
                (self.df["Estado Chequeo"] != "") & 
                (self.df["Estado Chequeo"].notna())
            ])
            pendientes = total - procesados
            
            # Estadísticas por fuente
            fuentes = self.df["Fuente Datos"].value_counts().to_dict()
            
            return {
                "total_registros": total,
                "registros_procesados": procesados,
                "registros_pendientes": pendientes,
                "porcentaje_completado": (procesados / total * 100) if total > 0 else 0,
                "fuentes_datos": fuentes,
                "archivo_path": self.archivo_path
            }

    def validar_estructura(self) -> Dict:
        """
        Valida que el DataFrame tenga la estructura correcta
        
        Returns:
            dict: Resultado de validación
        """
        if self.df is None:
            return {"valid": False, "message": "No hay datos cargados"}
        
        # Verificar columnas críticas
        columnas_faltantes = [
            col for col in ["CUIL"] + self.nuevas_columnas 
            if col not in self.df.columns
        ]
        
        if columnas_faltantes:
            return {
                "valid": False,
                "message": f"Columnas faltantes: {', '.join(columnas_faltantes)}"
            }
        
        # Verificar datos básicos
        cuils_vacios = self.df["CUIL"].isna().sum() + (self.df["CUIL"] == "").sum()
        
        return {
            "valid": True,
            "message": "Estructura válida",
            "warnings": [
                f"CUILs vacíos: {cuils_vacios}"
            ] if cuils_vacios > 0 else []
        }
    
def crear_excel_manager(archivo_path: str) -> ExcelManager:
    """
    Crea y configura un ExcelManager
    
    Args:
        archivo_path: Ruta al archivo Excel
        
    Returns:
        ExcelManager: Instancia configurada
    """
    return ExcelManager(archivo_path)