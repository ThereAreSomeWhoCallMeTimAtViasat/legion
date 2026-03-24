"""
LEGION (https://shanewilliamscott.com)
Copyright (c) 2025 Shane William Scott

    This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
    License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
    version.

    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
    warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
    details.

    You should have received a copy of the GNU General Public License along with this program.
    If not, see <http://www.gnu.org/licenses/>.

Author(s): Shane Scott (sscott@shanewilliamscott.com), Dmitriy Dubson (d.dubson@gmail.com)
"""

import os
import logging
from logging import Logger
from collections import deque

cachedAppLogger = None
cachedStartupLogger = None
cachedDbLogger = None


class _InMemoryLogHandler(logging.Handler):
    """Captures log records in memory so /api/logs works without a file redirect.
    Thread-safe: deque append/popleft are atomic in CPython."""
    def __init__(self, maxlen=2000):
        super().__init__()
        self._buf = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter(
            '%(asctime)s  %(levelname)-8s  %(name)s: %(message)s',
            datefmt='%H:%M:%S'))

    def emit(self, record):
        try:
            self._buf.append(self.format(record))
        except Exception:
            pass

    def get_lines(self, level='INFO'):
        """Return formatted lines filtered by level name."""
        level = level.upper()
        if level == 'DEBUG':
            return list(self._buf)
        keep = {'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        return [l for l in self._buf if any(f'  {k}' in l for k in keep)]


# Singleton — shared by all loggers in the process
_mem_handler = _InMemoryLogHandler(maxlen=10000)


def get_cache_path():
    """Get log directory from legion.conf without importing Settings because settings uses logging and it causes a circular import"""
    try:
        from configparser import ConfigParser
        configdir = os.path.expanduser('~/.local/share/legion')
        configpath = os.path.join(configdir, 'legion.conf')
        
        if os.path.exists(configpath):
            config = ConfigParser()
            config.read(configpath)
            if config.has_option('GeneralSettings', 'log-directory'):
                log_directory = config.get('GeneralSettings', 'log-directory')
                #print(f"log_directory is: {log_directory}")
                cache_path = os.path.join(os.getcwd(), log_directory.lstrip('./'))
                #print(f"cache_path is: {cache_path}")
                log_path = os.path.join(cache_path, 'legion.log')
                #print(f"log path inside get_cache_path is: {log_path}")
                if not os.path.isfile(log_path):
                    if not os.path.isdir(cache_path):
                        os.makedirs(cache_path)
                
                return cache_path
    except Exception as e:
        print(f"Error getting log directory: {e}")
    
    # Fallback
    fallback = os.path.join(os.getcwd(), 'log')
    if not os.path.isdir(fallback):
        os.makedirs(fallback)
    return fallback



def getStartupLogger() -> Logger:
    global cachedStartupLogger
    cache_path = get_cache_path()
    logger = getOrCreateCachedLogger("legion-startup",
            os.path.join(cache_path, "legion-startup.log"), True, cachedStartupLogger)
    cachedStartupLogger = logger
    return logger


def getAppLogger() -> Logger:
    global cachedAppLogger
    cache_path = get_cache_path()
    logger = getOrCreateCachedLogger("legion",
            os.path.join(cache_path, "legion.log"), True, cachedAppLogger)
    cachedAppLogger = logger
    return logger


def getDbLogger() -> Logger:
    global cachedDbLogger
    cache_path = get_cache_path()
    logger = getOrCreateCachedLogger("legion-db",
            os.path.join(cache_path, "legion-db.log"), False, cachedDbLogger)
    cachedDbLogger = logger
    return logger


def getOrCreateCachedLogger(logName: str, logPath: str, console: bool, cachedLogger):
    if cachedLogger:
        return cachedLogger
    from rich.logging import RichHandler
    import sys
    from rich.console import Console
    
    # Create a logger with the specific name
    log = logging.getLogger(logName)
    log.setLevel(logging.DEBUG)  # Logger accepts DEBUG and above
    
    # Clear any existing handlers to avoid duplicates
    log.handlers.clear()
    
    # Add console handler if requested (INFO level)
    if console:
        console_handler = RichHandler(rich_tracebacks=True, console=Console(file=sys.stderr))
        console_handler.setLevel(logging.INFO)  # Console shows INFO and above
        console_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
        log.addHandler(console_handler)
        log.debug(f"Added console handler for {logName}")
    
    # Add rotating file handler (10 MB per file, keep 3 backups = 30 MB max per log).
    # Previously used FileHandler(mode='a') which accumulated ALL sessions into one
    # unbounded file — legion.log grew to 310 MB with no way to tell sessions apart.
    try:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            logPath, mode='a', maxBytes=10 * 1024 * 1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        log.addHandler(file_handler)
        # Write a session-start separator so individual server runs are distinguishable
        # in the rotated log file even when multiple sessions share the same file.
        import datetime as _dt
        sep = f"\n{'='*80}\nSESSION START  {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  logger={logName}\n{'='*80}"
        file_handler.stream.write(sep + '\n')
        file_handler.stream.flush()
        log.debug(f"Successfully created rotating file handler for {logName} at {logPath}")
    except Exception as e:
        log.error(f"Error creating file handler for {logName} at {logPath}: {e}")

    # In-memory handler — so /api/logs works without stdout redirect
    if _mem_handler not in log.handlers:
        log.addHandler(_mem_handler)
    
    return log
