import urequests


class RegistrationService:
    def __init__(
        self,
        claim_url="",
        claim_code="",
        setting=None,
    ):
        self.claim_url = claim_url
        self.claim_code = claim_code
        self.setting = setting

    def is_claimed(self):
        return bool(self.setting and self.setting.DEVICE_ID)

    def register(self):
        if not self.claim_url or not self.claim_code:
            print("Registration skipped: claim_url or claim_code not configured")
            return None

        print("Registering device with backend using claim code")
        try:
            response = urequests.post(
                self.claim_url, json={"claim_code": self.claim_code}
            )
        except Exception as e:
            print("Device registration failed:", e)
            return None

        try:
            if response.status_code != 200:
                print("Device registration rejected: HTTP", response.status_code)
                return None
            data = response.json()
        finally:
            response.close()

        device_id = data.get("device_id", "")
        if not device_id:
            print("Device registration response missing device_id")
            return None

        if self.setting:
            self.setting.save(
                device_id=device_id,
                device_cert=data.get("device_cert", ""),
                device_key=data.get("device_key", ""),
                mqtt_lwt_topic=data.get("lwt_topic", ""),
                mqtt_lwt_message=data.get("lwt_payload", ""),
                claim_code="",
            )

        print("Device registered with id:", device_id)
        return data
