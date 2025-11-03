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

cachedAppLogger = None
cachedStartupLogger = None
cachedDbLogger = None


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
    
    # Add file handler to write to log file (DEBUG level)
    try:
        file_handler = logging.FileHandler(logPath, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # File captures DEBUG and above
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        log.addHandler(file_handler)
        log.debug(f"Successfully created file handler for {logName} at {logPath}")
    except Exception as e:
        log.error(f"Error creating file handler for {logName} at {logPath}: {e}")
    
    return log
