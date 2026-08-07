import gc

from app.services.bootloop import BootLoopGuard
from app.services.factory_reset import FactoryResetService
from app.services.logger import LogService
from app.services.reset import ResetService
from config.app import Setting

setting = (Setting()).get_settings()


def run_bootstrap():
    gc.collect()
    ResetService(logger=LogService(format=setting.LOG_FORMAT)).read()

    guard = BootLoopGuard(
        setting.BOOT_LOOP_STATE_PATH,
        setting.BOOT_LOOP_MAX_ATTEMPTS,
        setting.BOOT_LOOP_PROTECTION_ENABLED,
    )
    boot_loop_detected = guard.check()

    if setting.FACTORY_RESET_ENABLED:
        factory_reset = FactoryResetService(
            pin=setting.FACTORY_RESET_PIN,
            hold_seconds=setting.FACTORY_RESET_HOLD_SECONDS,
            sentinel_path=setting.FACTORY_RESET_SENTINEL_PATH,
            setting=setting,
        )
        if factory_reset.should_trigger():
            print("BOOT: factory reset requested, clearing credentials")
            factory_reset.clear_credentials()

    import main

    gc.collect()

    if boot_loop_detected:
        print("BOOT: boot-loop detected, entering safe mode")
        main.start_safe_mode()
        return

    if not setting.WIFI_SSID:
        print("BOOT: no WiFi credentials configured, entering provisioning mode")
        main.start_provisioning()
        return

    main.start()
