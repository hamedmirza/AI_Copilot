from app.providers.ollama import normalize_ollama_base_url, ollama_native_root


def test_normalize_ollama_base_url_appends_v1():
    assert normalize_ollama_base_url("http://172.10.1.2:11434") == "http://172.10.1.2:11434/v1"
    assert normalize_ollama_base_url("http://172.10.1.2:11434/") == "http://172.10.1.2:11434/v1"
    assert normalize_ollama_base_url("http://172.10.1.2:11434/v1") == "http://172.10.1.2:11434/v1"
    assert normalize_ollama_base_url("http://172.10.1.2:11434/v1/") == "http://172.10.1.2:11434/v1"


def test_ollama_native_root_strips_v1():
    assert ollama_native_root("http://172.10.1.2:11434/v1") == "http://172.10.1.2:11434"
    assert ollama_native_root("http://172.10.1.2:11434") == "http://172.10.1.2:11434"
