"""
LEGION (https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion)
Author: Tim McLean (Viasat, Inc.)
Copyright (c) 2025-2026 Viasat, Inc.
Copyright (c) 2025 Shane William Scott (original Legion)

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful, but
    WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
    General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.

THIS SOFTWARE IS PROVIDED BY VIASAT, INC. "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES ARE DISCLAIMED. IN NO EVENT SHALL VIASAT, INC. BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE.
"""

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

# Serialises concurrent XML imports.  Previously the code patched
# project.database.dbsemaphore.acquire/release on a shared object, which
# caused a deadlock when two threads ran simultaneously: thread B's patch
# overwrote thread A's patch, breaking the acquire/release pairing so
# _import_lock was never released and every subsequent import hung forever.
_import_lock = threading.Lock()


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

    observable = UpdateProgressObservable()
    importer = NmapImporter(observable, project.repositoryContainer.hostRepository)
    importer.setDB(project.database)
    importer.setHostRepository(project.repositoryContainer.hostRepository)
    importer.setFilename(xml_path)
    importer.setOutput(output)

    # Serialise concurrent imports with a module-level lock.
    # We hold _import_lock for the entire patch→run→restore cycle so no other
    # thread can overwrite the dbsemaphore patches while we are running.
    with _import_lock:
        original_acquire = project.database.dbsemaphore.acquire
        original_release = project.database.dbsemaphore.release

        # Replace Qt semaphore with no-ops: the lock above already serialises
        # concurrent imports so we don't need the semaphore inside run().
        project.database.dbsemaphore.acquire = lambda n=1: None
        project.database.dbsemaphore.release = lambda n=1: None

        try:
            importer.run()
            log.info(f"[nmap_import] Import complete: {xml_path}")
        except Exception as e:
            log.error(f"[nmap_import] Import failed: {e}")
            raise
        finally:
            project.database.dbsemaphore.acquire = original_acquire
            project.database.dbsemaphore.release = original_release
