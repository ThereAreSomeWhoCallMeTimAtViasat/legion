"""
Qt-free nmap XML import — calls the same logic as NmapImporter.run()
but without QThread, QSemaphore, or signals.

This is a thin wrapper around your existing NmapImporter code.
It instantiates NmapImporter and calls run() after replacing the
Qt-dependent pieces with no-ops.
"""

import logging
import threading

log = logging.getLogger('legion')

_import_lock = threading.Lock()  # replaces QSemaphore


def import_nmap_xml(project, xml_path, output=""):
    """
    Import an nmap XML file into the project database.
    Same logic as NmapImporter.run() without Qt dependencies.

    Args:
        project: the active Legion project
        xml_path: path to the .xml nmap output file
        output: optional plaintext output string
    """
    from app.importers.NmapImporter import NmapImporter
    from app.actions.updateProgress.UpdateProgressObservable import UpdateProgressObservable

    if not xml_path:
        return

    log.info(f"[nmap_import] Importing {xml_path}")

    # Create importer using your existing NmapImporter class
    observable = UpdateProgressObservable()
    importer = NmapImporter(observable, project.repositoryContainer.hostRepository)
    importer.setDB(project.database)
    importer.setHostRepository(project.repositoryContainer.hostRepository)
    importer.setFilename(xml_path)
    importer.setOutput(output)

    # Replace Qt semaphore acquire/release with threading.Lock
    # This is the only Qt piece that blocks us from calling run() directly
    original_acquire = project.database.dbsemaphore.acquire
    original_release = project.database.dbsemaphore.release

    def lock_acquire(n=1):
        _import_lock.acquire()

    def lock_release(n=1):
        try:
            _import_lock.release()
        except RuntimeError:
            pass  # already released

    project.database.dbsemaphore.acquire = lock_acquire
    project.database.dbsemaphore.release = lock_release

    try:
        # Call run() directly (same as QThread would call it)
        importer.run()
        log.info(f"[nmap_import] Import complete: {xml_path}")
    except Exception as e:
        log.error(f"[nmap_import] Import failed: {e}")
        raise
    finally:
        # Restore original semaphore
        project.database.dbsemaphore.acquire = original_acquire
        project.database.dbsemaphore.release = original_release
