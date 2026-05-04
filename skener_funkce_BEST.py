import cv2
import numpy as np
import trimesh
import glob
import os

# --- KONFIGURACE ---
IMAGE_DIR = "images"
 
FIXED_CENTER_X = 1640
FIXED_CENTER_Y = 1232

def extract_red_points(image_path):
    img = cv2.imread(image_path)
    if img is None: return []
    
    cx = FIXED_CENTER_X
    cy = FIXED_CENTER_Y
    
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Maskování červené barvy
    lower_red1 = np.array([0, 150, 50])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([170, 150, 50])
    upper_red2 = np.array([180, 255, 255])
    mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    
    # Vyčištění šumu (morfologické operace)
    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    points = []
    for cnt in contours:
        M = cv2.moments(cnt)
        if M["m00"] > 10: # Práh pro potlačení drobného šumu
            points.append((int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]), cx, cy))
    return points

def get_3d_points(file_pattern, camera_distance, pixel_scale, offset_x=0.0):
    files = sorted(glob.glob(os.path.join(IMAGE_DIR, file_pattern)))
    all_pts = []
    
    for i, file_path in enumerate(files):
        points_data = extract_red_points(file_path)
        angle = (i / len(files)) * 2 * np.pi
        
        for x, y, cx, cy in points_data:
            # Výpočet relativních souřadnic
            dx = (x - cx) * pixel_scale
            dy = (y - cy) * pixel_scale
            
            # Z je ovlivněno vzdáleností kamery
            z = camera_distance - dy
            radius = dx
            
            all_pts.append([
                radius * np.cos(angle) + offset_x, 
                radius * np.sin(angle), 
                z
            ])
    return np.array(all_pts)

# --- HLAVNÍ LOGIKA ---
# Zde ladíte parametry pro každý model:
# camera_distance: určuje základní hloubku (Z)
# pixel_scale: určuje, jak moc se pixely promítnou do velikosti modelu
points_B = get_3d_points("*B.jpg", camera_distance=10.0, pixel_scale=0.05, offset_x=0.0)
points_T = get_3d_points("*T.jpg", camera_distance=25.0, pixel_scale=0.05, offset_x=2.0)

if len(points_B) > 0 and len(points_T) > 0:
    mesh_B = trimesh.points.PointCloud(points_B).convex_hull
    mesh_T = trimesh.points.PointCloud(points_T).convex_hull
    
    mesh_B.export("model_B.stl")
    mesh_T.export("model_T.stl")

    try:
        difference = mesh_B.difference(mesh_T)
        difference.export("rozdil_modelu.stl")
        print("Rozdíl (B - T) exportován.")
    except Exception as e:
        print(f"Chyba při operaci rozdílu: {e}")
else:
    print("Nedostatek dat pro zpracování.")