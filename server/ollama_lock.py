import threading

# Serialize all Ollama API calls (vision + embedding) to avoid
# overloading a local Ollama instance with concurrent requests.
ollama_lock = threading.Lock()
