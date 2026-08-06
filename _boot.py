import gc

from app.services.reset import ResetService


def run_bootstrap():
    gc.collect()
    ResetService().read()

    import main

    gc.collect()
    main.start()
