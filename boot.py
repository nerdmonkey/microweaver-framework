import gc

try:
    import main

    main.start()
except Exception as err:
    print("BOOT: unhandled exception:", err)
    raise
finally:
    gc.collect()
