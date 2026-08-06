import gc

from app.services.bootloop import BootLoopGuard
from app.services.reset import ResetService
from config.app import Setting

setting = (Setting()).get_settings()


def run_bootstrap():
    gc.collect()
    ResetService().read()

    guard = BootLoopGuard(
        setting.BOOT_LOOP_STATE_PATH,
        setting.BOOT_LOOP_MAX_ATTEMPTS,
        setting.BOOT_LOOP_PROTECTION_ENABLED,
    )
    boot_loop_detected = guard.check()

    import main

    gc.collect()

    if boot_loop_detected:
        print("BOOT: boot-loop detected, entering safe mode")
        main.start_safe_mode()
        return

    main.start()
