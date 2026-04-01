import json
import os
from datetime import datetime

from samsungtvws import SamsungTVWS


def push_to_tv(image_data: bytes, tv_ip: str, history_file: str, art_cfg: dict = None):
    """Upload a JPEG frame to the Samsung Frame TV in Art Mode."""
    art_cfg = art_cfg or {}
    matte = art_cfg.get("matte", "none")
    portrait_matte = art_cfg.get("portrait_matte", "none")

    try:
        tv = SamsungTVWS(tv_ip)
        art = tv.art()

        try:
            if str(art.get_artmode()).lower() != "on":
                print("Art Mode is off; skipping frame update to avoid interrupting playback.")
                return
        except Exception as e:
            print(f"Could not determine Art Mode status ({e}); skipping update.")
            return

        remote_id = art.upload(image_data, file_type="jpg", matte=matte, portrait_matte=portrait_matte)
        art.select_image(remote_id)
        _manage_history(art, remote_id, history_file)
        print(f"Successfully pushed frame at {datetime.now().strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"TV connection failed: {e}")


def _manage_history(art_api, new_id: str, history_file: str):
    """Keep TV storage clean by deleting the oldest uploaded frame."""
    history = []
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history = json.load(f)

    if history:
        old_id = history.pop(0)
        try:
            art_api.delete(old_id)
        except Exception:
            pass

    history.append(new_id)
    os.makedirs(os.path.dirname(os.path.abspath(history_file)), exist_ok=True)
    with open(history_file, "w") as f:
        json.dump(history, f)
