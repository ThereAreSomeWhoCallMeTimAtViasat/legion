#!/usr/bin/env python

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

import re
from PyQt6 import QtWidgets, QtGui, QtCore

from app.ModelHelpers import resolveHeaders, itemInteractive
from app.auxiliary import *                                                 # for bubble sort

class ProcessesTableModel(QtCore.QAbstractTableModel):

    def __init__(self, controller, processes = [[]], headers = [], parent = None):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.__headers = headers
        self.__processes = processes
        self.__controller = controller
        self.__match_cache = {}  # Cache for match results

    @staticmethod
    def _format_duration(seconds):
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            return "00:00:00"
        if seconds < 0:
            seconds = 0
        total_seconds = int(seconds)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _runtime_seconds_for_row(self, row):
        proc = self.__processes[row]
        pid_value = proc.get('pid')
        runtime = None
        measurements = getattr(self.__controller.controller, 'processMeasurements', {})
        if pid_value not in (None, '', '0'):
            try:
                runtime = measurements.get(int(pid_value))
            except (ValueError, TypeError):
                runtime = measurements.get(pid_value)
        if runtime is None or runtime == 0:
            runtime = proc.get('elapsed')
        if runtime in ('', None):
            runtime = 0
        try:
            return float(runtime)
        except (TypeError, ValueError):
            return 0.0
        
    def setProcesses(self, processes):
        self.__processes = processes
        
    def getProcesses(self):
        return self.__processes

    def rowCount(self, parent):
        return len(self.__processes)

    def columnCount(self, parent):
        if len(self.__processes) != 0:
            return len(self.__processes[0])
        return 0

    def headerData(self, section, orientation, role):
        return resolveHeaders(role, orientation, section, self.__headers)
    
    #for matching
    def _has_matches_for_tool(self, row):
        """Check if a tool has matches, with caching"""
        # Check cache first
        if row in self.__match_cache:
            return self.__match_cache[row]
        
        # Check for matches
        has_matches = False
        try:
            from PyQt6 import QtWidgets
            toolName = self.__processes[row].get('name', '')
            view = self.__controller
            
            if hasattr(view, 'viewState') and hasattr(view.viewState, 'hostTabs'):
                for hostIp, tabs in view.viewState.hostTabs.items():
                    for tab in tabs:
                        tabName = tab.objectName()
                        if toolName in tabName:
                            matches = tab.property('matches')
                            if matches:
                                has_matches = True
                                break
                    if has_matches:
                        break
        except:
            pass
        
        # Cache the result
        self.__match_cache[row] = has_matches
        return has_matches


    # this method takes care of how the information is displayed
    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole or role == QtCore.Qt.ItemDataRole.EditRole:
            value = ''
            row = index.row()
            column = index.column()
            processColumns = {0: 'progress', 1: 'display', 2: 'elapsed', 3: 'percent',
                              4: 'pid', 5: 'name', 6: 'tabTitle', 7: 'hostIp', 8: 'port', 9: 'protocol', 10: 'command',
                              11: 'startTime', 12: 'endTime', 13: 'outputfile', 14: 'output', 15: 'status',
                              16: 'closed'}
            try:
                if column == 0:
                    value = ''
                elif column == 2:
                    runtime_seconds = self._runtime_seconds_for_row(row)
                    value = self._format_duration(runtime_seconds)
                elif column == 3:
                    percent = self.__processes[row].get('percent')
                    if percent is not None and percent != "":
                        value = f"{percent}%" if not str(percent).endswith("%") else str(percent)
                    else:
                        value = "Unknown"
                elif column == 6:
                    if not self.__processes[row]['tabTitle'] == '':
                        value = self.__processes[row]['tabTitle']
                    else:
                        value = self.__processes[row]['name']
                elif column == 8:
                    port = self.__processes[row].get('port', '')
                    protocol = self.__processes[row].get('protocol', '')
                    
                    # If port/protocol exist, display them
                    if port and protocol:
                        value = f"{port}/{protocol}"
                    elif port:
                        value = port
                    else:
                        # No port data - extract text from parentheses in tabTitle
                        tab_title = self.__processes[row].get('tabTitle', '')
                        if tab_title and '(' in tab_title and ')' in tab_title:
                            import re
                            # Extract text within parentheses
                            paren_match = re.search(r'\(([^)]+)\)', tab_title)
                            if paren_match:
                                value = paren_match.group(1)
                            else:
                                value = ''
                        else:
                            value = ''
                elif column == 16:
                    value = ""
                else:
                    try:
                        key = processColumns.get(int(column))
                        if key is not None:
                            value = self.__processes[row][key]
                        else:
                            value = ""
                    except:
                        value = ""

            except Exception:
                value = ""
            return value
        
        # Handle text color for tool name and port columns
        elif role == QtCore.Qt.ItemDataRole.ForegroundRole:
            row = index.row()
            column = index.column()
            
            # Color column 5 (tool name) if ANY instance has matches
            if column == 5 and self._has_matches_for_tool(row):
                from PyQt6.QtGui import QColor
                return QColor('red')
            
            # Color column 8 (port) if THIS specific host/port has matches
            elif column == 8 and self._has_matches_for_this_process(row):
                from PyQt6.QtGui import QColor
                return QColor('red')
            
            return None
        
        # Handle font weight (bold) for tool name and port columns
        elif role == QtCore.Qt.ItemDataRole.FontRole:
            row = index.row()
            column = index.column()
            
            # Bold column 5 (tool name) if ANY instance has matches
            if column == 5 and self._has_matches_for_tool(row):
                from PyQt6.QtGui import QFont
                font = QFont()
                font.setBold(True)
                return font
            
            # Bold column 8 (port) if THIS specific host/port has matches
            elif column == 8 and self._has_matches_for_this_process(row):
                from PyQt6.QtGui import QFont
                font = QFont()
                font.setBold(True)
                return font
            
            return None
        
        return None


    def sort(self, Ncol, order):
        # Store persistent indices before sorting
        oldIndexList = self.persistentIndexList()
        oldIds = [self.__processes[idx.row()].get('id') if idx.row() < len(self.__processes) else None for idx in oldIndexList]
        
        self.layoutAboutToBeChanged.emit()
        array=[]

        sortColumns = {2: 'elapsed', 5:'name', 6:'tabTitle', 11:'startTime', 12:'endTime'}
        field = sortColumns.get(int(Ncol)) or 'status'

        try:
            if Ncol == 7:
                for i in range(len(self.__processes)):
                    array.append(IP2Int(self.__processes[i]['hostIp']))

            elif Ncol == 8:
                for i in range(len(self.__processes)):
                    port_value = self.__processes[i].get('port', '')
                    protocol = self.__processes[i].get('protocol', '')
                    
                    # Determine the display value (same logic as in data method)
                    if port_value and protocol:
                        display_value = f"{port_value}/{protocol}"
                    elif port_value:
                        display_value = port_value
                    else:
                        # Extract from tabTitle parentheses
                        tab_title = self.__processes[i].get('tabTitle', '')
                        if tab_title and '(' in tab_title and ')' in tab_title:
                            import re
                            paren_match = re.search(r'\(([^)]+)\)', tab_title)
                            display_value = paren_match.group(1) if paren_match else ''
                        else:
                            display_value = ''
                    
                    # Try to extract numeric port for sorting
                    if '/' in str(display_value):
                        # Format: "80/tcp" - extract the port number
                        try:
                            array.append(int(display_value.split('/')[0]))
                            continue
                        except (ValueError, IndexError):
                            pass
                    
                    # Try to extract stage number for "stage N" format
                    if 'stage' in str(display_value).lower():
                        import re
                        stage_match = re.search(r'stage\s+(\d+)', str(display_value), re.IGNORECASE)
                        if stage_match:
                            array.append(int(stage_match.group(1)))
                            continue
                    
                    # Try as plain integer
                    try:
                        array.append(int(display_value))
                        continue
                    except (ValueError, TypeError):
                        pass
                    
                    # Fall back to string value
                    array.append(display_value if display_value else '')
            else:
                for i in range(len(self.__processes)):
                    value = self.__processes[i].get(field)
                    if field == 'elapsed':
                        try:
                            value = float(value)
                        except (TypeError, ValueError):
                            value = 0.0
                    array.append(value)
        
            # Debug logging
            if Ncol == 8:  # Port column
                log.debug(f"BEFORE SORT - First 3 processes:")
                for i in range(min(3, len(self.__processes))):
                    log.debug(f"  [{i}] tool={self.__processes[i].get('name')}, port={self.__processes[i].get('port')}, sortkey={array[i]}")
            
            sortArrayWithArray(array, self.__processes)  # sort the services based on the values in the array

            if Ncol == 8:  # Port column
                log.debug(f"AFTER SORT - First 3 processes:")
                for i in range(min(3, len(self.__processes))):
                    log.debug(f"  [{i}] tool={self.__processes[i].get('name')}, port={self.__processes[i].get('port')}, sortkey={array[i]}")

            if order == Qt.SortOrder.AscendingOrder:                                  # reverse if needed
                self.__processes.reverse()
                self.__controller.processesTableViewSort = 'desc'
            else:
                self.__controller.processesTableViewSort = 'asc'

            self.__controller.processesTableViewSortColumn = field

        ## Extra?
        #self.__controller.updateProcessesIcon()  # to make sure the progress GIF is displayed in the right place
            
            # Update persistent indices after sorting
            newIndexList = []
            for oldIdx, oldId in zip(oldIndexList, oldIds):
                if oldId is not None:
                    for newRow, process in enumerate(self.__processes):
                        if process.get('id') == oldId:
                            newIndexList.append(self.index(newRow, oldIdx.column()))
                            break
                    else:
                        newIndexList.append(QtCore.QModelIndex())
                else:
                    newIndexList.append(QtCore.QModelIndex())
            
            self.changePersistentIndexList(oldIndexList, newIndexList)
            self.layoutChanged.emit()
        except:
            log.error("Failed to sort")
            pass

    # method that allows views to know how to treat each item, eg: if it should be enabled, editable, selectable etc
    def flags(self, index):
        return itemInteractive()

    def setDataList(self, processes):
        self.__processes = processes
        self.__match_cache = {}  # Clear cache when data changes
        self.layoutAboutToBeChanged.emit()
        self.dataChanged.emit(self.createIndex(0, 0), self.createIndex(self.rowCount(0), self.columnCount(0)))
        self.layoutChanged.emit()

    ### getter functions ###

    def getProcessPidForRow(self, row):
        return self.__processes[row]['pid']
        
    def getProcessPidForId(self, dbId):
        for i in range(len(self.__processes)):
            if str(self.__processes[i]['id']) == str(dbId):
                return self.__processes[i]['pid']

    def getProcessStatusForRow(self, row):
        return self.__processes[row]['status']

    def getProcessStatusForPid(self, pid):
        for i in range(len(self.__processes)):
            if str(self.__processes[i]['pid']) == str(pid):
                return self.__processes[i]['status']
                
    def getProcessStatusForId(self, dbId):
        for i in range(len(self.__processes)):
            if str(self.__processes[i]['id']) == str(dbId):
                return self.__processes[i]['status']

    def getProcessIdForRow(self, row):
        return self.__processes[row]['id']
        
    def getToolNameForRow(self, row):
        return self.__processes[row]['name']
        
    def getRowForToolName(self, toolname):
        for i in range(len(self.__processes)):
            if self.__processes[i]['name'] == toolname:
                return i

    def getRowForDBId(self, dbid):  # new
        for i in range(len(self.__processes)):
            if self.__processes[i]['id'] == dbid:
                return i

    def getIpForRow(self, row):
        return self.__processes[row]['hostIp']

    def getPortForRow(self, row):
        return self.__processes[row]['port']

    def getProtocolForRow(self, row):
        return self.__processes[row]['protocol']
        
    def getOutputfileForRow(self, row):
        return self.__processes[row]['outputfile']
    
    #for matching
    def _has_matches_for_this_process(self, row):
        """Check if this specific process has matches, with caching"""
        processId = self.__processes[row].get('id', '')
        cache_key = f"process_{processId}"
        
        # Check cache first
        if cache_key in self.__match_cache:
            cached = self.__match_cache[cache_key]
            log.debug(f"_has_matches: row={row}, processId={processId}, CACHED={cached}")
            return cached
        
        # Check for matches for this specific process
        has_matches = False
        try:
            from PyQt6 import QtWidgets
            
            toolName = self.__processes[row].get('name', '')
            hostIp = self.__processes[row].get('hostIp', '')
            
            log.debug(f"_has_matches: row={row}, processId={processId}, toolName='{toolName}', CHECKING...")
            
            view = self.__controller
            
            if hasattr(view, 'viewState') and hasattr(view.viewState, 'hostTabs'):
                # Check only tabs for this specific host
                tabs = view.viewState.hostTabs.get(hostIp, [])
                log.debug(f"_has_matches: row={row}, processId={processId}, found {len(tabs)} tabs")
                
                for tab in tabs:
                    # Match by tab name containing tool name
                    tabName = tab.objectName()
                    if toolName in tabName:
                        log.debug(f"_has_matches: row={row}, processId={processId}, checking tab '{tabName}'")
                        # Check if this tab is for this specific process by comparing dbId
                        text_widget = tab.findChild(QtWidgets.QTextEdit)
                        if text_widget:
                            tab_process_id = str(text_widget.property('dbId'))
                        else:
                            # Fallback: check dbId on the tab widget itself
                            tab_process_id = str(tab.property('dbId'))
                            log.debug(f"_has_matches: row={row}, processId={processId}, tab '{tabName}' using fallback dbId from parent widget")
                        
                        matches_prop = tab.property('matches')
                        log.debug(f"_has_matches: row={row}, processId={processId}, tab '{tabName}' dbId={tab_process_id}, matches={matches_prop}")
                        
                        if tab_process_id == str(processId):
                            matches = tab.property('matches')
                            if matches:
                                has_matches = True
                                log.debug(f"_has_matches: row={row}, processId={processId}, MATCH FOUND! has_matches=True")
                                break
        except Exception as e:
            log.debug(f"_has_matches: row={row}, processId={processId}, EXCEPTION: {e}")
        
        # Cache the result
        self.__match_cache[cache_key] = has_matches
        log.debug(f"_has_matches: row={row}, processId={processId}, FINAL has_matches={has_matches} (cached)")
        return has_matches

