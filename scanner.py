import cv2
import numpy as np
import os
import glob
import math

# ==========================================
# --- KONFIGURACE ---
# ==========================================
INPUT_DIR = "SampleInput"
DEBUG_DIR = "debug_frames"

# --- KALIBRACE ---
# CENTER_X je osa otáčení. Podle tvého obrázku ji zkusíme posunout na střed stolu.
CENTER_X = 550.0        
TRIANGULATION_FACTOR = 1.8 

# --- ROI (Region of Interest) ---
# TADY JE ZMĚNA: Posouváme okno na PRAVOU stranu kostky (kde je ten jasný pruh).
# Modré čáry v debugu se posunou doprava.
SEARCH_LEFT = 700       
SEARCH_RIGHT = 1150     

# --- FILTR POZADÍ ---
# Všechno nalevo od pixelu 500 úplně vymažeme, aby to nechytalo ten laser v pozadí.
IGNORE_LEFT_SIDE = 600 

# --- OKRAJE A CITLIVOST ---
TOP_MARGIN = 80         
BOTTOM_MARGIN = 180     
MIN_BRIGHTNESS = 25     # Citlivost na "rozmazaný" laser na povrchu kostky

# ==========================================
# --- JÁDRO ---
# ==========================================

def get_3d_point(x_pixel, y_pixel, angle_rad, img_height):
    """ Výpočet vzdálenosti od středu. """
    # dx je horizontální vzdálenost od osy otáčení
    dx = abs(CENTER_X - x_pixel)
    R = dx * TRIANGULATION_FACTOR
    
    # Převod na souřadnice pro 3D model
    x = R * math.cos(angle_rad)
    y = R * math.sin(angle_rad)
    z = img_height - y_pixel
    return x, y, z

def run_scanner():
    if not os.path.exists(DEBUG_DIR): os.makedirs(DEBUG_DIR)
    images = sorted(glob.glob(os.path.join(INPUT_DIR, "*.jpg")) + glob.glob(os.path.join(INPUT_DIR, "*.png")))
    
    if not images:
        print("CHYBA: Složka SampleInput je prázdná!")
        return

    num_images = len(images)
    point_cloud = []

    for idx, img_path in enumerate(images):
        img = cv2.imread(img_path)
        if img is None: continue
        
        h, w, _ = img.shape
        # Vezmeme červený kanál pro nejlepší viditelnost laseru
        laser_raw = img[:, :, 2].copy()
        
        # --- AGRESIVNÍ ČIŠTĚNÍ POZADÍ ---
        # Vše vlevo od kostky prostě "zhasneme"
        laser_raw[:, 0:IGNORE_LEFT_SIDE] = 0

        # Prahování pro odstranění šumu a slabých odlesků
        _, thresh = cv2.threshold(laser_raw, MIN_BRIGHTNESS, 255, cv2.THRESH_TOZERO)
        debug_viz = img.copy()

        # Vykreslení modrých čar (kde software hledá) a žluté (střed)
        cv2.line(debug_viz, (SEARCH_LEFT, 0), (SEARCH_LEFT, h), (255, 0, 0), 2)
        cv2.line(debug_viz, (SEARCH_RIGHT, 0), (SEARCH_RIGHT, h), (255, 0, 0), 2)
        cv2.line(debug_viz, (int(CENTER_X), 0), (int(CENTER_X), h), (0, 255, 255), 1)

        # Úhel natočení objektu na podstavě
        angle = (idx / num_images) * 2 * np.pi
        
        for y in range(TOP_MARGIN, h - BOTTOM_MARGIN):
            row_roi = thresh[y, SEARCH_LEFT:SEARCH_RIGHT]
            row_sum = np.sum(row_roi)
            
            if row_sum > 50: 
                # Výpočet těžiště jasu (Centroid) pro maximální přesnost
                weights = row_roi.astype(float)
                positions = np.arange(len(row_roi))
                
                rel_x = np.sum(positions * weights) / row_sum
                abs_x = rel_x + SEARCH_LEFT
                
                # Uložení 3D bodu
                p3d = get_3d_point(abs_x, y, angle, h)
                point_cloud.append(p3d)
                
                # Zelená tečka značí úspěšnou detekci
                cv2.circle(debug_viz, (int(abs_x), y), 1, (0, 255, 0), -1)

        cv2.imwrite(os.path.join(DEBUG_DIR, f"debug_{os.path.basename(img_path)}"), debug_viz)
        if idx % 10 == 0: print(f"Zpracováno {idx}/{num_images} snímků...")

    export_obj(point_cloud, "krychle_cloud.obj")
    print("\nHOTOVO! Otevři 'krychle_cloud.obj' v MeshLabu nebo Blenderu.")

def export_obj(points, filename):
    with open(filename, 'w') as f:
        f.write("# 3D Point Cloud\n")
        for p in points: f.write(f"v {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")

if __name__ == "__main__":
    run_scanner()