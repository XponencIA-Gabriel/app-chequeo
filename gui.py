#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import queue
import time
import os
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

from business_engine import BusinessEngine
from excel_manager import ExcelManager

class VerificadorGUI:
    """GUI Principal"""
    def __init__(self, root):
        self.root = root
        self.root.title("Chequeo CUIL - Arquitectura Refactorizada")
        self.root.geometry("1000x800")
        self.root.configure(bg="#f0f0f0")
        self.root.resizable(True, True)
        
        #BUSINESS ENGINE - Reemplaza ProcessingEngine
        self.business_engine = BusinessEngine(callback_gui=self.callback_gui)
        self.excel_manager = None  # Se crea al cargar archivo
        
        # Variables de interfaz (mantener como antes)
        self.archivo_excel = tk.StringVar()
        self.workers_sss = tk.IntVar(value=6)
        self.workers_nopecha = tk.IntVar(value=6)
        self.workers_gemini = tk.IntVar(value=4)
        
        # Variables para progreso y estadísticas 
        self.progress_var = tk.DoubleVar()

        self.auto_continuar_gemini = tk.BooleanVar(value=True)

        # Estado GUI (simplificado - BusinessEngine maneja el estado real)
        self.proceso_activo = False
        self.estadisticas_actuales = {}
        
        # Thread de procesamiento
        self.thread_procesamiento = None
        
        # Queue para mensajes de BusinessEngine
        self.gui_queue = queue.Queue()
        
        # Interfaz
        self.configurar_estilos_modernos()
        self.crear_interfaz()
        
        self.cargar_configuracion_inicial()

        # Iniciar loop de mensajes
        self.procesar_mensajes_queue()

    def cargar_configuracion_inicial(self):
        """
        Inicializa BusinessEngine temprano para verificar APIs
        """
        try:
            from dotenv import load_dotenv
            import os
            load_dotenv() 
            nopecha_key = os.getenv('NOPECHA_API_KEY', '')
            gemini_keys = []
            
            # Buscar keys de Gemini (GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.)
            i = 1
            while True:
                key = os.getenv(f'GEMINI_API_KEY{i}', '')
                if key:
                    gemini_keys.append(key)
                    i += 1
                else:
                    break

            if not hasattr(self.business_engine, 'captcha_solver') or self.business_engine.captcha_solver is None:
                from captcha_solver import CaptchaSolver
                self.business_engine.captcha_solver = CaptchaSolver()
                self.log_mensaje("🔧 CaptchaSolver inicializado", "INFO")

            stats = self.business_engine.captcha_solver.obtener_estadisticas()

            self.actualizar_status_apis()  
            self.log_mensaje("⚙️ Configuración inicial cargada", "INFO")
            
        except Exception as e:
            self.log_mensaje(f"⚠️ Error en configuración inicial: {str(e)}", "WARNING")
            self.log_mensaje("🔄 Continuando con configuración básica", "INFO")

    def configurar_estilos_modernos(self):
        """Configura estilos modernos para toda la aplicación"""
        style = ttk.Style()
        style.theme_use('clam')

        # Fuentes modernas
        fuentes_modernas = ['Segoe UI', 'San Francisco', 'Roboto', 'Inter', 'Arial']
        fuente_elegida = 'Segoe UI'  # Default

        # Intentar encontrar una fuente disponible
        for fuente in fuentes_modernas:
            try:
                test_font = (fuente, 10)
                self.root.option_add('*Font', test_font)
                fuente_elegida = fuente
                break
            except:
                continue

        # Definir tamaños de fuente
        self.fuente_normal = (fuente_elegida, 9)
        self.fuente_titulo = (fuente_elegida, 11, 'bold')
        self.fuente_grande = (fuente_elegida, 10)
        self.fuente_boton = (fuente_elegida, 10, 'bold')

        # Colores modernos
        self.color_primario = '#2196F3'  # Azul moderno
        self.color_secundario = '#4CAF50'  # Verde
        self.color_peligro = '#F44336'  # Rojo
        self.color_advertencia = '#FF9800'  # Naranja
        self.color_fondo = '#FFFFFF'  # Blanco
        self.color_fondo_hover = '#E3F2FD'  # Azul claro

        # Configurar estilos base

        style.configure('TLabel', font=self.fuente_normal, background='#f0f0f0')
        style.configure('TButton', font=self.fuente_grande, padding=(10, 8))
        style.configure('TEntry', font=self.fuente_normal, padding=8)
        style.configure('TFrame', background='#f0f0f0')
        style.configure('TLabelFrame', background='#f0f0f0', padding=10)
        style.configure('TLabelFrame.Label', font=(self.fuente_titulo[0], 11, 'bold'), background='#f0f0f0')
        style.configure('TNotebook.Tab', font=(fuente_elegida, 9, 'bold'), padding=(10, 5))

        # Estilo para títulos
        style.configure('Heading.TLabel', font=self.fuente_titulo, background='#f0f0f0')

        # Estilos para botones modernos
        style.configure('Primary.TButton',
            font=self.fuente_boton,
            background=self.color_primario,
            foreground='white',
            borderwidth=0,
            focuscolor='none',
            padding=(20, 12))

        style.map('Primary.TButton',
            background=[('active', '#1976D2'), ('disabled', '#CCCCCC')],
            foreground=[('disabled', '#888888')])

        style.configure('Success.TButton',
            font=self.fuente_boton,
            background=self.color_secundario,
            foreground='white',
            borderwidth=0,
            focuscolor='none',
            padding=(20, 12))

        style.map('Success.TButton',
            background=[('active', '#388E3C')])

        style.configure('Danger.TButton',
            font=self.fuente_boton,
            background=self.color_peligro,
            foreground='white',
            borderwidth=0,
            focuscolor='none',
            padding=(16, 10))

        style.map('Danger.TButton',
            background=[('active', '#C62828'), ('disabled', '#CCCCCC')],
            foreground=[('disabled', '#888888')])

        # Estilo para barra de progreso
        style.configure("Modern.Horizontal.TProgressbar",
            background=self.color_secundario,
            troughcolor='#E0E0E0',
            borderwidth=0,
            thickness=25)

        # Estilo para Spinbox
        style.configure('TSpinbox', 
            font=self.fuente_normal,
            arrowsize=15,
            padding=5)

    def callback_gui(self, mensaje):
        """
        Callback que recibe mensajes del BusinessEngine
        Reemplaza la comunicación via queue con ProcessingEngine
        """
        self.gui_queue.put(mensaje)

    def crear_interfaz(self):
        # Crear Canvas con scrollbar
        canvas = tk.Canvas(self.root, bg='#f0f0f0', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        
        # Frame principal scrolleable
        main_frame = ttk.Frame(canvas)
        
        # Configurar scroll
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Empaquetar canvas y scrollbar
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Crear ventana en el canvas
        canvas_window = canvas.create_window((0, 0), window=main_frame, anchor="nw")
        
        # Función para actualizar el scrollregion
        def actualizar_scroll(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # Ajustar ancho del frame al canvas
            canvas_width = canvas.winfo_width()
            canvas.itemconfig(canvas_window, width=canvas_width)
        
        main_frame.bind("<Configure>", actualizar_scroll)
        canvas.bind("<Configure>", actualizar_scroll)
            
            # Soporte de scroll con rueda del mouse
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
            
        # 1. HEADER
        self.crear_header(main_frame)
        
        # 2. SELECCIÓN DE ARCHIVO
        self.crear_seccion_archivo(main_frame)
        
        # 3. CONTROLES PRINCIPALES - MUY VISIBLES
        self.crear_controles_principales(main_frame)
        
        # 4. CONFIGURACIÓN (en pestañas para ahorrar espacio)
        self.crear_configuracion_compacta(main_frame)
        
        # 5. PROGRESO EN TIEMPO REAL
        self.crear_seccion_progreso(main_frame)
        
        # 6. LOG DE ACTIVIDAD
        self.crear_seccion_log(main_frame)

    def crear_header(self, parent):

        """Crea el header de la aplicación"""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, pady=(0, 15))

        title_label = ttk.Label(header_frame, 
            text="VERIFICARDOR CUILS - O.S",
            font=(self.fuente_titulo[0], 16, 'bold'),
            style="Heading.TLabel")
        title_label.pack(side=tk.LEFT)

        version_label = ttk.Label(header_frame, 
            text="Automatización",
            font=self.fuente_normal,
            foreground="gray")
        version_label.pack(side=tk.RIGHT)

    def crear_seccion_archivo(self, parent):

        """Crea la sección de selección de archivo"""
        frame = ttk.LabelFrame(parent, text="  📁  Archivo de Trabajo", padding=15)
        frame.pack(fill=tk.X, pady=(0, 15))

        # Selección de archivo
        file_frame = ttk.Frame(frame)
        file_frame.pack(fill=tk.X, pady=(0, 10))

        self.archivo_entry = ttk.Entry(file_frame, textvariable=self.archivo_excel)
        self.archivo_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(file_frame, 
            text="  📂  Examinar",
            command=self.seleccionar_archivo,
            style='TButton').pack(side=tk.RIGHT, padx=(10, 0))

        # Información del archivo
        self.info_archivo = ttk.Label(frame, text="", foreground="gray")
        self.info_archivo.pack(anchor=tk.W)

    def crear_controles_principales(self, parent):
        """Crea los controles principales MUY VISIBLES"""
        frame = ttk.LabelFrame(parent, text="  🎛️  CONTROLES PRINCIPALES", padding=20)
        frame.pack(fill=tk.X, pady=(0, 15))

        # Frame para centrar botones
        btn_frame = ttk.Frame(frame)
        btn_frame.pack()

        # Solo dos botones: INICIAR y DETENER con iconos y texto alineados
        self.btn_iniciar = ttk.Button(btn_frame, 
            text="  ▶  INICIAR VERIFICACIÓN  ",
            command=self.iniciar_procesamiento,
            style='Primary.TButton',
            width=30)

        self.btn_iniciar.pack(side=tk.LEFT, padx=10, pady=10)

        self.btn_detener = ttk.Button(btn_frame, 
            text="  ⏹  DETENER  ",
            command=self.detener_procesamiento,
            state=tk.DISABLED,
            style='Danger.TButton',
            width=18)
        self.btn_detener.pack(side=tk.LEFT, padx=10, pady=10)

        # Estado del sistema con mejor alineación
        estado_frame = ttk.Frame(frame)
        estado_frame.pack(pady=15)

        self.estado_sistema = ttk.Label(estado_frame, 
            text="  🟢  SISTEMA LISTO  ",
            font=(self.fuente_titulo[0], 11, 'bold'),
            foreground='green')
        self.estado_sistema.pack()

        # Controles secundarios con mejor alineación
        secundarios_frame = ttk.Frame(frame)
        secundarios_frame.pack(pady=(10, 0))

        ttk.Button(secundarios_frame, 
            text="  🔄  Recargar  ",
            command=self.actualizar_info_archivo, 
            width=16).pack(side=tk.LEFT, padx=5)

        ttk.Button(secundarios_frame, 
            text="  📄  Excel  ",
            command=self.abrir_excel, 
            width=16).pack(side=tk.LEFT, padx=5)

    def crear_configuracion_compacta(self, parent):

        """Crea configuración compacta en pestañas"""
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.X, pady=(0, 15))

        # Pestaña APIs
        api_frame = ttk.Frame(notebook)
        notebook.add(api_frame, text="  🔑  APIs  ")

        # Status APIs en una fila con mejor alineación
        status_frame = ttk.Frame(api_frame)
        status_frame.pack(fill=tk.X, padx=10, pady=10)

        # Nopecha
        nopecha_frame = ttk.LabelFrame(status_frame, text="  🤖  Servicios de captcha  ", padding=10)
        nopecha_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.nopecha_status = ttk.Label(nopecha_frame, 
            text="⏳ Cargando...",
            font=self.fuente_normal)
        self.nopecha_status.pack(pady=5)

        ttk.Label(nopecha_frame, text="Procesos:", font=self.fuente_normal).pack()
        ttk.Spinbox(nopecha_frame, from_=1, to=10, width=12,
            textvariable=self.workers_nopecha,
            font=self.fuente_normal).pack(pady=5)

        # Gemini
        gemini_frame = ttk.LabelFrame(status_frame, text="  🧠  Gemini  ", padding=10)
        gemini_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        self.gemini_status = ttk.Label(gemini_frame, 
            text="⏳ Cargando...",
            font=self.fuente_normal)
        self.gemini_status.pack(pady=5)

        ttk.Label(gemini_frame, text="Procesos:", font=self.fuente_normal).pack()
        ttk.Spinbox(gemini_frame, from_=1, to=6, width=12,
            textvariable=self.workers_gemini,
            font=self.fuente_normal).pack(pady=5)

    def crear_seccion_progreso(self, parent):

        """Crea la sección de progreso"""
        frame = ttk.LabelFrame(parent, text="  📊  Progreso en Tiempo Real  ", padding=15)
        frame.pack(fill=tk.X, pady=(0, 15))

        # Barra de progreso
        progress_frame = ttk.Frame(frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame,
            variable=self.progress_var,
            maximum=100,
            style="Modern.Horizontal.TProgressbar",
            length=400)

        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_label = ttk.Label(progress_frame, 
            text="0%", 
            width=8,
            font=self.fuente_grande)
        self.progress_label.pack(side=tk.RIGHT, padx=(10, 0))

        # Estadísticas en 2 filas con mejor alineación
        stats_frame1 = ttk.Frame(frame)
        stats_frame1.pack(fill=tk.X, pady=(0, 5))

        self.label_registros = ttk.Label(stats_frame1, 
            text="  📋  Registros: 0/0  ",
            font=self.fuente_normal)

        self.label_registros.pack(side=tk.LEFT)
        self.label_proveedor = ttk.Label(stats_frame1, 
            text="",
            font=self.fuente_normal)
        self.label_proveedor.pack(side=tk.RIGHT)

        stats_frame2 = ttk.Frame(frame)
        stats_frame2.pack(fill=tk.X)

        self.label_consultas = ttk.Label(stats_frame2, 
            text="  🤖  Nopecha: 0  |  🧠  Gemini: 0  ",
            font=self.fuente_normal)
        self.label_consultas.pack(side=tk.LEFT)
        self.label_tiempo = ttk.Label(stats_frame2, 
            text="  ⏱️  00:00:00  ",
            font=self.fuente_normal)
        self.label_tiempo.pack(side=tk.RIGHT)

    def crear_seccion_log(self, parent):
        """Crea la sección de log compacta"""
        frame = ttk.LabelFrame(parent, text="  📝  Log de Actividad  ", padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(frame, 
            height=8, 
            wrap=tk.WORD,
            font=self.fuente_normal)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Configurar tags para colores
        self.log_text.tag_configure("INFO", foreground="#2196F3")
        self.log_text.tag_configure("SUCCESS", foreground="#4CAF50")
        self.log_text.tag_configure("WARNING", foreground="#FF9800")
        self.log_text.tag_configure("ERROR", foreground="#F44336")

        # Mensaje inicial
        self.log_mensaje("🚀 Sistema iniciado correctamente", "SUCCESS")
        self.log_mensaje("📋 Seleccione un archivo Excel para comenzar", "INFO")

    def centrar_ventana(self):
        """Centra la ventana en la pantalla"""
        self.root.update_idletasks()

        width = self.root.winfo_width()
        height = self.root.winfo_height()

        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)

        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def seleccionar_archivo(self):
        """Abre diálogo para seleccionar archivo Excel"""
        filename = filedialog.askopenfilename(
            title="Seleccionar archivo Excel",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )

        if filename:
            self.archivo_excel.set(filename)
            self.actualizar_info_archivo()

    def actualizar_progreso(self):
        """Actualiza barra de progreso y estadísticas"""
        try:
            stats = self.business_engine.obtener_estadisticas()
            
            if stats.get("total_registros", 0) > 0:
                progreso = (stats.get("registros_procesados", 0) / stats.get("total_registros", 1)) * 100
                self.progress_var.set(progreso)
                self.progress_label.config(text=f"{progreso:.1f}%")
            
            # Actualizar tiempo transcurrido
            if stats.get("tiempo_inicio"):
                elapsed = time.time() - stats["tiempo_inicio"]
                tiempo_str = str(timedelta(seconds=int(elapsed)))
                self.label_tiempo.config(text=f"Tiempo: {tiempo_str}")
        
        except Exception as e:
            print(f"⚠️ Error actualizando progreso: {e}")

    def actualizar_info_archivo(self):
        """
        Actualizar información del archivo usando ExcelManager
        """
        archivo = self.archivo_excel.get()
        if archivo and os.path.exists(archivo):
            try:
                # USAR BUSINESS ENGINE para estadísticas
                if hasattr(self.business_engine, 'excel_manager') and self.business_engine.excel_manager:
                    stats = self.business_engine.excel_manager.obtener_estadisticas()
                    total = stats.get("total_registros", 0)
                    procesados = stats.get("registros_procesados", 0)
                    pendientes = stats.get("registros_pendientes", 0)
                    
                    info = f"Total: {total} | Procesados: {procesados} | Pendientes: {pendientes}"
                    self.info_archivo.config(text=info)
                else:
                    # Fallback - leer directamente
                    import pandas as pd
                    df = pd.read_excel(archivo, dtype={"CUIL": str})
                    total = len(df)
                    procesados = len(df[df.get("Estado Chequeo", "").fillna("") != ""])
                    pendientes = total - procesados
                    
                    info = f"Total: {total} | Procesados: {procesados} | Pendientes: {pendientes}"
                    self.info_archivo.config(text=info)
                    
            except Exception as e:
                self.info_archivo.config(text=f"Error: {str(e)}")
        else:
            self.info_archivo.config(text="")

    def log_mensaje(self, mensaje, tipo="INFO"):
        """Añade mensaje al log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        mensaje_completo = f"[{timestamp}]  {mensaje}\n"

        self.log_text.insert(tk.END, mensaje_completo, tipo)
        self.log_text.see(tk.END)

    def iniciar_procesamiento(self):
        """
        Inicia procesamiento usando BusinessEngine
        """
        if not self.archivo_excel.get():
            messagebox.showerror("Error", "Debe seleccionar un archivo Excel")
            return
        
        if not os.path.exists(self.archivo_excel.get()):
            messagebox.showerror("Error", "El archivo seleccionado no existe")
            return
        
        # Validar que no hay proceso activo
        if self.proceso_activo:
            messagebox.showwarning("Advertencia", "Ya hay un proceso en ejecución")
            return

        workers_inicial = self.calcular_workers_inicial()

        if workers_inicial == 0:
            self.log_mensaje("🚫 CANCELANDO: Todas las APIs están agotadas", "ERROR")
            messagebox.showerror(
                "APIs Agotadas", 
                "Todas las APIs de CAPTCHA están agotadas.\n\n" +
                "Recarga crédito en algún servicio de captcha o espera que se renueven las keys de Gemini."
            )
            self.btn_iniciar.config(state=tk.NORMAL)
            self.btn_detener.config(state=tk.DISABLED)
            self.estado_sistema.config(text="DETENIDO - SIN APIs", foreground="red")
            return
        
        # Actualizar UI
        self.log_mensaje(f"🔧 Workers iniciales calculados: {workers_inicial}", "INFO")
        self.btn_iniciar.config(state=tk.DISABLED)
        self.btn_detener.config(state=tk.NORMAL)
        self.estado_sistema.config(text="CARGANDO...", foreground="orange")
        self.log_mensaje("INICIANDO procesamiento...", "INFO")
        
        def ejecutar_procesamiento():
            try:
                # Cargar archivo
                self.log_mensaje("📁 Cargando archivo Excel...", "INFO")
                resultado_carga = self.business_engine.cargar_archivo(self.archivo_excel.get())
                        
                if not resultado_carga["success"]:
                    print(f"❌ ERROR CARGA: {resultado_carga}")
                    self.callback_gui({
                        "tipo": "error",
                        "mensaje": resultado_carga.get("message", f"Error cargando: {resultado_carga}")
                    })
                    return

                self.log_mensaje(resultado_carga.get("message", "Archivo cargado"), "INFO")

                # Iniciar procesamiento
                self.log_mensaje(f"🚀 Iniciando procesamiento con {workers_inicial} workers", "INFO")
                resultado = self.business_engine.iniciar_procesamiento(workers_inicial)
                
                if resultado["success"]:
                    self.callback_gui({
                        "tipo": "procesamiento_completado",
                        "data": {
                            "procesados": resultado["procesados"],
                            "errores": resultado["errores"],
                            "tiempo": resultado["tiempo_total"]
                        },
                        "mensaje": "Procesamiento completado exitosamente"
                    })
                else:
                    self.callback_gui({
                        "tipo": "error", 
                        "mensaje": resultado["message"]
                    })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.callback_gui({
                    "tipo": "error",
                    "mensaje": f"Error crítico: {str(e)}"
                })
        
        # Ejecutar en thread separado
        self.thread_procesamiento = threading.Thread(
            target=ejecutar_procesamiento, 
            daemon=True
        )
        self.thread_procesamiento.start()

    def calcular_workers_inicial(self):
        """
        Calcula workers iniciales basado en qué API se usará PRIMERO
        Considera el fallback automático pero optimiza para el inicio
        
        Returns:
            int: Número de workers para iniciar (0 si todas las APIs agotadas)
        """
        try:
                # Verificar si BusinessEngine está inicializado
            if (not hasattr(self.business_engine, 'captcha_solver') or 
                self.business_engine.captcha_solver is None):
                
                # ⭐ FORZAR INICIALIZACIÓN TEMPRANA
                self.log_mensaje("🔧 Inicializando CaptchaSolver...", "INFO")
                try:
                    from captcha_solver import CaptchaSolver
                    self.business_engine.captcha_solver = CaptchaSolver()
                except Exception as e:
                    self.log_mensaje(f"❌ Error inicializando CaptchaSolver: {e}", "ERROR")
                    return self.workers_sss.get()  # Fallback
            
            # Obtener estadísticas actuales
            stats = self.business_engine.captcha_solver.obtener_estadisticas()

            # VERIFICAR SERVICIOS PAGOS PRIMERO (NopeCHA, CapSolver, CapMonster, Anti-Captcha, 2Captcha)
            servicio_pago_disponible = stats.get("servicio_pago_disponible", False)

            if servicio_pago_disponible:
                workers = self.workers_nopecha.get()
                orden = " → ".join(stats["proveedores"][p]["nombre"] for p in stats.get("orden", []))
                self.log_mensaje(f"🟢 Iniciando con servicios de captcha: {workers} workers ({orden})", "INFO")
                self.log_mensaje("📋 Gemini quedará como fallback automático", "INFO")
                return max(1, workers)  # ⭐ ASEGURAR MÍNIMO 1
                
            else:
                # ⭐ VERIFICAR GEMINI
                self.log_mensaje("🟡 Ningún servicio pago disponible - verificando Gemini...", "WARNING")
                
                keys_gemini_total = stats.get("total_keys_gemini", 0)
                keys_gemini_agotadas = stats.get("todas_keys_gemini_agotadas", False)
                indice_actual = stats.get("indice_gemini_actual", 0)
                
                if keys_gemini_total > 0 and not keys_gemini_agotadas:
                    workers = self.workers_gemini.get()
                    keys_restantes = keys_gemini_total - indice_actual
                    self.log_mensaje(f"🟡 Iniciando con Gemini: {workers} workers (key {indice_actual+1}/{keys_gemini_total})", "WARNING")
                    return max(1, workers)
                else:
                    # 🔴 TODAS AGOTADAS - RETORNAR 0 PARA CANCELAR
                    self.log_mensaje("🔴 CRÍTICO: Todas las APIs están agotadas", "ERROR")
                    self.log_mensaje(f"🔍 Debug: total_keys={keys_gemini_total}, todas_agotadas={keys_gemini_agotadas}", "ERROR")
                    self.log_mensaje("💡 Recarga cuotas o espera renovación automática", "INFO")
                    return 0
                
        except Exception as e:
            # ❌ Error en verificación - usar fallback seguro
            self.log_mensaje(f"❌ Error verificando APIs: {str(e)}", "ERROR")
            self.log_mensaje("🔄 Usando workers SSS como fallback seguro", "INFO")
            return max(1, self.workers_sss.get()) 

    def detener_procesamiento(self):
        """Detiene el procesamiento usando BusinessEngine"""
        if messagebox.askyesno("Confirmar", 
                              "¿Detener el procesamiento? El progreso se guardará automáticamente."):
            
            self.log_mensaje("Enviando comando DETENER...", "WARNING")
            
            # USAR BUSINESS ENGINE para detener
            self.business_engine.detener_procesamiento()

            self.proceso_activo = False
            
            # Actualizar UI inmediatamente
            self.btn_iniciar.config(state=tk.NORMAL)
            self.btn_detener.config(state=tk.DISABLED)
            self.estado_sistema.config(text="DETENIENDO...", foreground="red")

    def abrir_excel(self):
        """Abre el archivo Excel con resultados (o el original si aún no se generó)"""
        archivo_salida = None
        if self.business_engine and self.business_engine.excel_manager:
            archivo_salida = self.business_engine.excel_manager.archivo_salida

        if archivo_salida and os.path.exists(archivo_salida):
            os.startfile(archivo_salida)
        elif self.archivo_excel.get() and os.path.exists(self.archivo_excel.get()):
            os.startfile(self.archivo_excel.get())
        else:
            messagebox.showwarning("Advertencia", "No hay archivo Excel válido")

    def procesar_mensajes_queue(self):
        """
        Procesa mensajes del BusinessEngine
        Reemplaza ProcessingEngine message handling [attached_file:3]
        """
        mensajes_procesados = 0
        
        try:
            while mensajes_procesados < 50:  # Límite para evitar bloqueos
                mensaje = self.gui_queue.get_nowait()
                self.manejar_mensaje(mensaje)
                mensajes_procesados += 1
        except queue.Empty:
            pass
        
        # Actualizar estadísticas si hay proceso activo
        try:
            self.actualizar_status_apis()
        except Exception as e:
            pass  # Evitar errores en loop principal
    
        # Programar siguiente verificación
        intervalo = 100 if self.proceso_activo else 200
        self.root.after(intervalo, self.procesar_mensajes_queue)

    def manejar_mensaje(self, mensaje):
        """
        Maneja mensajes del BusinessEngine
        """
        tipo = mensaje.get("tipo", "")
        data = mensaje.get("data", {})
        texto = mensaje.get("mensaje", "")
        
        # Mensajes de inicio
        if tipo == "archivo_cargado":
            stats = data.get("stats", {})
            if "total_registros" in stats:
                self.log_mensaje(f"Archivo cargado: {stats['total_registros']} registros", "INFO")
            
            self.actualizar_info_archivo()
        
        elif tipo == "inicio_procesamiento":
            total = data.get("total", 0)
            workers = data.get("workers", 0)
            self.proceso_activo = True
            self.log_mensaje(f"Iniciando con {workers} workers para {total} CUILs pendientes", "INFO")
            self.estado_sistema.config(text="PROCESANDO...", foreground="blue")
        
        # Mensajes de progreso
        elif tipo == "procesando_cuil":
            cuil = data.get("cuil", "DESCONOCIDO")
            # No loggear cada CUIL para evitar spam
        
        elif tipo == "cuil_procesado":
            cuil = data.get("cuil", "DESCONOCIDO") 
            resultado = data.get("resultado", "DESCONOCIDO")
            obra_social = data.get("obra_social", "N/A")
            intento = data.get("intento", 1)
            
            if resultado == "OK":
                self.log_mensaje(f"{cuil}: {obra_social} (intento {intento})", "SUCCESS")
            else:
                self.log_mensaje(f"{cuil}: Sin datos (intento {intento})", "SUCCESS")
        
        # Mensajes de error
        elif tipo == "error_no_guardado":
            cuil = data.get("cuil", "DESCONOCIDO")
            self.log_mensaje(f"{cuil}: Error - NO guardado", "WARNING")
        
        elif tipo == "cuota_agotada":
            self.proceso_activo = False
            proveedor = data.get("proveedor", "DESCONOCIDO")
            self.log_mensaje(f"Cuota de {proveedor} AGOTADA", "ERROR")
            self.estado_sistema.config(text="DETENIDO - SIN CUOTA", foreground="red")
        
        # Mensajes de guardado
        elif tipo == "guardado_periodico":
            registros = data.get("registros", 0)
            self.log_mensaje(f"Guardado: {registros} registros", "INFO")
        
        elif tipo == "guardado_final":
            self.log_mensaje("Guardado final completado", "SUCCESS")
        
        elif tipo == "procesamiento_completado":
            procesados = data.get("procesados", 0)
            errores = data.get("errores", 0)
            tiempo = data.get("tiempo", 0)

            self.proceso_activo = False

            self.log_mensaje("PROCESAMIENTO COMPLETADO", "SUCCESS")
            self.log_mensaje(f"Total procesados: {procesados}", "SUCCESS")
            if errores > 0:
                self.log_mensaje(f"Errores detectados: {errores}", "WARNING")
            if tiempo > 0:
                minutos = tiempo / 60
                velocidad = procesados / minutos if minutos > 0 else 0
                self.log_mensaje(
                    f"Tiempo: {minutos:.1f} min | Velocidad: {velocidad:.1f} registros/min "
                    f"({self.workers_nopecha.get()} proc. servicios pagos / {self.workers_gemini.get()} proc. Gemini)",
                    "INFO"
                )
            
            # Actualizar UI final
            self.btn_iniciar.config(state=tk.NORMAL)
            self.btn_detener.config(state=tk.DISABLED) 
            self.estado_sistema.config(text="COMPLETADO", foreground="green")
        
        # Mensajes generales
        elif tipo == "info":
            self.log_mensaje(texto, "INFO")
        
        elif tipo == "error":
            self.proceso_activo = False
            self.log_mensaje(texto, "ERROR")
            self.btn_iniciar.config(state=tk.NORMAL)
            self.btn_detener.config(state=tk.DISABLED)
            self.estado_sistema.config(text="ERROR", foreground="red")

    def actualizar_status_apis(self):
        """
        Usa BusinessEngine para obtener status
        Actualiza el status de las APIs via CaptchaSolver
        """
        try:
            if (hasattr(self.business_engine, 'captcha_solver') and 
            self.business_engine.captcha_solver is not None):
            
                captcha_stats = self.business_engine.captcha_solver.obtener_estadisticas()
                
                # Status servicios pagos: una línea por servicio configurado, en orden de uso
                lineas = []
                for p in captcha_stats.get("orden", []):
                    if p == "gemini":
                        continue
                    info = captcha_stats["proveedores"][p]
                    estado_p = "🟢" if info["disponible"] else "🔴 sin crédito"
                    lineas.append(f"{info['nombre']} {estado_p}")

                if lineas:
                    self.nopecha_status.config(text="\n".join(lineas))
                else:
                    self.nopecha_status.config(text="❌ Ninguno configurado")

                # Status Gemini
                total_keys_gemini = captcha_stats.get("total_keys_gemini", 0)
                todas_keys_agotadas = captcha_stats.get("todas_keys_gemini_agotadas", False)
                indice_actual = captcha_stats.get("indice_gemini_actual", 0)
                
                if total_keys_gemini > 0:
                    workers_gemini = self.workers_gemini.get()
                    
                    if not todas_keys_agotadas:
                        keys_restantes = total_keys_gemini - indice_actual
                        self.gemini_status.config(
                            text=f"✅ Configurada\n🟢 {keys_restantes}/{total_keys_gemini} keys ({workers_gemini} workers)"
                        )
                    else:
                        self.gemini_status.config(
                            text=f"✅ Configurada\n🔴 Todas agotadas ({total_keys_gemini} keys)"
                        )
                else:
                    self.gemini_status.config(text="❌ No configuradas")
                    
            else:
                # Fallback si no hay business_engine inicializado
                self.nopecha_status.config(text="⚠️ Inicializando...")
                self.gemini_status.config(text="⚠️ Inicializando...")
                
        except Exception as e:
            # Error handling
            self.nopecha_status.config(text="❌ Error")
            self.gemini_status.config(text="❌ Error")
            self.log_mensaje(f"❌ Error actualizando status APIs: {str(e)}", "ERROR")

    def actualizar_estadisticas_interfaz(self):
        """Actualiza las estadísticas en la interfaz"""
        estado = self.estado.obtener_copia()

        # Progreso
        if estado['registros_totales'] > 0:
            progreso = (estado['registros_procesados'] / estado['registros_totales']) * 100
            self.progress_var.set(progreso)
            self.progress_label.config(text=f"{progreso:.1f}%")

        # Estadísticas con mejor formato
        self.label_registros.config(text=f"  📋  {estado['registros_procesados']}/{estado['registros_totales']}  ")
        self.label_consultas.config(text=f"  🤖  {estado['consultas_nopecha']}  |  🧠  {estado['consultas_gemini']}  ")

        # Tiempo
        if estado['tiempo_inicio']:
            elapsed = time.time() - estado['tiempo_inicio']
            tiempo_str = str(timedelta(seconds=int(elapsed)))
            self.label_tiempo.config(text=f"  ⏱️  {tiempo_str}  ")

def main():
    """Función principal"""
    root = tk.Tk()
    app = VerificadorGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
