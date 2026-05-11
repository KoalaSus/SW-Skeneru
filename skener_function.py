import cv2
import numpy as np
import trimesh
import glob
import os

# --- 1. KONFIGURACE A PARAMETRY ---
# Souřadnice středu obrazu (3280x2464)
CENTER_X = 1640  
CENTER_Y = 1232  

# Přepočty pixelů na mm podle tvé kalibrace
CAM1_PX_MM = 0.032467532467532  # Side kamera
CAM2_PX_MM = 0.0608766233766234 # Up kamera

# Citlivost hloubky (upraveno dle tvého zadání)
SENSITIVITY_UP = 2.2   
SENSITIVITY_SIDE = 1.5

# Fyzické posuny (offsety)
X_OFFSET_UP = 5.0  # Posun horní kamery od osy v mm    

FINAL_DEST = "static/scans"

def get_laser_center(image_bgr, is_side=True):
    """
    Extrahuje střed laserové linky s vysokou citlivostí na červenou barvu.
    Využívá vážený průměr pro sub-pixelovou přesnost.
    """
    # Separace kanálů a zvýraznění červené složky proti modré a zelené
    b, g, r = cv2.split(image_bgr.astype(np.int16))
    red_boost = np.clip(r - (g + b) // 2, 0, 255).astype(np.uint8)
    
    # Práh nastaven na 100 pro zachycení i slabších odrazů linky
    _, thresh = cv2.threshold(red_boost, 100, 255, cv2.THRESH_TOZERO)
    
    points = []
    if is_side:
        # Analýza řádek po řádku pro boční pohled
        for y in range(0, thresh.shape[0], 4):
            row = thresh[y, :]
            indices = np.where(row > 0)[0]
            if len(indices) > 3:
                weights = row[indices].astype(float)
                center_x = np.sum(indices * weights) / np.sum(weights)
                points.append((center_x, y))
    else:
        # Analýza sloupec po sloupci pro horní pohled
        for x in range(0, thresh.shape[1], 4):
            col = thresh[:, x]
            indices = np.where(col > 0)[0]
            if len(indices) > 3:
                weights = col[indices].astype(float)
                center_y = np.sum(indices * weights) / np.sum(weights)
                points.append((x, center_y))
    return points

def transform_to_3d(points_2d, angle_deg, cam_type):
    """
    Transformuje 2D souřadnice z obrázků do 3D prostoru mm.
    Zahrnuje rotaci objektu a hloubkovou citlivost.
    """
    pts_3d = []
    rad = np.radians(angle_deg)
    cos_a, sin_a = np.cos(rad), np.sin(rad)
    
    for px_a, px_b in points_2d:
        if cam_type == 'side':
            # Výpočet poloměru od osy rotace (X) a výšky (Z)
            dist_x = (px_a - CENTER_X) * CAM1_PX_MM
            radius = dist_x * SENSITIVITY_SIDE
            z = (CENTER_Y - px_b) * CAM1_PX_MM 
            pts_3d.append([radius * cos_a, radius * sin_a, z])
            
        else:
            # Výpočet pozice na ploše (X) a výšky z deformace (Z)
            x_pos = (px_a - CENTER_X) * CAM2_PX_MM + X_OFFSET_UP
            displacement_y = (CENTER_Y - px_b) * CAM2_PX_MM
            z_height = max(0, displacement_y * SENSITIVITY_UP)
            pts_3d.append([x_pos * cos_a, x_pos * sin_a, z_height])
            
    return pts_3d

def run_reconstruction():
    print("🚀 START: Načítání obrázků a analýza laseru...")
    
    cam1_files = sorted(glob.glob("images/cam1*.jpg"))
    cam2_files = sorted(glob.glob("images/cam2*.jpg"))
    
    if not cam1_files or not cam2_files:
        print("❌ CHYBA: Složka 'images' neobsahuje potřebné soubory.")
        return

    all_points_side, all_points_up = [], []

    # Zpracování boční kamery (Side)
    for i, f in enumerate(cam1_files):
        img = cv2.imread(f)
        pts_2d = get_laser_center(img, is_side=True)
        angle = i * (360.0 / len(cam1_files))
        all_points_side.extend(transform_to_3d(pts_2d, angle, 'side'))

    # Zpracování horní kamery (Up)
    for i, f in enumerate(cam2_files):
        img = cv2.imread(f)
        pts_2d = get_laser_center(img, is_side=False)
        angle = i * (360.0 / len(cam2_files))
        all_points_up.extend(transform_to_3d(pts_2d, angle, 'up'))

    print("🛠 SKLÁDÁM: Generování 3D modelů...")
    # Vytvoření samostatných těles
    mesh_side = trimesh.convex.convex_hull(all_points_side)
    mesh_up = trimesh.convex.convex_hull(all_points_up)

    # Zarovnání: Posuneme horní model tak, aby seděl na stejné základně jako boční
    z_min_s = mesh_side.bounds[0][2]
    z_min_u = mesh_up.bounds[0][2]
    mesh_up.apply_translation([0, 0, z_min_s - z_min_u])

    # --- METODA PRŮMĚROVÁNÍ ---
    # Spojíme vrcholy obou meshů do jednoho pole
    combined_vertices = np.vstack([mesh_side.vertices, mesh_up.vertices])
    # Vytvoříme nový obal nad všemi body - to funguje jako geometrický průměr
    average_mesh = trimesh.convex.convex_hull(combined_vertices)

    # Exporty souborů
    mesh_side.export(FINAL_DEST + '/side_final.stl')
    mesh_up.export(FINAL_DEST + '/up_final.stl')
    average_mesh.export(FINAL_DEST + '/average_model.stl')

    try:
        # Pokus o booleovský průnik pro srovnání
        final_intersect = trimesh.boolean.intersection([mesh_up, mesh_side])
        final_intersect.export(FINAL_DEST + '/final_intersection.stl')
        print("✅ HOTOVO: Modely uloženy (včetně average_model.stl)")
    except Exception as e:
        print(f"⚠️ PRŮNIK SELHAL: {e}. Použij 'average_model.stl' nebo 'final_combined.stl'.")
        combined = trimesh.util.concatenate([mesh_side, mesh_up])
        combined.export(FINAL_DEST + '/final_combined.stl')

if __name__ == "__main__":
    run_reconstruction()