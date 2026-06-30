"""Backend frontend fallback contract."""


def test_backend_root_redirects_to_vite_when_dist_missing(monkeypatch):
    import backend.main as backend_main

    monkeypatch.setattr(backend_main, "FRONTEND_DIR", "/tmp/network-agent-missing-dist")
    monkeypatch.setenv("NETWORK_AGENT_FRONTEND_DEV_URL", "http://127.0.0.1:5173")
    client = backend_main.create_app().test_client()

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "http://127.0.0.1:5173/"


def test_backend_root_redirect_preserves_request_host_when_dev_url_unset(monkeypatch):
    import backend.main as backend_main

    monkeypatch.setattr(backend_main, "FRONTEND_DIR", "/tmp/network-agent-missing-dist")
    monkeypatch.delenv("NETWORK_AGENT_FRONTEND_DEV_URL", raising=False)
    client = backend_main.create_app().test_client()

    response = client.get("/", headers={"Host": "192.168.5.12:8010"})

    assert response.status_code == 302
    assert response.headers["Location"] == "http://192.168.5.12:5173/"


def test_unknown_api_path_stays_json_404_when_dist_missing(monkeypatch):
    import backend.main as backend_main

    monkeypatch.setattr(backend_main, "FRONTEND_DIR", "/tmp/network-agent-missing-dist")
    client = backend_main.create_app().test_client()

    response = client.get("/api/not-a-real-route")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"
