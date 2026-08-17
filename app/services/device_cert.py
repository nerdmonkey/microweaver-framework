class DeviceCertService:
    """Falls back to the claimed device_cert/device_key (from registration.py's
    claim flow) as the MQTT client's mTLS cert when no explicit
    mqtt_ssl_cert_path/mqtt_ssl_key_path is configured - writing the PEM
    content to disk since umqtt.simple's ssl_params expects file paths, not
    inline PEM."""

    def __init__(self, cert_path="device_cert.pem", key_path="device_key.pem"):
        self.cert_path = cert_path
        self.key_path = key_path

    def resolve(self, mqtt_cert_path, mqtt_key_path, device_cert, device_key):
        cert_path = mqtt_cert_path
        key_path = mqtt_key_path
        if not cert_path and not key_path and device_cert and device_key:
            self._write(self.cert_path, device_cert)
            self._write(self.key_path, device_key)
            cert_path, key_path = self.cert_path, self.key_path

        ssl_params = {}
        if cert_path:
            ssl_params["cert"] = cert_path
        if key_path:
            ssl_params["key"] = key_path
        return ssl_params

    def _write(self, path, content):
        with open(path, "w") as cert_file:
            cert_file.write(content)
