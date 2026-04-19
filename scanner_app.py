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

LASER_THRESHOLD = 60     # Vyšší próg - chyť jen silný laser, ne šum!
DEBUG_MODE = True
DEBUG_DIR = "debug_frames"

# ==========================================
# --- ZÁSADNÍ OPRAVA: STŘED OTÁČENÍ ---
# ==========================================
# Žlutá čára musí být PŘESNĚ ve středu zelené kulaté podložky.
# Zadej záporné číslo (např. -50, -120) pro posun žluté čáry DOLEVA.
# Zadej kladné číslo (např. 50) pro posun DOPRAVA.
CENTER_OFFSET = 0  

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
    
    print("Zahajuji skenování s JEDNODUCHÝM MODELEM...")
    for idx, img_path in enumerate(images):
        while state["scan_state"] == "pozastaveno":
            time.sleep(1)
            if stop_event.is_set(): return None
        if stop_event.is_set(): return None

        print(f"Skenuji obrázek {idx+1}/{num_images}: {img_path}")
        img = cv2.imread(img_path)
        if img is None: 
            print(f"  CHYBA: Nelze načíst obrázek!")
            continue
            
        debug_img = img.copy() if DEBUG_MODE else None

        b, g, r = cv2.split(img)
        # Rozmazání proti jednopixelovému šumu
        laser_mask = cv2.GaussianBlur(r, (7, 7), 0)

        height, width = laser_mask.shape
        center_x = width // 2
        
        angle = (idx / num_images) * 2 * np.pi
        profile_3d = []
        
        # Najdi spodek - hledej maximum z CELÉHO řádku, který je VLEVO od středu
        bottom_row = 0
        for r in range(height):
            col_max = np.argmax(laser_mask[r, :])
            # DŮLEŽITÉ: Pokud je maximum vlevo od středu (laser točky vlevo!)
            if col_max < center_x and laser_mask[r, col_max] > LASER_THRESHOLD:
                bottom_row = r
        
        # Debug čáry
        if DEBUG_MODE:
            cv2.line(debug_img, (0, bottom_row), (width, bottom_row), (255, 0, 0), 2)
            cv2.line(debug_img, (center_x, 0), (center_x, height), (0, 255, 255), 2)
        
        # --- ALGORITMUS: VEZMI MAXIMUM Z CELÉHO ŘÁDKU, ALE JENOM POKUD JE VLEVO ---
        for y in range(height):
            # Najdi maximum v CELÉM řádku
            col_max = np.argmax(laser_mask[y, :])
            
            # ZÁSADNÍ: Podmínka - maximum musí být vlevo od středu a dostatečně jasné!
            # (Takže ignorujeme pravý laser úplně)
            if col_max < center_x and laser_mask[y, col_max] > LASER_THRESHOLD:
                # Výška = y minus spodek
                H = y - bottom_row
                # Vzdálenost = sloupec minus střed (bude negativní, což je v pořádku!)
                distance = col_max - center_x
                
                # Konvertuj na kartézské
                X = distance * np.cos(angle)
                Y = distance * np.sin(angle)
                Z = H
                
                profile_3d.append([X, Y, Z])
                
                if DEBUG_MODE:
                    cv2.circle(debug_img, (col_max, y), 2, (0, 255, 0), -1)
                
        if DEBUG_MODE:
            debug_filename = os.path.join(DEBUG_DIR, f"debug_{idx:03d}.jpg")
            cv2.imwrite(debug_filename, debug_img)

        points_grid.append(profile_3d)
        print(f"  Profil {idx}: {len(profile_3d)} bodů detekováno")
        state["scan_process"]["pos"] = idx + 1
        
    print("Sestavuji 3D mesh - jen bočni plochy...")
    print(f"Celkem obrázků: {len(points_grid)}")
    print(f"Bodů v jednotlivych profilech: {[len(p) for p in points_grid[:5]]}... (prvních 5)")
    
    # Kontrola - máme vůbec nějaké body?
    total_points = sum(len(p) for p in points_grid)
    print(f"CELKOM BODŮ V SITI: {total_points}")
    
    if total_points == 0:
        print("CHYBA: Nebyli detekováni žádné body! Zkontroluj detekci laseru.")
        return None
    
    # --- ZÁSADNÍ: NORMALIZUJ VŠECHNY PROFILY NA STEJNOU DÉLKU ---
    # (Jak to dělá originální script - jinak se rozbije mesh)
    print("Normalizuji délky profilů...")
    shortest = min(len(profile) for profile in points_grid) if points_grid else 0
    print(f"Nejkratší profil: {shortest} bodů")
    
    # --- VERTICAL RESOLUTION: Sníž počet bodů (jako originální script) ---
    # Máš příliš mnoho bodů na profil (2049), chceme jen ~100-200
    target_points = 100  # Kolik bodů chceme na výšku
    if shortest > target_points:
        step = max(1, shortest // target_points)
        print(f"Snižuji verifikální rozlišení: vezmeme každý {step}. bod")
        for profile in points_grid:
            profile[:] = profile[::step]  # Vezmi jen každý step-tý bod
    
    # Znova normalizuj po snížení rozlišení
    shortest = min(len(profile) for profile in points_grid) if points_grid else 0
    print(f"Po snížení rozlišení: nejkratší profil má {shortest} bodů")
    
    for profile in points_grid:
        while len(profile) > shortest:
            profile.pop(len(profile) - 2)  # Odstraň prostřední bodu, ne poslední
    
    print(f"Profily normalizovány - všechny mají nyní {shortest} bodů")
    vertices_list = []
    
    # JEDNODUŠE: Spojit sousední řezy trojúhelníky (jako běžný 3D scan)
    for i in range(len(points_grid)):
        next_i = (i + 1) % len(points_grid)  # Cyklicky - poslední se napojí na první
        
        # Projdeme všechny body v profilu
        for j in range(len(points_grid[i]) - 1):
            # Čtyři rohy kvadru mezi dvěma profily
            p1 = points_grid[i][j]          # Aktuální profil, nižší bod
            p2 = points_grid[next_i][j]     # Další profil, nižší bod
            p3 = points_grid[i][j+1]        # Aktuální profil, vyšší bod
            p4 = points_grid[next_i][j+1]   # Další profil, vyšší bod
            
            # Dva trojúhelníky pro každý čtverec (správné pořadí normál)
            vertices_list.append([p1, p2, p3])
            vertices_list.append([p2, p4, p3])
    
    np_vertices = np.array(vertices_list)
    stl_mesh = mesh.Mesh(np.zeros(np_vertices.shape[0], dtype=mesh.Mesh.dtype))
    for i, face in enumerate(vertices_list):
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