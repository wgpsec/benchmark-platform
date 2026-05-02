import json
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock

_log_file = None
_log_lock = Lock()
_init_lock = Lock()


def get_logger(log_file_path: Path):
    """Get logger instance with JSONL file output"""
    global _log_file

    # Double-checked locking pattern for thread-safe initialization
    if _log_file is None:
        with _init_lock:
            if _log_file is None:
                log_file_path.parent.mkdir(parents=True, exist_ok=True)
                _log_file = open(log_file_path, 'a', encoding='utf-8')

    return Logger()


class Logger:
    def _log(self, level: str, message: str, **kwargs):
        """Internal logging method"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            **kwargs,
        }

        try:
            with _log_lock:
                # Generate JSON line
                json_line = json.dumps(
                    log_entry, ensure_ascii=False, default=str,
                )

                # Write to file if initialized
                if _log_file is not None:
                    _log_file.write(json_line + '\n')
                    _log_file.flush()

                # Also output to terminal in JSON format
                output_stream = sys.stderr if level in (
                    'ERROR', 'CRITICAL',
                ) else sys.stdout
                print(json_line, file=output_stream, flush=True)
        except Exception:
            # Silently fail to avoid breaking application
            pass

    def debug(self, message: str, **kwargs):
        self._log('DEBUG', message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log('INFO', message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log('WARNING', message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log('ERROR', message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log('CRITICAL', message, **kwargs)
