import os

from app.services.device_cert import DeviceCertService


def test_resolve_returns_configured_paths_when_set():
    service = DeviceCertService()

    ssl_params = service.resolve("/certs/client.crt", "/certs/client.key", "", "")

    assert ssl_params == {"cert": "/certs/client.crt", "key": "/certs/client.key"}


def test_resolve_omits_missing_configured_path():
    service = DeviceCertService()

    ssl_params = service.resolve("/certs/client.crt", "", "", "")

    assert ssl_params == {"cert": "/certs/client.crt"}


def test_resolve_returns_empty_when_nothing_configured():
    service = DeviceCertService()

    assert service.resolve("", "", "", "") == {}


def test_resolve_falls_back_to_claimed_device_cert(tmp_path):
    cert_path = str(tmp_path / "device_cert.pem")
    key_path = str(tmp_path / "device_key.pem")
    service = DeviceCertService(cert_path, key_path)

    ssl_params = service.resolve("", "", "cert-pem-content", "key-pem-content")

    assert ssl_params == {"cert": cert_path, "key": key_path}
    with open(cert_path) as f:
        assert f.read() == "cert-pem-content"
    with open(key_path) as f:
        assert f.read() == "key-pem-content"


def test_resolve_ignores_claimed_cert_when_explicit_path_configured(tmp_path):
    cert_path = str(tmp_path / "device_cert.pem")
    key_path = str(tmp_path / "device_key.pem")
    service = DeviceCertService(cert_path, key_path)

    ssl_params = service.resolve(
        "/certs/client.crt", "/certs/client.key", "cert-pem-content", "key-pem-content"
    )

    assert ssl_params == {"cert": "/certs/client.crt", "key": "/certs/client.key"}
    assert not os.path.exists(cert_path)


def test_resolve_ignores_claimed_cert_missing_key():
    service = DeviceCertService()

    assert service.resolve("", "", "cert-pem-content", "") == {}
