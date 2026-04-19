import os
import glob
import time
import threading
from datetime import datetime

import cv2
import numpy as np
from stl import mesh
from flask import Flask, jsonify

# ==========================================
# --- KONFIGURACE ---
# ==========================================
INPUT_DIR = "SampleInput"
OUTPUT_DIR = "SampleOutput"
MAX_SCANS_COUNT = 5   

TOP_MARGIN = 150         
REFLECTION_OFFSET = 230  
LEFT_MARGIN = 5          # Zmenšeno, aby to neřezalo rohy krychle!

LASER_THRESHOLD = 40     # Vráceno na rozumnou hodnotu proti šumu
DEBUG_MODE = True
DEBUG_DIR = "debug_frames"

# ==========================================
# --- ZÁSADNÍ OPRAVA: STŘED OTÁČENÍ ---
# ==========================================
# Žlutá čára musí být PŘESNĚ ve středu zelené kulaté podložky.
# Zadej záporné číslo (např. -50, -120) pro posun žluté čáry DOLEVA.
# Zadej kladné číslo (např. 50) pro posun DOPRAVA.
CENTER_OFFSET = 0  

# Měřítko výsledného STL modelu (kdyby byl moc velký/malý)
SCALE_FACTOR = 1.0  

# ==========================================
# --- GLOBÁLNÍ STAV ---
# ==========================================
state = {
    "name": "Skener",
    "scan_state": "neskenuje",
    "scan_dir": OUTPUT_DIR,
    "scan_process": {"pos": 0, "end": 100}
}

scan_thread = None
stop_event = threading.Event()

def manage_directory_space():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        return
    files = glob.glob(os.path.join(OUTPUT_DIR, "*.stl"))
    files.sort(key=os.path.getmtime)
    while len(files) >= MAX_SCANS_COUNT:
        oldest_file = files.pop(0)
        try: os.remove(oldest_file)
        except: pass

