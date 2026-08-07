import socket

import network

ACCEPT_TIMEOUT_SECONDS = 1.0


class ProvisioningService:
    def __init__(
        self,
        ap_ssid="Microweaver-Setup",
        ap_password="",
        ap_ip="192.168.4.1",
        port=80,
        setting=None,
    ):
        self.ap_ssid = ap_ssid
        self.ap_password = ap_password
        self.ap_ip = ap_ip
        self.port = port
        self.setting = setting
        self.ap = network.WLAN(network.AP_IF)
        self.server = None

    def start(self):
        self.ap.active(True)
        self.ap.ifconfig((self.ap_ip, "255.255.255.0", self.ap_ip, self.ap_ip))
        if self.ap_password:
            self.ap.config(
                essid=self.ap_ssid,
                password=self.ap_password,
                authmode=network.AUTH_WPA_WPA2_PSK,
            )
        else:
            self.ap.config(essid=self.ap_ssid, authmode=network.AUTH_OPEN)
        print("Provisioning AP started:", self.ap_ssid, self.ap_ip)

    def stop(self):
        if self.server:
            self.server.close()
            self.server = None
        self.ap.active(False)
        print("Provisioning AP stopped")

    def scan_networks(self):
        sta = network.WLAN(network.STA_IF)
        sta.active(True)
        ssids = set()
        for entry in sta.scan():
            ssid = entry[0]
            if isinstance(ssid, bytes):
                ssid = ssid.decode()
            if ssid:
                ssids.add(ssid)
        return sorted(ssids)

    def run(self):
        self.start()
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("0.0.0.0", self.port))
        self.server.listen(1)
        self.server.settimeout(ACCEPT_TIMEOUT_SECONDS)
        print("Provisioning server listening on port", self.port)
        try:
            while True:
                try:
                    client, _addr = self.server.accept()
                except OSError:
                    # accept() timed out with no client connecting - loop
                    # back so the interpreter gets a chance to process a
                    # Ctrl-C / raw-REPL request instead of blocking forever.
                    continue
                self._handle_request(client)
        finally:
            self.stop()

    def _handle_request(self, client):
        try:
            request = client.recv(1024)
            method, path = self._parse_request_line(request)
            if method == "POST" and path == "/save":
                fields = self._parse_form(request)
                self._save_credentials(fields)
                client.send(self._response(200, "Credentials saved. Rebooting."))
            else:
                client.send(
                    self._response(200, self._render_form(), content_type="text/html")
                )
        except ValueError as e:
            print("Provisioning request rejected:", e)
            client.send(self._response(400, str(e)))
        except Exception as e:
            print("Provisioning request failed:", e)
            client.send(self._response(500, "Internal server error"))
        finally:
            client.close()

    def _save_credentials(self, fields):
        ssid = fields.get("ssid", "").strip()
        password = fields.get("password", "")
        claim_code = fields.get("claim_code", "").strip()
        if not ssid:
            raise ValueError("ssid is required")
        if self.setting:
            self.setting.save(
                wifi_ssid=ssid, wifi_password=password, claim_code=claim_code or None
            )
        print("Provisioning saved credentials for ssid:", ssid)

    def _parse_request_line(self, request):
        line = request.split(b"\r\n", 1)[0].decode()
        parts = line.split(" ")
        return parts[0], parts[1]

    def _parse_form(self, request):
        body = request.split(b"\r\n\r\n", 1)[1].decode()
        fields = {}
        for pair in body.split("&"):
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            fields[self._unquote(key)] = self._unquote(value)
        return fields

    def _unquote(self, value):
        value = value.replace("+", " ")
        result = ""
        i = 0
        while i < len(value):
            if value[i] == "%" and i + 2 < len(value):
                hex_pair = value[i + 1 : i + 3]  # noqa: E203
                result += chr(int(hex_pair, 16))
                i += 3
            else:
                result += value[i]
                i += 1
        return result

    def _render_form(self):
        options = "".join(
            '<option value="{0}">{0}</option>'.format(ssid)
            for ssid in self.scan_networks()
        )
        return (
            "<html><body><h1>Microweaver WiFi Setup</h1>"
            '<form method="POST" action="/save">'
            '<select name="ssid">{options}</select><br>'
            '<input type="password" name="password" placeholder="Password"><br>'
            '<input type="text" name="claim_code" placeholder="Claim code (optional)">'
            "<br>"
            '<button type="submit">Save</button>'
            "</form></body></html>"
        ).format(options=options)

    def _response(self, status, body, content_type="text/plain"):
        status_text = {200: "OK", 400: "Bad Request", 500: "Internal Server Error"}
        return (
            ("HTTP/1.1 {0} {1}\r\nContent-Type: {2}\r\nConnection: close\r\n\r\n{3}")
            .format(status, status_text.get(status, "Error"), content_type, body)
            .encode()
        )
