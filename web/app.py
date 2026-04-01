import os
import tempfile

import yaml
from flask import Flask, Response, current_app, jsonify, render_template, request


def create_app(config_path: str, base_dir: str, orchestrator=None) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["CONFIG_PATH"] = config_path
    app.config["BASE_DIR"] = base_dir
    app.config["ORCHESTRATOR"] = orchestrator

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/preview")
    def preview():
        preview_path = os.path.join(current_app.config["BASE_DIR"], "www", "frame_preview.jpg")
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

    return app
