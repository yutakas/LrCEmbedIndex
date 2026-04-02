import logging

from flask import Flask

from config import config, load_config, get_vision_model_label, get_embed_model_label
from metadata import count_metadata_files
from vectorstore import init_chromadb
from routes import api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.register_blueprint(api)
    return app


def startup():
    if load_config():
        if config["index_folder"]:
            init_chromadb()
            logger.info(f"Startup: {count_metadata_files()} metadata files found")
    logger.info(f"Vision: {get_vision_model_label()}, Embed: {get_embed_model_label()}")


if __name__ == "__main__":
    startup()
    app = create_app()
    app.run(host="127.0.0.1", port=8600, debug=False)
