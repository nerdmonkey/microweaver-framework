import gc
import time

import machine

from app.services.bootloop import BootLoopGuard
from app.services.crash_log import CrashLogService
from app.services.factory_reset import FactoryResetService
from app.services.logger import LogService
from app.services.ota import OtaService
from app.services.reset import ResetService
from config.app import Setting

setting = (Setting()).get_settings()


def _open_boot_interrupt_window():
    seconds = setting.BOOT_INTERRUPT_WINDOW_SECONDS
    if seconds <= 0:
        return
    print(
        "BOOT: serial interrupt window open for",
        seconds,
        "s (connect with mpremote now)",
    )
    time.sleep(seconds)


def run_bootstrap():
    gc.collect()
    crash_log = CrashLogService(
        setting.CRASH_LOG_PATH,
        setting.CRASH_LOG_ENABLED,
        max_bytes=setting.CRASH_LOG_MAX_BYTES,
    )
    ResetService(
        logger=LogService(format=setting.LOG_FORMAT), crash_log=crash_log
    ).read()

    guard = BootLoopGuard(
        setting.BOOT_LOOP_STATE_PATH,
        setting.BOOT_LOOP_MAX_ATTEMPTS,
        setting.BOOT_LOOP_PROTECTION_ENABLED,
    )
    boot_loop_detected = guard.check()

    ota_service = None
    if setting.OTA_ENABLED:
        ota_service = OtaService(
            setting.OTA_MANIFEST_URL,
            setting=setting,
            state_path=setting.OTA_STATE_PATH,
        )

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
    _open_boot_interrupt_window()

    if not setting.AUTOSTART_ENABLED:
        print("BOOT: autostart disabled, leaving device idle for serial access")
        return

    if boot_loop_detected:
        if ota_service and ota_service.rollback():
            print("BOOT: OTA rollback complete, restarting")
            crash_log.write("boot_loop_reset", attempts=guard.attempts)
            machine.reset()
            return
        print("BOOT: boot-loop detected, entering safe mode")
        main.start_safe_mode()
        return

    if not setting.WIFI_SSID:
        print("BOOT: no WiFi credentials configured, entering provisioning mode")
        main.start_provisioning()
        return

    if setting.CLAIM_ENABLED and not setting.DEVICE_ID and setting.CLAIM_CODE:
        print("BOOT: device not yet claimed, registering with backend")
        main.start_claim()

    main.start()
