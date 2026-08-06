from app.services.publish import PublishService
from app.services.safe_mode import SafeModeService
from config.app import Setting

setting = (Setting()).get_settings()


def start():
    publish = PublishService()
    publish.run()


def start_safe_mode():
    safe_mode = SafeModeService(setting.SAFE_MODE_SLEEP_SECONDS)
    safe_mode.run()


if __name__ == "__main__":
    start()
