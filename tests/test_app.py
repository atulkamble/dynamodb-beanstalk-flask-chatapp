import json
from application import application

def test_health():
    client = application.test_client()
    r = client.get("/health")
    assert r.status_code == 200
    d = r.get_json()
    assert "status" in d
