from app.services.logger import LogService


class ErrorHandlerService:
    """Centralized exception boundary.

    Wraps a callable so a raised exception is logged and swallowed
    instead of propagating and crashing its caller. Generalizes the
    catch-log-continue shape ServiceRegistry.stop_all(),
    HealthCheckService.poll(), and ServiceRestartService.reconcile()
    each implement ad hoc for their own narrow purpose.
    """

    def __init__(self, logger=None):
        self.logger = logger or LogService()

    def guard(self, fn, context, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            self.logger.log(
                "unhandled_exception",
                level="error",
                context=context,
                error=str(e),
            )
            return None
