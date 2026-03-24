import os
import io
import json
import time
import signal
import glob
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from samsungtvws import SamsungTVWS

# --- CONFIGURATION ---
TV_IP = '192.168.6.53'  # Update with your TV's actual IP
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ART_FOLDER = os.path.join(BASE_DIR, "art")
FONT_PATH = os.path.join(BASE_DIR, "fonts", "Roboto-Bold.ttf")
HISTORY_FILE = os.path.join(BASE_DIR, "frame_history.json")
WWW_DIR = os.path.join(BASE_DIR, "www")
os.makedirs(WWW_DIR, exist_ok=True) 

PREVIEW_PATH = os.path.join(WWW_DIR, "frame_preview.jpg")
# --- CORE LOGIC ---

def get_base_image():
    """Selects a random image from the art folder."""
    extensions = ['*.jpg', '*.jpeg', '*.png']
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(ART_FOLDER, ext)))
    return files[0] if files else None

def create_flip_clock_frame(base_image_path):
    """Generates the 4K image with the flip clock overlay."""
    img = Image.open(base_image_path).convert("RGB")
    if img.size != (3840, 2160):
        img = img.resize((3840, 2160), Image.Resampling.LANCZOS)
    
    draw = ImageDraw.Draw(img)
    current_time = datetime.now().strftime("%I:%M %p")
    
    scale = 1
    base_font_size = 180
    base_pad = 40
    base_margin = 100
    base_radius = 30
    base_divider_width = 4
    base_text_y_offset = -20

    font_size = base_font_size * scale
    font_candidates = [
        FONT_PATH,
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    font = None
    for path in font_candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except:
                pass
    if font is None:
        font = ImageFont.load_default()

    # Flip Clock Positioning (Bottom Right)
    bbox = draw.textbbox((0, 0), current_time, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = base_pad * scale
    margin = base_margin * scale
    x1, y1 = 3840 - text_w - (pad*2) - margin, 2160 - text_h - (pad*2) - margin
    x2, y2 = 3840 - margin, 2160 - margin

    # Draw the "Flip" background and text
    draw.rounded_rectangle([x1, y1, x2, y2], radius=base_radius * scale, fill=(15, 15, 15))
    draw.line(
        [x1, y1 + (y2 - y1) // 2, x2, y1 + (y2 - y1) // 2],
        fill=(30, 30, 30),
        width=base_divider_width * scale,
    )
    draw.text((x1 + pad, y1 + pad + (base_text_y_offset * scale)), current_time, fill="white", font=font)

    # Save preview for Home Assistant
    img.save(PREVIEW_PATH, quality=85)
    
    # Return as bytes for the API
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    return img_byte_arr.getvalue()

# --- TV COMMUNICATION ---

def push_to_tv(image_data):
    """Updated to use the latest samsungtvws method names."""
    try:
        tv = SamsungTVWS(TV_IP)
        art = tv.art()
        
        # 1. Upload the image
        remote_id = art.upload(image_data, file_type='jpg')
        
        # 2. SELECT THE IMAGE (The fixed line)
        # Old: art.select_artwork(remote_id)
        art.select_image(remote_id)
        
        # 3. Manage history
        manage_history(art, remote_id)
        print(f"Successfully pushed frame at {datetime.now().strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"Connection failed: {e}")

def manage_history(art_api, new_id):
    """Keeps the TV storage clean by deleting the previous frame."""
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            history = json.load(f)
    
    # Delete the oldest image if history exists
    if history:
        old_id = history.pop(0)
        try:
            art_api.delete(old_id)
        except:
            pass
            
    # Save the new ID to history
    history.append(new_id)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

# --- RUNTIME CONTROL ---

def main_loop():
    print("Starting Frame TV Dashboard Loop... (Ctrl+C to stop)")
    while True:
        base_art = get_base_image()
        if base_art:
            frame_data = create_flip_clock_frame(base_art)
            push_to_tv(frame_data)
        
        # Wait 60 seconds for the next minute update
        time.sleep(60)

def handle_exit(signum, frame):
    print("\nGracefully shutting down...")
    exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_exit) # Handle Ctrl+C
    main_loop()
