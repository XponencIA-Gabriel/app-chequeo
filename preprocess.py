import cv2
import numpy as np

def limpiar_imagen(img):
    """
    Limpia el ruido de un CAPTCHA. Recibe y devuelve una imagen en escala de
    grises (array de numpy), sin tocar el disco.
    """
    # --- Paso 1: Binarización ---
    # Se aplica un umbral para obtener una imagen puramente en blanco y negro.
    # Los píxeles más oscuros que 170 se vuelven negros (0), y los más claros, blancos (255).
    # cv2.THRESH_BINARY_INV invierte los colores (texto en blanco sobre fondo negro), lo cual es estándar para el procesamiento de contornos.
    _, binarized_img = cv2.threshold(img, 170, 255, cv2.THRESH_BINARY_INV)

    # --- Paso 2: Eliminación de ruido con Operaciones Morfológicas ---
    # Define el "kernel", que es una pequeña matriz para las operaciones.
    kernel = np.ones((3, 3), np.uint8)

    # Erosión: "adelgaza" las formas. Las líneas finas de ruido desaparecerán.
    eroded_img = cv2.erode(binarized_img, kernel, iterations=1)

    # Dilatación: "engorda" las formas restantes. Esto restaura los caracteres a su tamaño original.
    cleaned_img = cv2.dilate(eroded_img, kernel, iterations=1)

    # --- Invertir la imagen de nuevo ---
    # Vuelve al formato de texto negro sobre fondo blanco para facilitar la lectura.
    return cv2.bitwise_not(cleaned_img)

def edit_image(imagen, img_clean):
    """Versión con archivos: lee 'imagen', la limpia y la guarda en 'img_clean'"""
    img = cv2.imread(imagen, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"Error: No se pudo cargar la imagen '{imagen}'.")
        return
    cv2.imwrite(img_clean, limpiar_imagen(img))
    print(f"La imagen limpia se ha guardado como {img_clean}")
