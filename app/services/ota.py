import urequests


class OtaService:
    def __init__(self, manifest_url="", setting=None):
        self.manifest_url = manifest_url
        self.setting = setting

    def check_for_update(self):
        if not self.manifest_url:
            print("OTA check skipped: manifest_url not configured")
            return None

        try:
            response = urequests.get(self.manifest_url)
        except Exception as e:
            print("OTA manifest fetch failed:", e)
            return None

        try:
            if response.status_code != 200:
                print("OTA manifest rejected: HTTP", response.status_code)
                return None
            return response.json()
        finally:
            response.close()

    def is_update_available(self, manifest):
        if not manifest or not manifest.get("version"):
            return False

        current_version = self.setting.APP_VERSION if self.setting else None
        return manifest["version"] != current_version

    def write_file(self, path, content):
        with open(path, "w") as target:
            target.write(content)

    def apply_payload(self, path, content):
        try:
            self.write_file(path, content)
        except Exception as e:
            print("OTA payload apply failed:", path, e)
            return False

        print("OTA payload written:", path)
        return True

    def download_file(self, url, path):
        try:
            response = urequests.get(url)
        except Exception as e:
            print("OTA file download failed:", url, e)
            return False

        try:
            if response.status_code != 200:
                print("OTA file download rejected:", url, "HTTP", response.status_code)
                return False
            self.write_file(path, response.text)
        finally:
            response.close()

        print("OTA file written:", path)
        return True

    def apply_update(self):
        manifest = self.check_for_update()
        if not self.is_update_available(manifest):
            print("OTA: no update available")
            return False

        for path, url in manifest.get("files", {}).items():
            if not self.download_file(url, path):
                print("OTA update aborted: failed to download", path)
                return False

        if self.setting:
            self.setting.save(app_version=manifest["version"])

        print("OTA update applied, version:", manifest["version"])
        return True
