import logging
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configure_terminal():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )


def safe_traceback(error):
    """Keep every stack frame and the exception chain without logging data values."""
    seen = set()

    def frames(exc):
        if id(exc) in seen:
            return
        seen.add(id(exc))
        preceding = exc.__cause__
        if preceding is None and not exc.__suppress_context__:
            preceding = exc.__context__
        if preceding is not None:
            yield from frames(preceding)
            yield '  Exceção anterior'
        yield 'Traceback (most recent call last):'
        for frame, line in traceback.walk_tb(exc.__traceback__):
            code = frame.f_code
            path = Path(code.co_filename)
            filename = path.relative_to(PROJECT_ROOT).as_posix() if path.is_relative_to(PROJECT_ROOT) else path.name
            yield f'  File "{filename}", line {line}, in {code.co_name}'
        yield type(exc).__name__
        if isinstance(exc, BaseExceptionGroup):
            for nested in exc.exceptions:
                yield from frames(nested)

    return '\n'.join(frames(error))
