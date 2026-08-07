try:
    import _boot
except Exception as err:
    print("BOOT: failed to import bootstrap module:", err)
    raise

run_bootstrap = getattr(_boot, "run_bootstrap", None)
if run_bootstrap is None:
    print(
        "BOOT: bootstrap module missing run_bootstrap; "
        "leaving REPL available for recovery"
    )
else:
    try:
        run_bootstrap()
    except Exception as err:
        print("BOOT: unhandled exception:", err)
        raise
