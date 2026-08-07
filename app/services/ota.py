import os

import urequests

try:
    import ujson as json
except ImportError:
    import json

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii

STAGED_SUFFIX = ".ota_new"
BACKUP_SUFFIX = ".ota_bak"


class OtaService:
    def __init__(self, manifest_url="", setting=None, state_path="ota_state.json"):
        self.manifest_url = manifest_url
        self.setting = setting
        self.state_path = state_path

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

    def download_file(self, url, path, expected_sha256=None):
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

        if expected_sha256 and not self._verify_checksum(path, expected_sha256):
            print("OTA checksum mismatch, rejecting payload:", path)
            self._remove(path)
            return False

        print("OTA file written:", path)
        return True

    def apply_update(self):
        manifest = self.check_for_update()
        if not self.is_update_available(manifest):
            print("OTA: no update available")
            return False

        staged = {}
        for path, file_meta in manifest.get("files", {}).items():
            url, expected_sha256 = self._file_url_and_checksum(file_meta)
            if not expected_sha256:
                print("OTA update aborted: missing checksum for", path)
                self._remove_all(staged.values())
                return False

            staged_path = path + STAGED_SUFFIX
            if not self.download_file(url, staged_path, expected_sha256):
                print("OTA update aborted: failed to stage", path)
                self._remove_all(staged.values())
                return False
            staged[path] = staged_path

        backups = {}
        for path, staged_path in staged.items():
            if self._exists(path):
                os.rename(path, path + BACKUP_SUFFIX)
                backups[path] = True
            else:
                backups[path] = False
            os.rename(staged_path, path)

        self._write_state(
            {
                "version": manifest["version"],
                "previous_version": self.setting.APP_VERSION if self.setting else None,
                "files": backups,
            }
        )

        if self.setting:
            self.setting.save(app_version=manifest["version"])

        print("OTA update applied, version:", manifest["version"])
        return True

    def rollback(self):
        state = self._read_state()
        if not state:
            return False

        for path, had_backup in state.get("files", {}).items():
            self._remove(path)
            if had_backup:
                try:
                    os.rename(path + BACKUP_SUFFIX, path)
                except Exception as e:
                    print("OTA rollback failed for", path, e)

        if self.setting:
            self.setting.save(app_version=state.get("previous_version"))

        self._clear_state()
        print("OTA rollback complete, restored version:", state.get("previous_version"))
        return True

    def confirm_update(self):
        state = self._read_state()
        if not state:
            return

        for path, had_backup in state.get("files", {}).items():
            if had_backup:
                self._remove(path + BACKUP_SUFFIX)

        self._clear_state()
        print("OTA update confirmed, version:", state.get("version"))

    def _file_url_and_checksum(self, file_meta):
        if isinstance(file_meta, dict):
            return file_meta.get("url"), file_meta.get("sha256")
        return file_meta, None

    def _verify_checksum(self, path, expected_sha256):
        actual = self._sha256_hex(path)
        return actual is not None and actual.lower() == expected_sha256.lower()

    def _sha256_hex(self, path):
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as source:
                while True:
                    chunk = source.read(512)
                    if not chunk:
                        break
                    digest.update(chunk)
            return binascii.hexlify(digest.digest()).decode()
        except Exception as e:
            print("OTA checksum computation failed:", path, e)
            return None

    def _remove_all(self, paths):
        for path in paths:
            self._remove(path)

    def _exists(self, path):
        try:
            os.stat(path)
            return True
        except OSError:
            return False

    def _remove(self, path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _read_state(self):
        try:
            with open(self.state_path, "r") as state_file:
                return json.load(state_file)
        except Exception:
            return None

    def _write_state(self, state):
        try:
            with open(self.state_path, "w") as state_file:
                json.dump(state, state_file)
        except Exception as e:
            print("Failed to persist OTA state:", e)

    def _clear_state(self):
        self._remove(self.state_path)
