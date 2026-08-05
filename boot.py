try:
    from _boot import run_bootstrap

    run_bootstrap()
except Exception as err:
    print("BOOT: unhandled exception:", err)
    raise
