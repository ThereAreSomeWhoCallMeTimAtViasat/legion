if __name__ == "__main__":
    # Only run dependency checks when executed directly, not during test discovery
    import sys
    import os
    
    # Add parent directory to path so we can import legion modules
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    
    try:
        from sqlalchemy.orm.scoping import ScopedSession as scoped_session
        print("SQL Alchemy library OK")
    except ImportError:
        print("Import failed. SQL Alchemy library not found.")
        exit(1)

    try:
        from PyQt6 import QtWidgets, QtGui, QtCore
        print("PyQt6 library OK.")
    except ImportError:
        print("Import failed. PyQt6 library not found.")
        exit(1)

    try:
        import qasync
        import asyncio
        print("qasync and asyncio libraries OK.")
    except ImportError:
        print("Import failed. qasync or asyncio not found.")
        exit(1)

    try:
        from app.logic import *
        print("app.logic import OK.")
    except ImportError as e:
        print(f"Import failed for app.logic: {e}")
        exit(1)
    
    try:
        from ui.gui import *
        print("ui.gui import OK.")
    except ImportError as e:
        print(f"Import failed for ui.gui: {e}")
        exit(1)
    
    try:
        from ui.view import *
        print("ui.view import OK.")
    except ImportError as e:
        print(f"Import failed for ui.view: {e}")
        exit(1)
    
    try:
        from controller.controller import *
        print("controller.controller import OK.")
    except ImportError as e:
        print(f"Import failed for controller.controller: {e}")
        exit(1)
    
    print("All Legion class imports OK.")