def build_3d_model(images):
    num_images = len(images)
    points_grid = []
    
    if DEBUG_MODE:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        for f in glob.glob(os.path.join(DEBUG_DIR, "*.jpg")):
            os.remove(f)
    
    print("Zahajuji skenování s OPRAVENOU OSOU ROTACE...")
    for idx, img_path in enumerate(images):
        while state["scan_state"] == "pozastaveno":
            time.sleep(1)
            if stop_event.is_set(): return None
        if stop_event.is_set(): return None

        img = cv2.imread(img_path)
        if img is None: continue
            
        debug_img = img.copy() if DEBUG_MODE else None

        b, g, r = cv2.split(img)
        # Rozmazání proti jednopixelovému šumu
        laser_mask = cv2.GaussianBlur(r, (7, 7), 0)

        height, width = laser_mask.shape
        
        # --- APLIKACE POSUNU OSY ---
        true_center_x = int((width // 2) + CENTER_OFFSET)
        
        angle = (idx / num_images) * 2 * np.pi
        profile_3d = []
        
        safe_height = height - REFLECTION_OFFSET 
        
        if DEBUG_MODE:
            cv2.line(debug_img, (0, safe_height), (width, safe_height), (255, 0, 0), 2) 
            cv2.line(debug_img, (true_center_x, 0), (true_center_x, height), (0, 255, 255), 2)  # ŽLUTÁ ČÁRA - OPRAVENÝ STŘED  
            cv2.line(debug_img, (LEFT_MARGIN, 0), (LEFT_MARGIN, height), (255, 0, 255), 1) 
            cv2.line(debug_img, (0, TOP_MARGIN), (width, TOP_MARGIN), (0, 165, 255), 2)    
        
        for y in range(TOP_MARGIN, safe_height, 5): 
            # Hledáme od kraje až po náš nový střed
            row = laser_mask[y, LEFT_MARGIN:true_center_x]
            
            if len(row) > 0:
                max_intensity = np.max(row)
                
                if max_intensity > LASER_THRESHOLD:
                    max_x_local = np.argmax(row)
                    max_x = max_x_local + LEFT_MARGIN
                    
                    # Ochrana proti zdi na okraji
                    if max_x_local < 3:
                        profile_3d.append([0, 0, safe_height - y])
                        continue
                        
                    start_x = max(LEFT_MARGIN, max_x - 15)
                    end_x = min(true_center_x, max_x + 15)
                    
                    local_region = laser_mask[y, start_x:end_x]
                    local_brights = np.where(local_region > LASER_THRESHOLD)[0]
                    
                    if len(local_brights) >= 1:
                        x_mean = int(start_x + np.mean(local_brights))
                        
                        # --- JEDNODUCHÁ A SPRÁVNÁ MATIKA S NOVÝM STŘEDEM ---
                        dx = true_center_x - x_mean  
                        radius = dx * SCALE_FACTOR
                        
                        # Absolutní gilotina proti šumu (s poloměrem přes celý obraz)
                        if radius > width:
                            profile_3d.append([0, 0, safe_height - y])
                            continue
                        
                        X = radius * np.cos(angle)
                        Y = radius * np.sin(angle)
                        Z = safe_height - y 
                        # ---------------------------------------------------
                        
                        profile_3d.append([X, Y, Z])
                        
                        if DEBUG_MODE:
                            cv2.circle(debug_img, (x_mean, y), 2, (0, 255, 0), -1)
                    else:
                        profile_3d.append([0, 0, safe_height - y])
                else:
                    profile_3d.append([0, 0, safe_height - y])
            else:
                profile_3d.append([0, 0, safe_height - y])
                
        if DEBUG_MODE:
            debug_filename = os.path.join(DEBUG_DIR, f"debug_{idx:03d}.jpg")
            cv2.imwrite(debug_filename, debug_img)

        points_grid.append(profile_3d)
        state["scan_process"]["pos"] = idx + 1
        
    print("Sestavuji 3D mesh a ukládám do STL...")
    vertices = []
    for i in range(len(points_grid)):
        next_i = (i + 1) % len(points_grid)
        for j in range(len(points_grid[i]) - 1):
            p1 = points_grid[i][j]
            p2 = points_grid[next_i][j]
            p3 = points_grid[i][j+1]
            p4 = points_grid[next_i][j+1]
            
            vertices.append([p1, p2, p3])
            vertices.append([p3, p2, p4])
            
    np_vertices = np.array(vertices)
    stl_mesh = mesh.Mesh(np.zeros(np_vertices.shape[0], dtype=mesh.Mesh.dtype))
    for i, f in enumerate(vertices):
        for j in range(3):
            stl_mesh.vectors[i][j] = np_vertices[i][j]
            
    return stl_mesh

def scan_worker():
    global state
    state["scan_state"] = "skenuje"
    stop_event.clear()
    
    images = sorted(glob.glob(os.path.join(INPUT_DIR, "*.jpg")) + glob.glob(os.path.join(INPUT_DIR, "*.png")))
    if not images:
        print(f"CHYBA: Složka {INPUT_DIR} je prázdná nebo neexistuje!")
        state["scan_state"] = "chyba"
        return
        
    state["scan_process"]["end"] = len(images)
    state["scan_process"]["pos"] = 0
    
    stl_model = build_3d_model(images)
    
    if stop_event.is_set():
        state["scan_state"] = "neskenuje"
        return
        
    if stl_model is not None:
        manage_directory_space()
        timestamp = datetime.now().strftime("%d-%m-%Y-%H-%M")
        filename = f"model-{timestamp}.stl"
        filepath = os.path.join(OUTPUT_DIR, filename)
        stl_model.save(filepath)
        print(f"HOTOVO! Model uložen do: {filepath}")
        state["scan_state"] = "hotovo"
    else:
        state["scan_state"] = "chyba"

app_controls = Flask("Controls")
@app_controls.route('/start')
def start_scan():
    global scan_thread
    if state["scan_state"] in ["neskenuje", "hotovo", "chyba"]:
        scan_thread = threading.Thread(target=scan_worker)
        scan_thread.start()
        return "Skenování spuštěno", 200
    return "Skenování už běží nebo je pauznuté.", 400

@app_controls.route('/kill')
def kill_scan():
    stop_event.set()
    state["scan_state"] = "neskenuje"
    return "Skenování zrušeno", 200

app_state = Flask("State")
@app_state.route('/state')
def get_state():
    return jsonify(state)

if __name__ == '__main__':
    threading.Thread(target=lambda: app_state.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)).start()
    app_controls.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)