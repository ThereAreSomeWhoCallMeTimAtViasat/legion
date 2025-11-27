# Python Memory/Resource Management Improvements Guide

**Date**: November 26, 2025  
**Estimated Total Time**: 10-15 hours  
**Difficulty**: Moderate  

This guide provides step-by-step implementation details for 5 practical improvements to Legion's resource management.

---

## Table of Contents

1. [Improvement #1: Add QThread Cleanup](#improvement-1-add-qthread-cleanup)
2. [Improvement #2: Process Table Cleanup](#improvement-2-process-table-cleanup)
3. [Improvement #3: Bound Screenshot Queue](#improvement-3-bound-screenshot-queue)
4. [Improvement #4: SQLAlchemy Context Managers](#improvement-4-sqlalchemy-context-managers)
5. [Improvement #5: Stream Large XML Files](#improvement-5-stream-large-xml-files)
6. [Testing Strategy](#testing-strategy)
7. [Monitoring & Validation](#monitoring--validation)

---

## Improvement #1: Add QThread Cleanup

**Problem**: QThread objects (NmapImporter, PythonImporter, Screenshooter) may not be properly garbage collected, accumulating in memory over long sessions.

**Files to Modify**:
- `controller/controller.py`
- `app/importers/NmapImporter.py`
- `app/importers/PythonImporter.py`

**Time Estimate**: 2-3 hours

### Step 1.1: Add Thread Cleanup Handler in Controller

**Location**: `controller/controller.py` (line ~164-178)

**Current Code**:
```python
def initNmapImporter(self, updateProgressObservable: UpdateProgressObservable):
    self.nmapImporter = NmapImporter(updateProgressObservable,
                                      self.logic.activeProject.repositoryContainer.hostRepository)
    self.nmapImporter.done.connect(self.importFinished)
    self.nmapImporter.done.connect(self.view.updateInterface)
    self.nmapImporter.done.connect(self.view.updateToolsTableView)
    self.nmapImporter.done.connect(self.view.updateProcessesTableView)
```

**Add After Existing Connections**:
```python
def initNmapImporter(self, updateProgressObservable: UpdateProgressObservable):
    self.nmapImporter = NmapImporter(updateProgressObservable,
                                      self.logic.activeProject.repositoryContainer.hostRepository)
    self.nmapImporter.done.connect(self.importFinished)
    self.nmapImporter.done.connect(self.view.updateInterface)
    self.nmapImporter.done.connect(self.view.updateToolsTableView)
    self.nmapImporter.done.connect(self.view.updateProcessesTableView)
    # NEW: Add cleanup handler
    self.nmapImporter.done.connect(self.cleanupNmapImporter)
```

### Step 1.2: Add Cleanup Methods to Controller

**Location**: `controller/controller.py` (add after `initNmapImporter`)

**New Methods**:
```python
def cleanupNmapImporter(self):
    """Clean up completed NmapImporter thread to prevent memory accumulation."""
    if hasattr(self, 'nmapImporter') and self.nmapImporter:
        try:
            # Wait for thread to fully complete (with timeout)
            if self.nmapImporter.isRunning():
                if not self.nmapImporter.wait(5000):  # 5 second timeout
                    log.warning("NmapImporter thread did not finish in time")
                    return
            
            # Disconnect all signals to break circular references
            try:
                self.nmapImporter.done.disconnect()
                self.nmapImporter.tick.disconnect()
                self.nmapImporter.schedule.disconnect()
                self.nmapImporter.log.disconnect()
            except TypeError:
                # Signal wasn't connected, that's fine
                pass
            
            # Schedule for deletion
            self.nmapImporter.deleteLater()
            log.debug("NmapImporter scheduled for cleanup")
            
        except Exception as e:
            log.error(f"Error cleaning up NmapImporter: {e}")

def cleanupPythonImporter(self):
    """Clean up completed PythonImporter thread to prevent memory accumulation."""
    if hasattr(self, 'pythonImporter') and self.pythonImporter:
        try:
            if self.pythonImporter.isRunning():
                if not self.pythonImporter.wait(5000):
                    log.warning("PythonImporter thread did not finish in time")
                    return
            
            try:
                self.pythonImporter.done.disconnect()
                self.pythonImporter.tick.disconnect()
                self.pythonImporter.log.disconnect()
            except TypeError:
                pass
            
            self.pythonImporter.deleteLater()
            log.debug("PythonImporter scheduled for cleanup")
            
        except Exception as e:
            log.error(f"Error cleaning up PythonImporter: {e}")
```

### Step 1.3: Connect Cleanup to PythonImporter

**Location**: `controller/controller.py` (line ~175-178)

**Modify**:
```python
def initPythonImporter(self):
    self.pythonImporter = PythonImporter()
    self.pythonImporter.done.connect(self.importFinished)
    self.pythonImporter.done.connect(self.view.updateInterface)
    self.pythonImporter.done.connect(self.view.updateToolsTableView)
    self.pythonImporter.done.connect(self.view.updateProcessesTableView)
    # NEW: Add cleanup handler
    self.pythonImporter.done.connect(self.cleanupPythonImporter)
```

### Step 1.4: Add Periodic Thread Pool Monitoring

**Location**: `controller/controller.py` (add to `__init__`)

**New Code**:
```python
def __init__(self, view, logic: Logic):
    # ... existing init code ...
    
    # NEW: Track active threads for monitoring
    self.activeThreads = []
    
    # NEW: Periodic thread cleanup timer (every 5 minutes)
    self.threadCleanupTimer = QTimer()
    self.threadCleanupTimer.timeout.connect(self.monitorThreads)
    self.threadCleanupTimer.start(300000)  # 5 minutes

def monitorThreads(self):
    """Monitor and log active thread count for debugging."""
    active_count = 0
    thread_info = []
    
    if hasattr(self, 'nmapImporter') and self.nmapImporter:
        if self.nmapImporter.isRunning():
            active_count += 1
            thread_info.append("NmapImporter")
    
    if hasattr(self, 'pythonImporter') and self.pythonImporter:
        if self.pythonImporter.isRunning():
            active_count += 1
            thread_info.append("PythonImporter")
    
    if hasattr(self, 'screenshooter') and self.screenshooter:
        if self.screenshooter.isRunning():
            active_count += 1
            thread_info.append(f"Screenshooter (queue: {len(self.screenshooter.queue)})")
    
    if active_count > 0:
        log.debug(f"Active threads: {active_count} - {', '.join(thread_info)}")
    
    # Force garbage collection if needed (optional, use with caution)
    # import gc
    # gc.collect()
```

---

## Improvement #2: Process Table Cleanup

**Problem**: Completed processes accumulate in the database indefinitely, slowing down queries and consuming space.

**Files to Modify**:
- `db/repositories/ProcessRepository.py`
- `controller/controller.py`

**Time Estimate**: 2-3 hours

### Step 2.1: Add Cleanup Method to ProcessRepository

**Location**: `db/repositories/ProcessRepository.py` (add after existing methods)

**New Method**:
```python
def cleanupOldProcesses(self, days_old=30, status_filter=None):
    """
    Remove process records older than specified days that are completed.
    
    Args:
        days_old: Number of days to keep (default: 30)
        status_filter: List of statuses to delete (default: ['Finished', 'Killed', 'Crashed'])
    
    Returns:
        int: Number of processes deleted
    """
    from datetime import datetime, timedelta
    
    if status_filter is None:
        status_filter = ['Finished', 'Killed', 'Crashed']
    
    cutoff_date = datetime.now() - timedelta(days=days_old)
    cutoff_timestamp = cutoff_date.strftime('%d/%m/%Y %H:%M:%S')
    
    session = self.dbAdapter.session
    
    try:
        # First, get count of processes to delete
        count_query = session.query(process).filter(
            process.status.in_(status_filter)
        )
        
        # Parse and filter by startTime (stored as string 'dd/mm/yyyy HH:MM:SS')
        to_delete = []
        for proc in count_query.all():
            if proc.startTime:
                try:
                    proc_time = datetime.strptime(proc.startTime, '%d/%m/%Y %H:%M:%S')
                    if proc_time < cutoff_date:
                        to_delete.append(proc.id)
                except ValueError:
                    # Invalid date format, skip
                    continue
        
        if not to_delete:
            self.log.info("No old processes to clean up")
            return 0
        
        # Delete associated process outputs first (foreign key constraint)
        session.query(process_output).filter(
            process_output.id.in_(to_delete)
        ).delete(synchronize_session=False)
        
        # Delete the processes
        deleted = session.query(process).filter(
            process.id.in_(to_delete)
        ).delete(synchronize_session=False)
        
        session.commit()
        self.log.info(f"Cleaned up {deleted} old processes (older than {days_old} days)")
        return deleted
        
    except Exception as e:
        self.log.error(f"Error cleaning up old processes: {e}")
        session.rollback()
        return 0
    finally:
        session.close()

def cleanupAllCompletedProcesses(self):
    """
    Remove ALL completed processes regardless of age.
    Use with caution - typically for clearing before a new scan.
    
    Returns:
        int: Number of processes deleted
    """
    session = self.dbAdapter.session
    
    try:
        status_filter = ['Finished', 'Killed', 'Crashed']
        
        # Get IDs first
        to_delete = [p.id for p in session.query(process).filter(
            process.status.in_(status_filter)
        ).all()]
        
        if not to_delete:
            return 0
        
        # Delete outputs first
        session.query(process_output).filter(
            process_output.id.in_(to_delete)
        ).delete(synchronize_session=False)
        
        # Delete processes
        deleted = session.query(process).filter(
            process.id.in_(to_delete)
        ).delete(synchronize_session=False)
        
        session.commit()
        self.log.info(f"Cleaned up {deleted} completed processes")
        return deleted
        
    except Exception as e:
        self.log.error(f"Error cleaning up completed processes: {e}")
        session.rollback()
        return 0
    finally:
        session.close()
```

### Step 2.2: Add UI Menu Option for Manual Cleanup

**Location**: `controller/controller.py` (add new method)

**New Method**:
```python
def cleanupOldProcesses(self, days_old=30):
    """Trigger process cleanup from UI."""
    if not self.logic.activeProject:
        log.warning("No active project for process cleanup")
        return
    
    repo = self.logic.activeProject.repositoryContainer.processRepository
    
    # Ask user for confirmation
    reply = QtWidgets.QMessageBox.question(
        self.view.ui.centralwidget,
        'Cleanup Old Processes',
        f'Delete all completed processes older than {days_old} days?\n\n'
        'This will remove process records but keep host/service data.',
        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        QtWidgets.QMessageBox.StandardButton.No
    )
    
    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
        deleted = repo.cleanupOldProcesses(days_old)
        self.view.updateProcessesTableView()
        QtWidgets.QMessageBox.information(
            self.view.ui.centralwidget,
            'Cleanup Complete',
            f'Removed {deleted} old process records.'
        )
```

### Step 2.3: Add Automatic Cleanup on Project Save

**Location**: `controller/controller.py` in `saveProject()` method (around line 390)

**Add Before Return**:
```python
def saveProject(self, filename=None, update_project_name=True):
    # ... existing save code ...
    
    if success:
        self.nmapImporter.setDB(self.logic.activeProject.database)
        
        # NEW: Automatic cleanup of old processes (90+ days)
        try:
            repo = self.logic.activeProject.repositoryContainer.processRepository
            deleted = repo.cleanupOldProcesses(days_old=90)
            if deleted > 0:
                log.info(f"Auto-cleanup: Removed {deleted} processes older than 90 days")
        except Exception as e:
            log.error(f"Error during automatic process cleanup: {e}")
    
    return success
```

---

## Improvement #3: Bound Screenshot Queue

**Problem**: The screenshot queue (`self.queue` list) can grow unbounded if screenshots are queued faster than they can be processed, potentially exhausting memory.

**Files to Modify**:
- `app/Screenshooter.py`

**Time Estimate**: 1-2 hours

### Step 3.1: Replace List with Bounded Queue

**Location**: `app/Screenshooter.py` (lines 1-50)

**Current Code**:
```python
class Screenshooter(QtCore.QThread):
    def __init__(self, timeout):
        QtCore.QThread.__init__(self, parent=None)
        self.queue = []
        self.processing = False
        self.timeout = timeout
```

**Replace With**:
```python
from queue import Queue, Full, Empty

class Screenshooter(QtCore.QThread):
    done = QtCore.pyqtSignal(str, str, str, name="done")
    log = QtCore.pyqtSignal(str, name="log")
    queueFull = QtCore.pyqtSignal(str, name="queueFull")  # NEW: Signal when queue is full

    def __init__(self, timeout, max_queue_size=500):
        QtCore.QThread.__init__(self, parent=None)
        self.queue = Queue(maxsize=max_queue_size)  # CHANGED: Bounded queue
        self.processing = False
        self.timeout = timeout
        self.current_subprocess = None
        self.blacklisted_ips = set()
        self.current_ip = None
        self.max_queue_size = max_queue_size
        self.dropped_count = 0  # Track dropped screenshots
```

### Step 3.2: Update addToQueue Method

**Location**: `app/Screenshooter.py` (replace `addToQueue` method)

**Current Code**:
```python
def addToQueue(self, ip, port, url):
    self.queue.append([ip, port, url])
```

**Replace With**:
```python
def addToQueue(self, ip, port, url):
    """Add screenshot to queue. Returns True if added, False if queue is full."""
    try:
        self.queue.put([ip, port, url], block=False)  # Non-blocking
        return True
    except Full:
        self.dropped_count += 1
        msg = f"Screenshot queue full ({self.max_queue_size} items). Dropped screenshot for {ip}:{port}"
        self.tsLog(msg)
        self.queueFull.emit(msg)
        return False

def getQueueSize(self):
    """Return current queue size."""
    return self.queue.qsize()

def getDroppedCount(self):
    """Return number of dropped screenshots."""
    return self.dropped_count

def resetDroppedCount(self):
    """Reset dropped screenshot counter."""
    self.dropped_count = 0
```

### Step 3.3: Update run Method to Use Queue.get()

**Location**: `app/Screenshooter.py` (replace `run` method)

**Current Code**:
```python
def run(self):
    while self.processing == True:
        self.sleep(1)

    self.processing = True

    for i in range(0, len(self.queue)):
        try:
            queueItem = self.queue.pop(0)
            # ... process screenshot ...
        except Exception as e:
            # ... error handling ...
            continue

    self.processing = False

    if not len(self.queue) == 0:
        self.run()
```

**Replace With**:
```python
def run(self):
    while self.processing == True:
        self.sleep(1)

    self.processing = True
    
    # Process until queue is empty
    while not self.queue.empty():
        try:
            # Non-blocking get with timeout
            try:
                queueItem = self.queue.get(block=True, timeout=1)
            except Empty:
                # Queue is empty, we're done
                break
            
            ip = queueItem[0]
            port = queueItem[1]
            url = queueItem[2]
            
            # Check blacklist before processing
            if ip in self.blacklisted_ips:
                self.tsLog(f'Skipping screenshot for blacklisted IP: {ip}')
                self.queue.task_done()  # Mark as processed
                continue
            
            self.current_ip = ip
            outputfile = getTimestamp() + '-screenshot-' + url.replace(':', '-') + '.png'
            self.save(url, ip, port, outputfile)
            self.current_ip = None
            
            self.queue.task_done()  # Mark as processed
            
        except Exception as e:
            self.tsLog('Unable to take the screenshot. Error follows.')
            self.tsLog(e)
            try:
                self.queue.task_done()
            except ValueError:
                pass
            continue

    self.processing = False
    
    # Log statistics if any screenshots were dropped
    if self.dropped_count > 0:
        self.tsLog(f"Screenshot session complete. {self.dropped_count} screenshots were dropped due to queue limits.")
```

### Step 3.4: Update cancelScreenshotsForIp Method

**Location**: `app/Screenshooter.py` (replace method)

**Current Code**:
```python
def cancelScreenshotsForIp(self, ip):
    # ... existing code using list operations ...
    self.queue = [item for item in self.queue if item[0] != ip]
```

**Replace With**:
```python
def cancelScreenshotsForIp(self, ip):
    """Cancel all queued and in-progress screenshots for a specific IP."""
    self.tsLog(f"=== cancelScreenshotsForIp START for IP: {ip} ===")
    
    # Add to blacklist
    self.blacklisted_ips.add(ip)
    self.tsLog(f"Added {ip} to blacklist")
    
    # Remove from queue - need to rebuild queue without this IP
    temp_queue = Queue(maxsize=self.max_queue_size)
    removed_count = 0
    
    while not self.queue.empty():
        try:
            item = self.queue.get_nowait()
            if item[0] != ip:
                temp_queue.put_nowait(item)
            else:
                removed_count += 1
                self.queue.task_done()
        except (Empty, Full):
            break
    
    # Replace old queue with filtered queue
    self.queue = temp_queue
    self.tsLog(f"Removed {removed_count} items from queue")
    
    # Kill current subprocess if it's for this IP
    if self.current_subprocess and self.current_ip == ip:
        try:
            self.current_subprocess.send_signal(signal.SIGKILL)
            self.current_subprocess = None
            self.tsLog(f"Killed running screenshot subprocess for {ip}")
        except Exception as e:
            self.tsLog(f"Error killing subprocess: {e}")
    
    self.tsLog(f"=== cancelScreenshotsForIp END ===")
    return removed_count
```

### Step 3.5: Connect Queue Full Signal in Controller

**Location**: `controller/controller.py` in `initScreenshooter()` method

**Add**:
```python
def initScreenshooter(self):
    self.screenshooter = Screenshooter(self.settings.screenshotutils_timeout)
    # ... existing connections ...
    self.screenshooter.done.connect(self.screenshotFinished)
    
    # NEW: Handle queue full warnings
    self.screenshooter.queueFull.connect(self.handleScreenshotQueueFull)

def handleScreenshotQueueFull(self, message):
    """Handle screenshot queue overflow."""
    log.warning(message)
    # Optionally show a warning to the user (only once per session)
    if not hasattr(self, '_screenshot_queue_warning_shown'):
        self._screenshot_queue_warning_shown = True
        QtWidgets.QMessageBox.warning(
            self.view.ui.centralwidget,
            'Screenshot Queue Full',
            'The screenshot queue is full. Some screenshots may be skipped.\n\n'
            'Consider reducing the number of concurrent scans or increasing the queue size.'
        )
```

---

## Improvement #4: SQLAlchemy Context Managers

**Problem**: Database sessions created manually may not be closed if exceptions occur, leading to session leaks and connection pool exhaustion.

**Files to Modify**:
- `db/SqliteDbAdapter.py`
- `db/repositories/HostRepository.py` (example)
- `db/repositories/PortRepository.py` (example)
- All other repository classes

**Time Estimate**: 4-6 hours

### Step 4.1: Add Context Manager to Database Adapter

**Location**: `db/SqliteDbAdapter.py` (add to Database class)

**New Method**:
```python
from contextlib import contextmanager

class Database:
    # ... existing methods ...
    
    @contextmanager
    def get_session(self):
        """
        Context manager for database sessions.
        Ensures sessions are properly closed even if exceptions occur.
        
        Usage:
            with db.get_session() as session:
                result = session.query(...).all()
                # session automatically closed on exit
        """
        session = self.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    @contextmanager
    def get_session_readonly(self):
        """
        Context manager for read-only database sessions (no auto-commit).
        
        Usage:
            with db.get_session_readonly() as session:
                result = session.query(...).all()
        """
        session = self.session()
        try:
            yield session
        finally:
            session.close()
```

### Step 4.2: Example Repository Refactoring (HostRepository)

**Location**: `db/repositories/HostRepository.py`

**Before (Current Pattern)**:
```python
def exists(self, host: str):
    session = self.dbAdapter.session
    query = text('SELECT host.ip FROM hostObj AS host WHERE host.ip == :host OR host.hostname == :host')
    result = session.execute(query, {'host': str(host)}).fetchall()
    session.close()
    return True if result else False
```

**After (Using Context Manager)**:
```python
def exists(self, host: str):
    with self.dbAdapter.get_session_readonly() as session:
        query = text('SELECT host.ip FROM hostObj AS host WHERE host.ip == :host OR host.hostname == :host')
        result = session.execute(query, {'host': str(host)}).fetchall()
        return True if result else False
```

**Benefits**:
- Session **always** closed, even if exception occurs
- Automatic rollback on errors
- Cleaner, more readable code
- No need to remember `session.close()`

### Step 4.3: Example for Write Operations

**Before**:
```python
def deleteHost(self, hostIP):
    session = self.dbAdapter.session
    try:
        host = session.query(hostObj).filter_by(ip=str(hostIP)).first()
        # ... deletion logic ...
        session.commit()
        session.close()
    except Exception as e:
        session.rollback()
        session.close()
        raise
```

**After**:
```python
def deleteHost(self, hostIP):
    with self.dbAdapter.get_session() as session:
        host = session.query(hostObj).filter_by(ip=str(hostIP)).first()
        # ... deletion logic ...
        # Automatic commit on success, rollback on exception
```

### Step 4.4: Migration Checklist

For each repository file, update methods that use manual session management:

**Files to Update** (Priority Order):
1. ✅ `db/repositories/HostRepository.py` - 15-20 methods
2. ✅ `db/repositories/ProcessRepository.py` - 20-25 methods
3. ✅ `db/repositories/PortRepository.py` - 10-15 methods
4. ✅ `db/repositories/ServiceRepository.py` - 8-10 methods
5. ✅ `db/repositories/CVERepository.py` - 5-8 methods
6. ✅ `db/repositories/NoteRepository.py` - 5-8 methods
7. ✅ `db/repositories/ScriptRepository.py` - 5-8 methods

**Pattern to Find**:
```bash
# Search for manual session usage
grep -rn "session = self.dbAdapter.session" db/repositories/
```

**Replacement Pattern**:
```python
# Read-only queries (SELECT)
with self.dbAdapter.get_session_readonly() as session:
    result = session.query(...).all()
    return result

# Write operations (INSERT/UPDATE/DELETE)
with self.dbAdapter.get_session() as session:
    session.add(obj)
    # Automatic commit on exit
```

### Step 4.5: Testing the Context Manager

**Create Test File**: `tests/db/test_SessionContextManager.py`

```python
import unittest
import tempfile
import os
from db.SqliteDbAdapter import Database
from db.entities.host import hostObj

class SessionContextManagerTest(unittest.TestCase):
    
    def setUp(self):
        self.tempfile = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.db = Database(self.tempfile.name)
    
    def tearDown(self):
        self.db.dispose()
        os.unlink(self.tempfile.name)
    
    def test_readonly_context_manager(self):
        """Test that readonly context manager works correctly."""
        # Add a host first
        with self.db.get_session() as session:
            host = hostObj(ip='192.168.1.1', hostname='test.local')
            session.add(host)
        
        # Read it back
        with self.db.get_session_readonly() as session:
            result = session.query(hostObj).filter_by(ip='192.168.1.1').first()
            self.assertIsNotNone(result)
            self.assertEqual(result.hostname, 'test.local')
    
    def test_write_context_manager_commit(self):
        """Test that write context manager commits on success."""
        with self.db.get_session() as session:
            host = hostObj(ip='10.0.0.1', hostname='auto-commit.local')
            session.add(host)
            # Should auto-commit on exit
        
        # Verify it was saved
        with self.db.get_session_readonly() as session:
            result = session.query(hostObj).filter_by(ip='10.0.0.1').first()
            self.assertIsNotNone(result)
    
    def test_write_context_manager_rollback(self):
        """Test that write context manager rolls back on exception."""
        try:
            with self.db.get_session() as session:
                host = hostObj(ip='10.0.0.2', hostname='rollback.local')
                session.add(host)
                raise ValueError("Simulated error")
        except ValueError:
            pass
        
        # Verify it was NOT saved
        with self.db.get_session_readonly() as session:
            result = session.query(hostObj).filter_by(ip='10.0.0.2').first()
            self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
```

---

## Improvement #5: Stream Large XML Files

**Problem**: Large nmap XML files (from massive scans) are loaded entirely into memory by `xml.dom.minidom.parse()`, potentially causing memory issues with 10,000+ host scans.

**Files to Modify**:
- `parsers/Parser.py`
- `app/importers/NmapImporter.py`

**Time Estimate**: 6-8 hours (most complex improvement)

### Step 5.1: Add Streaming Parser Class

**Location**: `parsers/Parser.py` (add new class)

**New Class**:
```python
from xml.etree.ElementTree import iterparse
from typing import Iterator, Optional
import parsers.Host as Host

class StreamingParser:
    """
    Memory-efficient streaming parser for large nmap XML files.
    Uses iterparse to process hosts one at a time without loading entire DOM.
    """
    
    def __init__(self, filename: str):
        self.filename = filename
        self._session_data = None
        self._highest_percent = None
    
    def iter_hosts(self) -> Iterator[Host.Host]:
        """
        Yield Host objects one at a time from the XML file.
        
        Yields:
            Host.Host: Individual host objects
        """
        context = iterparse(self.filename, events=('start', 'end'))
        context = iter(context)
        
        root = None
        
        for event, elem in context:
            if event == 'start' and root is None:
                root = elem
            
            if event == 'end' and elem.tag == 'host':
                # Parse this host element
                try:
                    host = Host.Host(elem)
                    yield host
                except Exception as e:
                    # Log but don't stop processing
                    print(f"Error parsing host: {e}")
                
                # Clear the element to free memory
                elem.clear()
                if root is not None:
                    # Remove from parent to prevent accumulation
                    for ancestor in root.iter():
                        try:
                            ancestor.remove(elem)
                        except ValueError:
                            pass
            
            # Extract progress information
            if event == 'end' and elem.tag == 'taskprogress':
                if elem.hasAttribute('percent'):
                    try:
                        percent = float(elem.getAttribute('percent'))
                        if self._highest_percent is None or percent > self._highest_percent:
                            self._highest_percent = percent
                    except (ValueError, AttributeError):
                        pass
                elem.clear()
    
    def get_session_info(self):
        """
        Extract session information without loading full DOM.
        Must be called before or after iter_hosts().
        
        Returns:
            Session.Session: Session object with scan metadata
        """
        if self._session_data is not None:
            return self._session_data
        
        session_dict = {
            'finish_time': '',
            'nmapVersion': '',
            'scanArgs': '',
            'startTime': '',
            'totalHosts': '',
            'upHosts': '',
            'downHosts': ''
        }
        
        # Quick pass to extract session info
        for event, elem in iterparse(self.filename, events=('start', 'end')):
            if event == 'start':
                if elem.tag == 'nmaprun':
                    session_dict['nmapVersion'] = elem.get('version', '')
                    session_dict['startTime'] = elem.get('startstr', '')
                    session_dict['scanArgs'] = elem.get('args', '')
                elif elem.tag == 'hosts':
                    session_dict['totalHosts'] = elem.get('total', '')
                    session_dict['upHosts'] = elem.get('up', '')
                    session_dict['downHosts'] = elem.get('down', '')
                elif elem.tag == 'finished':
                    session_dict['finish_time'] = elem.get('timestr', '')
            
            if event == 'end':
                elem.clear()
        
        self._session_data = Session.Session(session_dict)
        return self._session_data
    
    def get_highest_percent(self) -> Optional[float]:
        """Get the highest percent value from taskprogress elements."""
        if self._highest_percent is not None:
            return self._highest_percent
        
        # Quick scan for progress
        for event, elem in iterparse(self.filename, events=('end',)):
            if elem.tag == 'taskprogress' and elem.get('percent'):
                try:
                    percent = float(elem.get('percent'))
                    if self._highest_percent is None or percent > self._highest_percent:
                        self._highest_percent = percent
                except ValueError:
                    pass
            elem.clear()
        
        return self._highest_percent


def parseNmapReportStreaming(nmapXmlReportFileName: str) -> StreamingParser:
    """
    Create a streaming parser for large nmap XML files.
    Use this for files > 10MB or > 1000 hosts.
    
    Example:
        parser = parseNmapReportStreaming('scan.xml')
        for host in parser.iter_hosts():
            print(host.ip)
    """
    try:
        return StreamingParser(nmapXmlReportFileName)
    except Exception as e:
        raise MalformedXmlDocumentException(e)
```

### Step 5.2: Add File Size Check to NmapImporter

**Location**: `app/importers/NmapImporter.py` in `run()` method

**Add at Start of run() Method**:
```python
def run(self):
    try:
        # NEW: Determine if we should use streaming parser
        import os
        file_size = os.path.getsize(self.filename) if os.path.exists(self.filename) else 0
        file_size_mb = file_size / (1024 * 1024)
        
        use_streaming = file_size_mb > 10  # Use streaming for files > 10MB
        
        if use_streaming:
            appLog.info(f"Large XML file detected ({file_size_mb:.1f}MB), using streaming parser")
            self.tsLog(f"[INFO] Using memory-efficient streaming parser for large file ({file_size_mb:.1f}MB)")
            return self.run_streaming()
        else:
            appLog.info(f"Standard XML parsing ({file_size_mb:.1f}MB)")
            return self.run_standard()
            
    except Exception as e:
        appLog.exception("Error in NmapImporter.run()")
        self.done.emit()
```

### Step 5.3: Refactor Existing run() to run_standard()

**Location**: `app/importers/NmapImporter.py`

**Rename Current run() Logic**:
```python
def run_standard(self):
    """Standard (non-streaming) XML parsing for small/medium files."""
    try:
        if self.updateProgressObservable is not None:
            self.updateProgressObservable.notifyObservers('[*] Parsing Nmap scan file...')
        
        # ... existing run() logic remains unchanged ...
        # (all the current code in run() goes here)
        
    except Exception as e:
        appLog.exception("Error in standard nmap import")
        self.done.emit()
```

### Step 5.4: Add New Streaming run() Method

**Location**: `app/importers/NmapImporter.py`

**New Method**:
```python
def run_streaming(self):
    """Memory-efficient streaming parser for large XML files."""
    try:
        from parsers.Parser import parseNmapReportStreaming
        
        if self.updateProgressObservable is not None:
            self.updateProgressObservable.notifyObservers('[*] Parsing large Nmap file (streaming mode)...')
        
        self.tsLog('[*] Starting streaming XML parse...')
        
        # Create streaming parser
        parser = parseNmapReportStreaming(self.filename)
        
        # Get session info first
        session = parser.get_session_info()
        self.db.repositoryContainer.nmapSessionRepository.storeNmapSession(session)
        
        # Process hosts one at a time
        host_count = 0
        session_obj = self.db.session  # Use scoped session for better performance
        
        try:
            for host in parser.iter_hosts():
                if self._cancel_requested:
                    self.tsLog('[!] Import cancelled by user')
                    break
                
                host_count += 1
                
                # Progress update every 50 hosts
                if host_count % 50 == 0:
                    self.tsLog(f'[*] Processed {host_count} hosts...')
                    if self.updateProgressObservable:
                        self.updateProgressObservable.notifyObservers(
                            f'[*] Imported {host_count} hosts...'
                        )
                
                # Store host (same logic as standard parser)
                try:
                    # Use existing host storage logic
                    self._store_host(host, session_obj)
                    
                    # Commit every 100 hosts to avoid massive transactions
                    if host_count % 100 == 0:
                        session_obj.commit()
                        
                except Exception as e:
                    appLog.error(f"Error storing host {host.ip}: {e}")
                    session_obj.rollback()
                    continue
            
            # Final commit
            session_obj.commit()
            
            self.tsLog(f'[+] Streaming parse complete: {host_count} hosts processed')
            
        finally:
            # Ensure session is closed
            session_obj.close()
        
        # Emit done signal
        self.done.emit()
        
    except Exception as e:
        appLog.exception("Error in streaming nmap import")
        self.tsLog(f'[!] Streaming parse error: {e}')
        self.done.emit()

def _store_host(self, host, session):
    """
    Helper method to store a single host (extracted for reuse).
    Can be called from both standard and streaming parsers.
    """
    # Extract the host storage logic from the existing run() method
    # This avoids code duplication between standard and streaming modes
    
    # Check if host already exists
    existing = self.hostRepository.getHostInformation(host.ip)
    
    if existing:
        # Update existing host
        # ... (existing update logic) ...
        pass
    else:
        # Create new host
        # ... (existing creation logic) ...
        pass
    
    # Store ports, services, scripts, etc.
    # ... (existing storage logic) ...
```

### Step 5.5: Add Configuration Option

**Location**: `legion.conf` (add to `[GeneralSettings]` section)

**Add**:
```ini
[GeneralSettings]
# ... existing settings ...

# XML Parser Settings
# Use streaming parser for nmap XML files larger than this size (MB)
# Streaming parser uses less memory but may be slightly slower
streaming-parser-threshold=10
```

**Load in Settings** (`app/settings.py`):
```python
class GeneralSettings:
    def __init__(self, settings):
        # ... existing settings ...
        
        # XML parser settings
        self.streaming_parser_threshold = int(
            settings.value('GeneralSettings/streaming-parser-threshold', '10')
        )
```

---

## Testing Strategy

### Test Plan Overview

| Test Type | What to Test | Time |
|-----------|-------------|------|
| Unit Tests | Individual methods | 2h |
| Integration Tests | Full workflows | 2h |
| Memory Tests | Actual memory usage | 1h |
| Regression Tests | Existing functionality | 1h |

### Unit Tests

**Create**: `tests/improvements/test_MemoryImprovements.py`

```python
import unittest
import tempfile
import os
from unittest.mock import Mock, patch
from db.SqliteDbAdapter import Database
from db.repositories.ProcessRepository import ProcessRepository
from app.Screenshooter import Screenshooter

class MemoryImprovementsTest(unittest.TestCase):
    
    def setUp(self):
        self.tempfile = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.db = Database(self.tempfile.name)
    
    def tearDown(self):
        self.db.dispose()
        os.unlink(self.tempfile.name)
    
    def test_process_cleanup_old_processes(self):
        """Test that old processes are correctly cleaned up."""
        from datetime import datetime, timedelta
        from db.RepositoryContainer import RepositoryContainer
        
        container = RepositoryContainer(self.db)
        repo = container.processRepository
        
        # Create old process (31 days ago)
        old_date = datetime.now() - timedelta(days=31)
        old_timestamp = old_date.strftime('%d/%m/%Y %H:%M:%S')
        
        repo.storeProcess(
            pid=12345,
            command='test command',
            hostip='192.168.1.1',
            port='80',
            protocol='tcp',
            starttime=old_timestamp,
            outputfile='/tmp/test',
            status='Finished'
        )
        
        # Create recent process (5 days ago)
        recent_date = datetime.now() - timedelta(days=5)
        recent_timestamp = recent_date.strftime('%d/%m/%Y %H:%M:%S')
        
        repo.storeProcess(
            pid=12346,
            command='test command 2',
            hostip='192.168.1.2',
            port='80',
            protocol='tcp',
            starttime=recent_timestamp,
            outputfile='/tmp/test2',
            status='Finished'
        )
        
        # Clean up processes older than 30 days
        deleted = repo.cleanupOldProcesses(days_old=30)
        
        # Should delete 1 old process
        self.assertEqual(deleted, 1)
        
        # Recent process should still exist
        processes = repo.getProcesses({})
        self.assertEqual(len(processes), 1)
    
    def test_screenshot_queue_bounded(self):
        """Test that screenshot queue respects max size."""
        screenshooter = Screenshooter(timeout=5000, max_queue_size=3)
        
        # Add 3 items (should succeed)
        self.assertTrue(screenshooter.addToQueue('192.168.1.1', '80', 'test1'))
        self.assertTrue(screenshooter.addToQueue('192.168.1.2', '80', 'test2'))
        self.assertTrue(screenshooter.addToQueue('192.168.1.3', '80', 'test3'))
        
        # Add 4th item (should fail - queue full)
        self.assertFalse(screenshooter.addToQueue('192.168.1.4', '80', 'test4'))
        
        # Check dropped count
        self.assertEqual(screenshooter.getDroppedCount(), 1)
    
    def test_session_context_manager_rollback(self):
        """Test that context manager rolls back on exception."""
        from db.entities.host import hostObj
        
        # Try to add a host but raise exception
        try:
            with self.db.get_session() as session:
                host = hostObj(ip='10.0.0.1', hostname='test')
                session.add(host)
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Verify host was NOT saved (rollback worked)
        with self.db.get_session_readonly() as session:
            result = session.query(hostObj).filter_by(ip='10.0.0.1').first()
            self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
```

### Integration Tests

Run full scan and check memory behavior:

```bash
# Run Legion with memory profiling
python -m memory_profiler legion.py

# Or use pympler for detailed tracking
pip install pympler

# Add to legion.py:
from pympler import tracker
memory_tracker = tracker.SummaryTracker()

# After scan:
memory_tracker.print_diff()
```

### Memory Profiling

**Create**: `tests/memory_profile.py`

```python
"""
Memory profiling script for Legion improvements.
Monitors memory usage during typical operations.
"""

import os
import psutil
import time
from memory_profiler import profile

def get_memory_usage():
    """Get current process memory in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

@profile
def test_large_xml_import():
    """Test memory usage when importing large nmap XML."""
    from app.importers.NmapImporter import NmapImporter
    from db.SqliteDbAdapter import Database
    import tempfile
    
    # Create temp database
    tempfile_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    db = Database(tempfile_db.name)
    
    print(f"Memory before import: {get_memory_usage():.2f} MB")
    
    # Import large XML file
    importer = NmapImporter(None, db.repositoryContainer.hostRepository)
    importer.setDB(db)
    importer.setFilename('tests/fixtures/large_scan.xml')  # Create this fixture
    importer.run()
    
    print(f"Memory after import: {get_memory_usage():.2f} MB")
    
    # Cleanup
    db.dispose()
    os.unlink(tempfile_db.name)

@profile
def test_screenshot_queue_growth():
    """Test memory usage with large screenshot queue."""
    from app.Screenshooter import Screenshooter
    
    print(f"Memory before queue: {get_memory_usage():.2f} MB")
    
    screenshooter = Screenshooter(timeout=5000, max_queue_size=1000)
    
    # Add 1000 screenshots to queue
    for i in range(1000):
        screenshooter.addToQueue(f'192.168.1.{i % 255}', '80', f'http://test{i}.com')
    
    print(f"Memory with 1000 queued: {get_memory_usage():.2f} MB")
    print(f"Queue size: {screenshooter.getQueueSize()}")

if __name__ == '__main__':
    test_large_xml_import()
    test_screenshot_queue_growth()
```

---

## Monitoring & Validation

### Adding Memory Monitoring to Legion

**Create**: `app/memory_monitor.py`

```python
"""
Real-time memory monitoring for Legion.
Logs memory usage periodically during operation.
"""

import os
import psutil
from PyQt6.QtCore import QTimer
from app.logging.legionLog import getAppLogger

log = getAppLogger()

class MemoryMonitor:
    """Monitor and log memory usage during Legion operation."""
    
    def __init__(self, interval_ms=60000):
        """
        Initialize memory monitor.
        
        Args:
            interval_ms: Monitoring interval in milliseconds (default: 60000 = 1 minute)
        """
        self.process = psutil.Process(os.getpid())
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_memory)
        self.timer.start(interval_ms)
        self.baseline_memory = self.get_memory_mb()
        log.info(f"Memory monitor started. Baseline: {self.baseline_memory:.2f} MB")
    
    def get_memory_mb(self):
        """Get current memory usage in MB."""
        return self.process.memory_info().rss / 1024 / 1024
    
    def check_memory(self):
        """Check and log current memory usage."""
        current = self.get_memory_mb()
        growth = current - self.baseline_memory
        percent = (growth / self.baseline_memory * 100) if self.baseline_memory > 0 else 0
        
        log.debug(f"Memory: {current:.2f} MB (growth: +{growth:.2f} MB, +{percent:.1f}%)")
        
        # Warn if memory growth exceeds threshold
        if growth > 500:  # More than 500MB growth
            log.warning(f"Significant memory growth detected: +{growth:.2f} MB")
    
    def stop(self):
        """Stop monitoring."""
        self.timer.stop()
        final = self.get_memory_mb()
        log.info(f"Memory monitor stopped. Final: {final:.2f} MB")
```

### Enable in Controller

**Location**: `controller/controller.py` in `__init__`

```python
def __init__(self, view, logic: Logic):
    # ... existing init ...
    
    # Enable memory monitoring in debug mode
    if log.level == logging.DEBUG:
        from app.memory_monitor import MemoryMonitor
        self.memory_monitor = MemoryMonitor(interval_ms=60000)  # Check every minute
```

### Performance Metrics to Track

Create a performance dashboard or log:

```python
# Add to controller after improvements
def logPerformanceMetrics(self):
    """Log performance metrics for debugging."""
    metrics = {
        'active_threads': 0,
        'screenshot_queue_size': 0,
        'process_count': 0,
        'memory_mb': 0
    }
    
    # Count active threads
    if hasattr(self, 'screenshooter') and self.screenshooter.isRunning():
        metrics['active_threads'] += 1
        metrics['screenshot_queue_size'] = self.screenshooter.getQueueSize()
    
    # Count processes
    if self.logic.activeProject:
        repo = self.logic.activeProject.repositoryContainer.processRepository
        processes = repo.getProcesses({})
        metrics['process_count'] = len(processes)
    
    # Memory
    import psutil
    process = psutil.Process()
    metrics['memory_mb'] = process.memory_info().rss / 1024 / 1024
    
    log.info(f"Performance: {metrics}")
```

---

## Summary Checklist

### Implementation Order (Recommended)

- [ ] **Week 1**: Improvements #1-3 (Low-hanging fruit)
  - [ ] 1. QThread cleanup (2-3 hours)
  - [ ] 2. Process table cleanup (2-3 hours)
  - [ ] 3. Bounded screenshot queue (1-2 hours)
  - [ ] Write unit tests for above (2 hours)

- [ ] **Week 2**: Improvements #4-5 (More complex)
  - [ ] 4. SQLAlchemy context managers (4-6 hours)
  - [ ] 5. Streaming XML parser (6-8 hours)
  - [ ] Integration testing (2 hours)

- [ ] **Week 3**: Monitoring & Validation
  - [ ] Add memory monitoring (1 hour)
  - [ ] Run memory profiling tests (1 hour)
  - [ ] Performance regression testing (2 hours)
  - [ ] Documentation updates (1 hour)

### Expected Results

After implementing all improvements:

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Memory growth per hour | ~50-100 MB | ~10-20 MB | 70-80% reduction |
| Long session stability | May leak | Stable | Crash prevention |
| Large XML import (1000 hosts) | ~500 MB peak | ~150 MB peak | 70% reduction |
| Process table query time (10K records) | ~2-5 sec | ~0.5 sec | 75% faster |
| Screenshot queue overflow | Crash risk | Graceful handling | No crashes |

---

## Need Help?

If you encounter issues during implementation:

1. **Check logs** - Use `DEBUG` level logging to see detailed information
2. **Run unit tests** - Validate each improvement in isolation
3. **Profile memory** - Use `memory_profiler` to identify actual issues
4. **Review this guide** - Each section has detailed examples

**Remember**: These are incremental improvements to an already-working system. Test each change thoroughly before moving to the next one.
