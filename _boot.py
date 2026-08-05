import gc


def run_bootstrap():
    gc.collect()
    import main

    gc.collect()
    main.start()
