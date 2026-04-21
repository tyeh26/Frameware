import ipaddress
import mimetypes
import os
import tempfile

import yaml
from flask import Flask, Response, current_app, jsonify, render_template, request, send_file, send_from_directory

from frame.config_store import update_base_image, update_tv_ip
from frame.image_store import get_active_image, list_images, save_upload
from frame.layout import resolve_widget_sources
from frame.renderer import create_dashboard_frame
from frame.tv_discover import FRAME_SUFFIX_REFERENCE, discover_samsung_tvs, tv_reachable


def _ipv4_string(s: str) -> bool:
    try:
        return ipaddress.ip_address(s.strip()).version == 4
    except ValueError:
        return False


def create_app(
    config_path: str,
    base_dir: str,
    orchestrator=None,
    data_dir: str | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["CONFIG_PATH"] = config_path
    app.config["BASE_DIR"] = base_dir
    app.config["DATA_DIR"] = data_dir if data_dir is not None else base_dir
    app.config["ORCHESTRATOR"] = orchestrator

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/preview")
    def preview():
        preview_path = os.path.join(current_app.config["DATA_DIR"], "www", "frame_preview.jpg")
        if not os.path.exists(preview_path):
            return Response("Preview not yet generated.", status=404)
        with open(preview_path, "rb") as f:
            data = f.read()
        return Response(
            data,
            mimetype="image/jpeg",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    @app.route("/api/render", methods=["POST"])
    def render_now():
        """Regenerate the frame JPEG from the current config (no TV push). For local dev preview."""
        base_dir = current_app.config["BASE_DIR"]
        data_dir = current_app.config["DATA_DIR"]
        config_path = current_app.config["CONFIG_PATH"]
        preview_path = os.path.join(data_dir, "www", "frame_preview.jpg")
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            return jsonify({"error": f"Could not read config: {e}"}), 500
        if not isinstance(config, dict):
            return jsonify({"error": "Config must be a YAML mapping."}), 500

        art_cfg = config.get("art", {}) or {}
        base_rel = art_cfg.get("base_image")
        if not base_rel:
            return jsonify({"error": "art.base_image is not set in config."}), 400
        base_art = os.path.join(data_dir, base_rel)
        if not os.path.exists(base_art):
            return jsonify({"error": f"Base image not found: {base_rel!r}"}), 400

        layout = resolve_widget_sources(config.get("layout", {}))
        try:
            os.makedirs(os.path.dirname(preview_path), exist_ok=True)
            data = create_dashboard_frame(base_art, layout, base_dir, preview_path)
        except Exception as e:
            return jsonify({"error": f"Render failed: {e}"}), 500

        return Response(
            data,
            mimetype="image/jpeg",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    @app.route("/api/config", methods=["GET"])
    def get_config():
        path = current_app.config["CONFIG_PATH"]
        try:
            with open(path, "r") as f:
                raw = f.read()
            return Response(raw, mimetype="text/plain; charset=utf-8")
        except Exception as e:
            return Response(f"Error reading config: {e}", status=500)

    @app.route("/api/config", methods=["POST"])
    def save_config():
        raw = request.get_data(as_text=True)
        try:
            parsed = yaml.safe_load(raw)
            if not isinstance(parsed, dict):
                return jsonify({"error": "Config must be a YAML mapping."}), 400
        except yaml.YAMLError as e:
            return jsonify({"error": f"Invalid YAML: {e}"}), 400

        path = current_app.config["CONFIG_PATH"]
        try:
            dir_ = os.path.dirname(os.path.abspath(path))
            with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            os.replace(tmp_path, path)
        except Exception as e:
            return jsonify({"error": f"Could not write config: {e}"}), 500

        orch = current_app.config.get("ORCHESTRATOR")
        if orch:
            orch.force_tick()

        return jsonify({"status": "ok"})

    @app.route("/api/refresh", methods=["POST"])
    def refresh():
        orch = current_app.config.get("ORCHESTRATOR")
        if orch:
            orch.force_tick()
            return jsonify({"status": "ok"})
        return jsonify({"error": "Orchestrator not available."}), 503

    @app.route("/api/tv", methods=["GET"])
    def get_tv():
        path = current_app.config["CONFIG_PATH"]
        try:
            with open(path, "r") as f:
                cfg = yaml.safe_load(f)
        except Exception as e:
            return jsonify({"error": f"Could not read config: {e}"}), 500
        if not isinstance(cfg, dict):
            return jsonify({"error": "Config must be a YAML mapping."}), 500
        tv = cfg.get("tv") or {}
        ip = tv.get("ip") if isinstance(tv, dict) else None
        if isinstance(ip, str):
            ip = ip.strip() or None
        else:
            ip = None
        reachable = tv_reachable(ip) if ip else False
        return jsonify(
            {
                "ip": ip,
                "reachable": reachable,
                "frame_suffix_reference": list(FRAME_SUFFIX_REFERENCE),
            }
        )

    @app.route("/api/tv/discover", methods=["POST"])
    def discover_tv():
        try:
            result = discover_samsung_tvs(total_seconds=5.0)
        except OSError as e:
            return jsonify({"error": f"Discovery failed (network): {e}"}), 500
        except Exception as e:
            return jsonify({"error": f"Discovery failed: {e}"}), 500
        return jsonify(
            {
                "tvs": result["tvs"],
                "candidates": result["candidates"],
                "frame_suffix_reference": result.get(
                    "frame_suffix_reference", list(FRAME_SUFFIX_REFERENCE)
                ),
            }
        )

    @app.route("/api/tv", methods=["PUT"])
    def put_tv():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected JSON object."}), 400
        ip = body.get("ip")
        if not isinstance(ip, str) or not ip.strip():
            return jsonify({"error": "Field \"ip\" must be a non-empty string."}), 400
        ip = ip.strip()
        if not _ipv4_string(ip):
            return jsonify({"error": "Field \"ip\" must be an IPv4 address."}), 400
        path = current_app.config["CONFIG_PATH"]
        try:
            update_tv_ip(path, ip)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"Could not write config: {e}"}), 500
        orch = current_app.config.get("ORCHESTRATOR")
        if orch:
            orch.force_tick()
        return jsonify({"status": "ok"})

    # ── Image management ──────────────────────────────────────────────────────

    @app.route("/api/images", methods=["GET"])
    def get_images():
        """List all available images (uploaded + active config image if outside uploads)."""
        data_dir = current_app.config["DATA_DIR"]
        config_path = current_app.config["CONFIG_PATH"]
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
        except Exception:
            config = {}
        active = get_active_image(config or {})
        images = list_images(data_dir, active_rel=active)
        return jsonify({"images": images, "active": active})

    @app.route("/api/images", methods=["POST"])
    def upload_image():
        """
        Upload an image file (multipart/form-data, field name 'file').
        Activates it immediately unless ?activate=false is passed.
        """
        data_dir = current_app.config["DATA_DIR"]
        config_path = current_app.config["CONFIG_PATH"]

        if "file" not in request.files:
            return jsonify({"error": "No 'file' field in request."}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "No filename provided."}), 400

        try:
            rel_path = save_upload(f, f.filename, data_dir)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"Upload failed: {e}"}), 500

        activate = request.args.get("activate", "true").lower() != "false"
        if activate:
            try:
                update_base_image(config_path, rel_path)
            except Exception as e:
                return jsonify({"error": f"Saved file but could not activate: {e}"}), 500
            orch = current_app.config.get("ORCHESTRATOR")
            if orch:
                orch.force_tick()

        return jsonify({"status": "ok", "rel_path": rel_path, "activated": activate})

    @app.route("/api/images/active", methods=["PUT"])
    def set_active_image():
        """Set the active image by relative path (updates art.base_image in config)."""
        data_dir = current_app.config["DATA_DIR"]
        config_path = current_app.config["CONFIG_PATH"]

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected JSON object."}), 400
        rel_path = body.get("path")
        if not isinstance(rel_path, str) or not rel_path.strip():
            return jsonify({"error": 'Field "path" must be a non-empty string.'}), 400
        rel_path = rel_path.strip()

        abs_data = os.path.abspath(data_dir)
        abs_img = os.path.normpath(os.path.join(data_dir, rel_path))
        if not abs_img.startswith(abs_data + os.sep):
            return jsonify({"error": "Invalid path."}), 400
        if not os.path.isfile(abs_img):
            return jsonify({"error": f"Image not found: {rel_path!r}"}), 404

        try:
            update_base_image(config_path, rel_path)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"Could not write config: {e}"}), 500

        orch = current_app.config.get("ORCHESTRATOR")
        if orch:
            orch.force_tick()
        return jsonify({"status": "ok"})

    @app.route("/api/images/file/<filename>")
    def serve_upload(filename):
        """Serve an uploaded image from data_dir/art/uploads/."""
        data_dir = current_app.config["DATA_DIR"]
        uploads_dir = os.path.join(data_dir, "art", "uploads")
        return send_from_directory(uploads_dir, filename)

    @app.route("/api/images/active-thumb")
    def serve_active_thumb():
        """Serve the currently active image regardless of where it lives in data_dir."""
        data_dir = current_app.config["DATA_DIR"]
        config_path = current_app.config["CONFIG_PATH"]
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
        except Exception:
            return Response("Config not readable.", status=500)
        active = get_active_image(config or {})
        if not active:
            return Response("No active image configured.", status=404)
        abs_data = os.path.abspath(data_dir)
        abs_img = os.path.normpath(os.path.join(data_dir, active))
        if not abs_img.startswith(abs_data + os.sep):
            return Response("Forbidden.", status=403)
        if not os.path.isfile(abs_img):
            return Response("Image not found.", status=404)
        mime = mimetypes.guess_type(abs_img)[0] or "image/jpeg"
        return send_file(abs_img, mimetype=mime)

    return app
