try:
    import network

    # Claim the STA_IF singleton now, before `import _boot` pulls in the rest
    # of the app's module tree and eats the heap. network.WLAN(id) on the
    # ESP32 port only runs the expensive esp_wifi_init() (the rx/tx buffer
    # allocation) on its first call per interface; every later
    # network.WLAN(network.STA_IF) call - including the one in
    # app/services/wifi.py - just returns this same cached object. Doing the
    # first call here, while the heap is still virgin, avoids esp-idf's
    # "Expected to init 10 rx buffer, actual is 2" WiFi Out of Memory error.
    network.WLAN(network.STA_IF)
except Exception as err:
    print("BOOT: failed to pre-initialize WiFi interface:", err)

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
