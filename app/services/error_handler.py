import io
import sys

from app.services.logger import LogService


def format_exception(e):
    """Render a full stack trace for e, falling back when unavailable.

    MicroPython has no `traceback` module; `sys.print_exception` is its
    equivalent, writing to any stream-like object including `io.StringIO`.
    CPython's `sys` has no `print_exception`, so tests (and any future
    non-MicroPython host) fall back to just the exception type and args.
    """
    try:
        buf = io.StringIO()
        sys.print_exception(e, buf)
        return buf.getvalue().strip()
    except AttributeError:
        return "{}: {}".format(type(e).__name__, e)


class ErrorHandlerService:
    """Centralized exception boundary.

    Wraps a callable so a raised exception is logged and swallowed
    instead of propagating and crashing its caller. Generalizes the
    catch-log-continue shape ServiceRegistry.stop_all(),
    HealthCheckService.poll(), and ServiceRestartService.reconcile()
    each implement ad hoc for their own narrow purpose.
    """

    def __init__(self, logger=None, crash_log=None, metrics=None):
        self.logger = logger or LogService()
        self.crash_log = crash_log
        self.metrics = metrics

    def guard(self, fn, context, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            trace = format_exception(e)
            self.logger.log(
                "unhandled_exception",
                level="error",
                context=context,
                error=str(e),
                trace=trace,
            )
            if self.crash_log:
                self.crash_log.write(
                    "unhandled_exception", context=context, error=str(e), trace=trace
                )
            if self.metrics:
                self.metrics.record_error()
            return None
