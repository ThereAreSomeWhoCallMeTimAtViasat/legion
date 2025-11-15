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

from typing import Union

from six import u as unicode

from app.timing import getTimestamp
from sqlalchemy import text
from db.SqliteDbAdapter import Database
from db.entities.process import process
from db.entities.processOutput import process_output


class ProcessRepository:
    def __init__(self, dbAdapter: Database, log):
        self.dbAdapter = dbAdapter
        self.log = log

    # the showProcesses flag is used to ensure we don't display processes in the process table after we have cleared
    # them or when an existing project is opened.
    # to speed up the queries we replace the columns we don't need by zeros (the reason we need all the columns is
    # we are using the same model to display process information everywhere)

    def updateProcessState(self, processId: str, **kwargs):
        """
        Update multiple process fields atomically in a single transaction.

        PHASE 2 FIX: Prevents race conditions by consolidating updates.

        Args:
            processId: The process ID to update
            **kwargs: Field names and values (status, pid, elapsed, percent, endTime, closed, display)

        Returns:
            bool: True if successful, False if process not found
        """
        if not processId:
            self.log.warning("updateProcessState called with empty processId")
            return False

        session = self.dbAdapter.session  # CRITICAL: Use scoped session (not session()!)

        try:
            proc = session.query(process).filter_by(id=processId).first()

            if not proc:
                self.log.warning(f"Process {processId} not found for update")
                return False

            # Apply all updates atomically
            updated_fields = []
            for field, value in kwargs.items():
                if hasattr(proc, field):
                    old_value = getattr(proc, field)
                    setattr(proc, field, value)
                    updated_fields.append(f"{field}: {old_value} → {value}")
                else:
                    self.log.warning(f"Invalid field '{field}' for process update")

            if updated_fields:
                session.commit()
                self.log.debug(f"Process {processId} updated: {', '.join(updated_fields)}")
                return True
            else:
                self.log.debug(f"No valid fields to update for process {processId}")
                return False

        except Exception as e:
            self.log.error(f"Error updating process {processId}: {e}")
            session.rollback()
            raise


    def getProcesses(self, filters, showProcesses: Union[str, bool] = 'noNmap', sort: str = 'desc', ncol: str = 'id',
                     status_filter=None):
        # Modified: return consistent column aliases across all query paths so UI models can rely on keys.
        session = self.dbAdapter.session()
        def normalize_status_filter(filter_value):
            if not filter_value:
                return []
            if isinstance(filter_value, str):
                mapping = {
                    'All': [],
                    'Running': ['Running', 'Waiting'],
                    'Finished': ['Finished'],
                    'Failed': ['Crashed', 'Cancelled', 'Killed', 'Failed'],
                    'Queued': ['Waiting']
                }
                values = mapping.get(filter_value, [filter_value])
            else:
                values = [value for value in filter_value if value]
            seen = set()
            normalized = []
            for value in values:
                if value not in seen:
                    normalized.append(value)
                    seen.add(value)
            return normalized

        def build_status_clause(values):
            if not values:
                return "", {}
            params = {}
            placeholders = []
            for idx, value in enumerate(values):
                key = f"status_{idx}"
                params[key] = value
                placeholders.append(f":{key}")
            clause = f" AND process.status IN ({', '.join(placeholders)})"
            return clause, params

        status_values = normalize_status_filter(status_filter)
        status_clause, status_params = build_status_clause(status_values)
        params = dict(status_params)
        if showProcesses == 'noNmap':
            base_query = (
                'SELECT '
                '0 AS progress, '
                'COALESCE(process.display, "False") AS display, '
                'COALESCE(process.elapsed, 0) AS elapsed, '
                'COALESCE(process.percent, "") AS percent, '
                'COALESCE(process.pid, "") AS pid, '
                'COALESCE(process.name, "") AS name, '
                'COALESCE(process.tabTitle, "") AS tabTitle, '
                'COALESCE(process.hostIp, "") AS hostIp, '
                'COALESCE(process.port, "") AS port, '
                'COALESCE(process.protocol, "") AS protocol, '
                'COALESCE(process.command, "") AS command, '
                'COALESCE(process.startTime, "") AS startTime, '
                'COALESCE(process.endTime, "") AS endTime, '
                'COALESCE(process.outputfile, "") AS outputfile, '
                '"" AS output, '
                'COALESCE(process.status, "") AS status, '
                'COALESCE(process.closed, "") AS closed, '
                'process.id AS id '
                'FROM process AS process '
                'WHERE process.closed = "False"'
            )
            query = text(base_query + status_clause + ' ORDER BY process.id DESC')
            result = session.execute(query, params)
        elif not showProcesses:
            base_query = (
                'SELECT '
                '0 AS progress, '
                'process.display AS display, '
                'COALESCE(process.elapsed, 0) AS elapsed, '
                'COALESCE(process.percent, "") AS percent, '
                'COALESCE(process.pid, "") AS pid, '
                'COALESCE(process.name, "") AS name, '
                'COALESCE(process.tabTitle, "") AS tabTitle, '
                'COALESCE(process.hostIp, "") AS hostIp, '
                'COALESCE(process.port, "") AS port, '
                'COALESCE(process.protocol, "") AS protocol, '
                'COALESCE(process.command, "") AS command, '
                'COALESCE(process.startTime, "") AS startTime, '
                'COALESCE(process.endTime, "") AS endTime, '
                'COALESCE(process.outputfile, "") AS outputfile, '
                'COALESCE(output.output, "") AS output, '
                'COALESCE(process.status, "") AS status, '
                'COALESCE(process.closed, "") AS closed, '
                'process.id AS id '
                'FROM process AS process '
                'INNER JOIN process_output AS output ON process.id = output.processId '
                'WHERE process.display = :display AND process.closed = "False"'
            )
            params['display'] = str(showProcesses)
            query = text(base_query + status_clause + ' ORDER BY process.id DESC')
            result = session.execute(query, params)
        else:
            base_query = (
                'SELECT '
                '0 AS progress, '
                'process.display AS display, '
                'COALESCE(process.elapsed, 0) AS elapsed, '
                'COALESCE(process.percent, "") AS percent, '
                'COALESCE(process.pid, "") AS pid, '
                'COALESCE(process.name, "") AS name, '
                'COALESCE(process.tabTitle, "") AS tabTitle, '
                'COALESCE(process.hostIp, "") AS hostIp, '
                'COALESCE(process.port, "") AS port, '
                'COALESCE(process.protocol, "") AS protocol, '
                'COALESCE(process.command, "") AS command, '
                'COALESCE(process.startTime, "") AS startTime, '
                'COALESCE(process.endTime, "") AS endTime, '
                'COALESCE(process.outputfile, "") AS outputfile, '
                'COALESCE(output.output, "") AS output, '
                'COALESCE(process.status, "") AS status, '
                'COALESCE(process.closed, "") AS closed, '
                'process.id AS id '
                'FROM process AS process '
                'LEFT JOIN process_output AS output ON process.id = output.processId '
                'WHERE process.display=:display'
            )
            params['display'] = str(showProcesses)
            order_clause = f' ORDER BY {ncol} {sort}'
            query = text(base_query + status_clause + order_clause)
            result = session.execute(query, params)
        rows = result.fetchall()
        keys = result.keys()
        processes = [dict(zip(keys, row)) for row in rows]
        session.close()
        return processes

    def storeProcess(self, proc):
        session = self.dbAdapter.session()
        p_output = process_output()
       
        #p = process(str(proc.processId()), str(proc.name), str(proc.tabTitle),
        p = process(str(proc.processId()), str(proc.name), str(proc.tabTitle),
                    str(proc.hostIp), str(proc.port), str(proc.protocol),
                    unicode(proc.command), proc.startTime, "", str(proc.outputfile),
                    'Waiting', [p_output], 100, 0)

        self.log.debug(f"Adding process: {p}")
        session.add(p)
        session.commit()
        proc.id = p.id
        session.close()
        return proc.id

    def storeProcessOutput(self, process_id: str, output: str):
        session = self.dbAdapter.session()
        proc = session.query(process).filter_by(id=process_id).first()

        if not proc:
            session.close()
            return False

        proc_output = session.query(process_output).filter_by(id=process_id).first()
        if proc_output:
            self.log.debug("Storing process output into db: {0}".format(str(proc_output)))
            proc_output.output = unicode(output)
            session.add(proc_output)

        proc.endTime = getTimestamp(True)

        if proc.status == "Killed" or proc.status == "Cancelled" or proc.status == "Crashed":
            #session.commit() # Needed?
            session.close()
            return True
        else:
            proc.status = 'Finished'
            session.add(proc)
            session.commit()
        session.close()

    def getStatusByProcessId(self, process_id: str):
        return self.getFieldByProcessId("status", process_id)

    def getPIDByProcessId(self, process_id: str):
        return self.getFieldByProcessId("pid", process_id)

    def isKilledProcess(self, process_id: str) -> bool:
        status = self.getFieldByProcessId("status", process_id)
        return True if status == "Killed" else False

    def isCancelledProcess(self, process_id: str) -> bool:
        status = self.getFieldByProcessId("status", process_id)
        return True if status == "Cancelled" else False

    def getFieldByProcessId(self, field_name: str, process_id: str):
        session = self.dbAdapter.session()
        query = text("SELECT process.{0} FROM process AS process WHERE process.id=:process_id".format(field_name))
        p = session.execute(query, {'process_id': str(process_id)}).fetchall()
        result = p[0][0] if p else -1
        session.close()
        return result

    def getHostsByToolName(self, toolName: str, closed: str = "False"):
        session = self.dbAdapter.session()
        if closed == 'FetchAll':
            query = text(
                'SELECT '
                '0 AS progress, '
                'process.display AS display, '
                'COALESCE(process.elapsed, 0) AS elapsed, '
                'COALESCE(process.percent, "") AS percent, '
                'COALESCE(process.pid, "") AS pid, '
                'COALESCE(process.name, "") AS name, '
                'COALESCE(process.tabTitle, "") AS tabTitle, '
                'COALESCE(process.hostIp, "") AS hostIp, '
                'COALESCE(process.port, "") AS port, '
                'COALESCE(process.protocol, "") AS protocol, '
                'COALESCE(process.command, "") AS command, '
                'COALESCE(process.startTime, "") AS startTime, '
                'COALESCE(process.endTime, "") AS endTime, '
                'COALESCE(process.outputfile, "") AS outputfile, '
                'COALESCE(output.output, "") AS output, '
                'COALESCE(process.status, "") AS status, '
                'COALESCE(process.closed, "") AS closed, '
                'process.id AS id '
                'FROM process AS process '
                'LEFT JOIN process_output AS output ON process.id = output.processId '
                'WHERE process.name=:toolName'
            )
            result = session.execute(query, {'toolName': str(toolName)})
        else:
            query = text(
                'SELECT '
                '0 AS progress, '
                'process.display AS display, '
                'COALESCE(process.elapsed, 0) AS elapsed, '
                'COALESCE(process.percent, "") AS percent, '
                'COALESCE(process.pid, "") AS pid, '
                'COALESCE(process.name, "") AS name, '
                'COALESCE(process.tabTitle, "") AS tabTitle, '
                'COALESCE(process.hostIp, "") AS hostIp, '
                'COALESCE(process.port, "") AS port, '
                'COALESCE(process.protocol, "") AS protocol, '
                'COALESCE(process.command, "") AS command, '
                'COALESCE(process.startTime, "") AS startTime, '
                'COALESCE(process.endTime, "") AS endTime, '
                'COALESCE(process.outputfile, "") AS outputfile, '
                'COALESCE(output.output, "") AS output, '
                'COALESCE(process.status, "") AS status, '
                'COALESCE(process.closed, "") AS closed, '
                'process.id AS id '
                'FROM process AS process '
                'LEFT JOIN process_output AS output ON process.id = output.processId '
                'WHERE process.name=:toolName AND process.closed=:closed'
            )
            result = session.execute(query, {'toolName': str(toolName), 'closed': str(closed)})
        rows = result.fetchall()
        keys = result.keys()
        session.close()
        return [dict(zip(keys, row)) for row in rows]

    def getProcessById(self, process_id):
        session = self.dbAdapter.session()
        try:
            proc = session.query(process).filter_by(id=process_id).first()
            if not proc:
                return None
            data = {
                'id': proc.id,
                'name': (proc.name or '').strip(),
                'tabTitle': (proc.tabTitle or '').strip(),
                'hostIp': (proc.hostIp or '').strip(),
                'port': (proc.port or '').strip(),
                'protocol': (proc.protocol or '').strip(),
                'command': (proc.command or '').strip(),
                'outputfile': (proc.outputfile or '').strip(),
                'status': (proc.status or '').strip(),
                'display': (proc.display or '').strip(),
            }
            return data
        finally:
            session.close()

    def getProcessesForRestore(self):
        session = self.dbAdapter.session()
        query = text(
            'SELECT '
            'process.id AS id, '
            'COALESCE(process.hostIp, "") AS hostIp, '
            'COALESCE(process.tabTitle, "") AS tabTitle, '
            'COALESCE(process.outputfile, "") AS outputfile, '
            'COALESCE(output.output, "") AS output '
            'FROM process AS process '
            'LEFT JOIN process_output AS output ON process.id = output.processId '
            'WHERE process.closed = "False" '
            'ORDER BY process.id ASC'
        )
        result = session.execute(query)
        rows = result.fetchall()
        keys = result.keys()
        session.close()
        return [dict(zip(keys, row)) for row in rows]

    def storeProcessCrashStatus(self, processId: str):
        session = self.dbAdapter.session()
        proc = session.query(process).filter_by(id=processId).first()
        if proc and not proc.status == 'Killed' and not proc.status == 'Cancelled':
            proc.status = 'Crashed'
            proc.endTime = getTimestamp(True)
            session.add(proc)
            session.commit()
        session.close()

    def storeProcessCancelStatus(self, processId: str):
        """Mark process as cancelled. REFACTORED for Phase 2."""
        return self.updateProcessState(processId, status='Cancelled', endTime=getTimestamp(True))

    def storeProcessKillStatus(self, processId: str):
        session = self.dbAdapter.session()
        proc = session.query(process).filter_by(id=processId).first()
        if proc and not proc.status == 'Finished':
            proc.status = 'Killed'
            proc.endTime = getTimestamp(True)
            session.add(proc)
            session.commit()
        session.close()

    def storeProcessRunningStatus(self, processId: str, pid):
        """Set process status to Running with PID. REFACTORED for Phase 2."""
        return self.updateProcessState(processId, status='Running', pid=str(pid))

    def storeProcessRunningElapsedTime(self, processId: str, elapsed):
        """Update process elapsed time. REFACTORED for Phase 2."""
        return self.updateProcessState(processId, elapsed=elapsed)

    def storeProcessPercent(self, processId: str, percent):
        """Update process percent. REFACTORED for Phase 2."""
        return self.updateProcessState(processId, percent=percent)

    def storeCloseStatus(self, processId):
        """Mark process as closed. REFACTORED for Phase 2."""
        return self.updateProcessState(processId, closed='True')

    def storeScreenshot(self, ip: str, port: str, filename: str):
        session = self.dbAdapter.session()
        p = process(0, "screenshooter", "screenshot (" + str(port) + "/tcp)", str(ip), str(port), "tcp", "",
                    getTimestamp(True), getTimestamp(True), str(filename), "Finished", [process_output()], 2, 0)
        if p:
            session.add(p)
            session.commit()
            pD = p.id
            session.close()
        return pD

    def toggleProcessDisplayStatus(self, resetAll=False):
        session = self.dbAdapter.session()
        proc = session.query(process).filter_by(display='True').all()
        for p in proc:
            session.add(self.toggleProcessStatusField(p, resetAll))
        session.commit()
        session.close()

    @staticmethod
    def toggleProcessStatusField(p, reset_all):
        not_running = p.status != 'Running'
        not_waiting = p.status != 'Waiting'

        if (reset_all and not_running) or (not_running and not_waiting):
            p.display = 'False'

        return p

    def resetDisplayStatusForOpenProcesses(self):
        session = self.dbAdapter.session()
        try:
            session.query(process).filter_by(closed='False').update(
                {process.display: 'True'}, synchronize_session=False
            )
            session.commit()
        finally:
            session.close()

    def deleteProcess(self, processId: str):
        """Delete a specific process and its output from the database."""
        session = self.dbAdapter.session()
        try:
            # Delete process_output first
            session.execute(
                text("DELETE FROM process_output WHERE id = :processId"),
                {"processId": str(processId)}
            )
            # Delete process
            session.execute(
                text("DELETE FROM process WHERE id = :processId"),
                {"processId": str(processId)}
            )
            session.commit()
            self.log.info(f"Deleted process {processId} from database")
        except Exception as e:
            session.rollback()
            self.log.error(f"Failed to delete process {processId}: {e}")
            raise
        finally:
            session.close()
    
    def deleteProcessesByHostIp(self, hostIp: str):
        """Delete all processes for a given host IP."""
        session = self.dbAdapter.session()
        try:
            # Delete process outputs first
            session.execute(
                text("DELETE FROM process_output WHERE id IN (SELECT id FROM process WHERE hostIp = :hostip)"),
                {"hostip": str(hostIp)}
            )
            # Delete processes
            session.execute(
                text("DELETE FROM process WHERE hostIp = :hostip"),
                {"hostip": str(hostIp)}
            )
            session.commit()
            self.log.info(f"Deleted all processes for host {hostIp}")
        except Exception as e:
            session.rollback()
            self.log.error(f"Failed to delete processes for host {hostIp}: {e}")
            raise
        finally:
            session.close()

    def storeProcessInteractiveStatus(self, processId: str):
        session = self.dbAdapter.session()
        proc = session.query(process).filter_by(id=processId).first()
        if proc:
            proc.status = 'Interactive'
            session.add(proc)
            session.commit()
        session.close()
