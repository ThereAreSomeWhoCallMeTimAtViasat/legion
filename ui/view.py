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

import ntpath  # for file operations, to kill processes and for regex
import os
import shutil
from collections import OrderedDict
from collections.abc import Mapping

from app.ApplicationInfo import applicationInfo, getVersion
from app.timing import getTimestamp
from ui.ViewState import ViewState
from ui.dialogs import *
from ui.settingsDialog import *
from ui.configDialog import *
from ui.helpDialog import *
from ui.addHostDialog import *
from ui.AddPortDialog import AddPortDialog
from ui.ancillaryDialog import *
from ui.models.hostmodels import *
from ui.models.servicemodels import *
from ui.models.scriptmodels import *
from ui.models.cvemodels import *
from ui.models.processmodels import *
from ui.models.ostables import OsSummaryTableModel, OsHostsTableModel
from app.auxiliary import *
from six import u as unicode
import pandas as pd
from PyQt6.QtWidgets import QAbstractItemView
from PyQt6.QtCore import Qt, QCoreApplication

log = getAppLogger()

# this class handles everything gui-related
class View(QtCore.QObject):
    tick = QtCore.pyqtSignal(int, name="changed")                       # signal used to update the progress bar
    
    def __init__(self, viewState: ViewState, ui, ui_mainwindow, shell: Shell, app, loop):
        QtCore.QObject.__init__(self)
        self.ui = ui
        self.ui_mainwindow = ui_mainwindow  # TODO: retrieve window dimensions/location from settings
        self.app = app
        self.loop = loop

        self.bottomWindowSize = 100
        self.leftPanelSize = 300

        self.ui.splitter_2.setSizes([250, self.bottomWindowSize])  # set better default size for bottom panel
        self.qss = None
        self.processesTableViewSort = 'desc'
        self.processesTableViewSortColumn = 'status'
        self.toolsTableViewSort = 'desc'
        self.toolsTableViewSortColumn = 'id'
        self.shell = shell
        self.viewState = viewState
        self._os_selection_model = None
        self.processStatusFilter = None
        # Flag to prevent double close confirmation
        self._closing = False

        #for update highlighting unread tabs
        # Track tabs with unread updates
        self.unread_tabs = {
            'Services': False,
            'Scripts': False,
            'Information': False,
            'CVEs': False,
            'Notes': False
        }
        
        # Add flag to track if app has finished initializing
        self.app_initialized = False
            
        # Track previous counts for each host to detect NEW data
        self.previous_data_counts = {}

    def highlightTab(self, tabname):
        """
        Highlight a tab with orange text when new data is added
        """
        log.debug("========== highlightTab START ==========")
        log.debug(f"highlightTab called for {tabname}, app_initialized={self.app_initialized}")
        log.debug(f"highlightTab - BEFORE: unread_tabs = {self.unread_tabs}")
        
        if not self.app_initialized:
            log.debug(f"Not highlighting {tabname} - app not initialized yet")
            return
            
        tabwidget = self.ui.ServicesTabWidget
        tabbar = tabwidget.tabBar()
        
        log.debug(f"highlightTab - ServicesTabWidget count = {tabwidget.count()}")
        log.debug(f"highlightTab - Current tabs: {[tabwidget.tabText(i) for i in range(tabwidget.count())]}")
        
        # Always mark fixed tabs as unread in the dictionary
        # This preserves the state even if the tab isn't currently visible (e.g., when on Tools tab)
        if tabname in ['Services', 'Scripts', 'Information', 'CVEs', 'Notes']:
            log.debug(f"highlightTab - Marking {tabname} as unread in dictionary")
            self.unread_tabs[tabname] = True
        
        # Try to find and color the tab if it's currently visible in the widget
        tab_found = False
        for i in range(tabwidget.count()):
            if tabwidget.tabText(i) == tabname:
                tab_found = True
                log.debug(f"Found {tabname} at index {i}, currently unread={self.unread_tabs.get(tabname, False)}")
                
                # Set the visual orange color on the tab
                tabbar.setTabTextColor(i, QtGui.QColor('orange'))
                log.debug(f"Set {tabname} tab to ORANGE at index {i}, visible={tabwidget.isVisible()}")
                break
        
        if not tab_found:
            log.debug(f"Tab {tabname} not currently visible in ServicesTabWidget (probably on Tools/OS view)")
            log.debug("State saved in unread_tabs for when tab is restored")
        
        log.debug(f"highlightTab - AFTER: unread_tabs = {self.unread_tabs}")
        log.debug("========== highlightTab END ==========\n")




    def preserveFixedTabColors(self):
        """
        Reapply colors to fixed tabs after dynamic tabs are added/removed
        """
        log.debug("========== preserveFixedTabColors START ==========")
        tabwidget = self.ui.ServicesTabWidget
        tabbar = tabwidget.tabBar()
        fixedtabs = ['Services', 'Scripts', 'Information', 'CVEs', 'Notes']
        
        log.debug(f"preserveFixedTabColors: unread_tabs={self.unread_tabs}")
        
        for i in range(min(len(fixedtabs), tabwidget.count())):
            tabname = tabwidget.tabText(i)
            if tabname in fixedtabs and self.unread_tabs.get(tabname, False):
                tabbar.setTabTextColor(i, QtGui.QColor('orange'))
                log.debug(f"Reapplied ORANGE to {tabname} at index {i}")
        
        log.debug("========== preserveFixedTabColors END ==========\n")



            
    def resetTabHighlight(self, tabindex):
        log.debug("========== resetTabHighlight START ==========")
        
        # Check flag - if set, skip completely
        if hasattr(self, 'suppress_reset_highlight') and self.suppress_reset_highlight:
            log.debug("resetTabHighlight: suppress_reset_highlight is True, SKIPPING reset")
            log.debug("========== resetTabHighlight END (suppressed) ==========\n")
            return
        
        tabwidget = self.ui.ServicesTabWidget
        tabbar = tabwidget.tabBar()
        tabname = tabwidget.tabText(tabindex)
        
        log.debug(f"resetTabHighlight: tabindex={tabindex}, tabname='{tabname}', before unread_tabs={self.unread_tabs}")
        log.debug(f"resetTabHighlight: ServicesTabWidget count = {self.ui.ServicesTabWidget.count()}")
        
        if tabname in self.unread_tabs and self.unread_tabs[tabname]:
            if tabname == 'Information':
                log.debug(f"resetTabHighlight: '{tabname}' is Information tab, skipping reset (waiting for blinking)")
                return
                
            log.debug(f"resetTabHighlight: Resetting '{tabname}' to default color")
            self.unread_tabs[tabname] = False
            tabbar.setTabTextColor(tabindex, self.app.palette().color(QtGui.QPalette.ColorRole.WindowText))
            log.debug(f"resetTabHighlight: RESET '{tabname}', after unread_tabs={self.unread_tabs}")
        else:
            log.debug(f"resetTabHighlight: '{tabname}' not in unread_tabs or already False, no action taken")
            
        log.debug("========== resetTabHighlight END ==========\n")









    def initializeTabColors(self):
        """Set all tabs to default color on startup"""
        tab_widget = self.ui.ServicesTabWidget
        tab_bar = tab_widget.tabBar()
        
        # Get default text color from palette
        default_color = self.app.palette().color(QtGui.QPalette.ColorRole.WindowText)
        
        # Set all fixed tabs to default color
        tab_names = ['Services', 'Scripts', 'Information', 'CVEs', 'Notes']
        for i in range(tab_widget.count()):
            tab_name = tab_widget.tabText(i)
            if tab_name in tab_names:
                tab_bar.setTabTextColor(i, default_color)
                self.unread_tabs[tab_name] = False

    def highlightChangesInText(self, old_text, new_text, text_widget):
        """
        Compare old_text and new_text, highlight changes in red in the text_widget
        """
        import difflib
        from PyQt6.QtGui import QTextCursor, QTextCharFormat, QColor
        
        # Clear the text widget
        text_widget.clear()
        
        # Create a differ object
        differ = difflib.Differ()
        
        # Split texts into lines
        old_lines = old_text.splitlines() if old_text else []
        new_lines = new_text.splitlines() if new_text else []
        
        # Compare the texts
        diff = list(differ.compare(old_lines, new_lines))
        
        # Create text formats
        normal_format = QTextCharFormat()
        normal_format.setForeground(text_widget.palette().color(QtGui.QPalette.ColorRole.Text))
        
        changed_format = QTextCharFormat()
        changed_format.setForeground(QColor('red'))
        
        cursor = text_widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        
        # Process diff results
        for line in diff:
            if line.startswith('  '):  # Unchanged line
                cursor.insertText(line[2:] + '\n', normal_format)
            elif line.startswith('+ '):  # Added line (new content)
                cursor.insertText(line[2:] + '\n', changed_format)
            elif line.startswith('- '):  # Removed line (skip it, we only show what's new)
                continue
            elif line.startswith('? '):  # Diff marker (skip)
                continue

    def buildInformationText(self, host, counterOpen, counterClosed, counterFiltered):
        """Build the information text from host data"""
        info_lines = []
        info_lines.append(f"Status: {host.status}")
        info_lines.append(f"Open Ports: {counterOpen}")
        info_lines.append(f"Closed Ports: {counterClosed}")
        info_lines.append(f"Filtered Ports: {counterFiltered}")
        
        if host.ipv4:
            info_lines.append(f"IPv4: {host.ipv4}")
        if host.ipv6:
            info_lines.append(f"IPv6: {host.ipv6}")
        if host.macaddr:
            info_lines.append(f"MAC Address: {host.macaddr}")
        if host.osMatch:
            info_lines.append(f"OS Match: {host.osMatch}")
        if host.osAccuracy:
            info_lines.append(f"OS Accuracy: {host.osAccuracy}")
        if host.vendor:
            info_lines.append(f"Vendor: {host.vendor}")
        if host.asn:
            info_lines.append(f"ASN: {host.asn}")
        if host.isp:
            info_lines.append(f"ISP: {host.isp}")
        if host.countryCode:
            info_lines.append(f"Country Code: {host.countryCode}")
        if host.city:
            info_lines.append(f"City: {host.city}")
        if host.latitude:
            info_lines.append(f"Latitude: {host.latitude}")
        if host.longitude:
            info_lines.append(f"Longitude: {host.longitude}")
        
        return '\n'.join(info_lines)


    # the view needs access to controller methods to link gui actions with real actions
    def setController(self, controller):
        self.controller = controller

    def startOnce(self):
        # the number of fixed host tabs (services, scripts, information, notes)
        self.fixedTabsCount = self.ui.ServicesTabWidget.count()
        self.hostInfoWidget = HostInformationWidget(self.ui.InformationTab)
        self.filterdialog = FiltersDialog(self.ui.centralwidget)
        # Remove ProgressWidget dialog, use status bar progress instead
        self.importProgressBar = QtWidgets.QProgressBar()
        self.importProgressBar.setMinimum(0)
        self.importProgressBar.setMaximum(100)
        self.importProgressBar.setValue(0)
        self.importProgressBar.setVisible(False)
        self.cancelImportButton = QtWidgets.QPushButton("Cancel Import")
        self.cancelImportButton.setVisible(False)
        self.cancelImportButton.clicked.connect(self.cancelImportNmap)
        self.ui.statusbar.addPermanentWidget(self.importProgressBar)
        self.ui.statusbar.addPermanentWidget(self.cancelImportButton)
        self.importInProgress = False  # Track import state
        # Connect NmapImporter progressUpdated signal to UI slot
        if hasattr(self, "controller") and hasattr(self.controller, "nmapImporter"):
            self.controller.nmapImporter.progressUpdated.connect(self.updateImportProgress)
            self.controller.nmapImporter.done.connect(self.importFinished)
        self.adddialog = AddHostsDialog(self.ui.centralwidget)
        self.settingsWidget = AddSettingsDialog(self.shell, self.ui.centralwidget)
        self.helpDialog = HelpDialog(applicationInfo["name"], applicationInfo["author"], applicationInfo["copyright"],
                                     applicationInfo["links"], applicationInfo["emails"], applicationInfo["version"],
                                     applicationInfo["build"], applicationInfo["update"], applicationInfo["license"],
                                     applicationInfo["desc"], applicationInfo["smallIcon"], applicationInfo["bigIcon"],
                                     qss = self.qss, parent = self.ui.centralwidget)
        self.configDialog = ConfigDialog(controller = self.controller, qss = self.qss, parent = self.ui.centralwidget)

        self.ui.HostsTableView.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.ui.ServiceNamesTableView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ui.CvesTableView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ui.ToolsTableView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ui.ScriptsTableView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ui.ToolHostsTableView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ui.OsListTableView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ui.OsHostsTableView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.connectOsHostsClick()
        status_combo = self.ui.ProcessStatusFilterComboBox
        status_combo.setItemData(0, None)
        status_combo.setItemData(1, ["Waiting", "Running"])
        status_combo.setItemData(2, ["Finished"])
        status_combo.setItemData(3, ["Crashed", "Cancelled", "Killed", "Failed"])
        status_combo.setItemData(4, ["Waiting"])
        status_combo.setCurrentIndex(0)
        self.processStatusFilter = status_combo.currentData()

    # initialisations (globals, etc)
    def start(self, title='*untitled'):
        self.viewState = ViewState()
        self.ui.keywordTextInput.setText('')                            # clear keyword filter

        self.ProcessesTableModel = None  # fixes bug when sorting processes for the first time
        self.ToolsTableModel = None
        self.OsListTableModel = None
        self.OsHostsTableModel = None
        self.setupProcessesTableView()
        self.setupToolsTableView()
        self.setupOsTabViews()

        self.setMainWindowTitle(title)
        self.ui.statusbar.showMessage('Starting up..', msecs=1000)

        self.initTables()                                               # initialise all tables

        self.updateInterface()
        self.restoreToolTabWidget(True)                  # True means we want to show the original textedit
        self.updateScriptsOutputView('')                                # update the script output panel (right)
        self.updateToolHostsTableView('')
        self.ui.MainTabWidget.setCurrentIndex(0)                        # display scan tab by default
        self.ui.HostsTabWidget.setCurrentIndex(0)                       # display Hosts tab by default
        self.ui.ServicesTabWidget.setCurrentIndex(0)                    # display Services tab by default
        self.ui.BottomTabWidget.setCurrentIndex(0)                      # display Log tab by default
        self.ui.BruteTabWidget.setTabsClosable(True)                    # sets all tabs as closable in bruteforcer

        self.ui.ServicesTabWidget.setTabsClosable(True)  # hide the close button (cross) from the fixed tabs

        self.ui.actionNoteSelection.triggered.connect(self.sendSelectionToNotes)

        self.ui.ServicesTabWidget.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        self.ui.ServicesTabWidget.tabBar().setTabButton(1, QTabBar.ButtonPosition.RightSide, None)
        self.ui.ServicesTabWidget.tabBar().setTabButton(2, QTabBar.ButtonPosition.RightSide, None)
        self.ui.ServicesTabWidget.tabBar().setTabButton(3, QTabBar.ButtonPosition.RightSide, None)
        self.ui.ServicesTabWidget.tabBar().setTabButton(4, QTabBar.ButtonPosition.RightSide, None)

        self.resetBruteTabs()  # clear brute tabs (if any) and create default brute tab
        self.displayToolPanel(False)
        self.displayScreenshots(False)
        # displays an overlay over the hosttableview saying 'click here to add host(s) to scope'
        self.displayAddHostsOverlay(True)
        self._initToolTabContextMenu()

        #for update highlighting unread tabs
        self.ui.ServicesTabWidget.setCurrentIndex(0)  # display Services tab by default
        self.ui.BottomTabWidget.setCurrentIndex(0)  # display Log tab by default
        self.ui.BruteTabWidget.setTabsClosable(True)  # sets all tabs as closable in bruteforcer
        self.initializeTabColors()

    def startConnections(self):  # signal initialisations (signals/slots, actions, etc)
        #for update highlighting unread tabs
        self.ui.ServicesTabWidget.currentChanged.connect(self.resetTabHighlight)

        ### MENU ACTIONS ###
        self.connectCreateNewProject()
        self.connectOpenExistingProject()
        self.connectSaveProject()
        self.connectSaveProjectAs()
        self.connectAddHosts()
        self.connectImportNmap()
        self.connectExportJson()
        #self.connectSettings()
        self.connectHelp()
        self.connectConfig()
        self.connectAppExit()
        ### TABLE ACTIONS ###
        self.connectAddHostsOverlayClick()
        self.connectHostTableClick()
        self.connectServiceNamesTableClick()
        self.connectToolsTableClick()
        self.connectScriptTableClick()
        self.connectToolHostsClick()
        self.connectAdvancedFilterClick()
        self.connectAddHostClick()
        self.connectSwitchTabClick()                                    # to detect changing tabs (on left panel)
        self.connectSwitchMainTabClick()                                # to detect changing top level tabs
        self.connectTableDoubleClick()   # for double clicking on host (it redirects to the host view)
        self.connectProcessTableHeaderResize()
        ### CONTEXT MENUS ###
        self.connectHostsTableContextMenu()
        self.connectServiceNamesTableContextMenu()
        self.connectServicesTableContextMenu()
        self.connectToolHostsTableContextMenu()
        self.connectProcessesTableContextMenu()
        self.connectScreenshotContextMenu()
        self.connectOsListClick()
        ### OTHER ###
        self.ui.NotesTextEdit.textChanged.connect(self.setDirty)
        self.ui.FilterApplyButton.clicked.connect(self.updateFilterKeywords)
        self.ui.ServicesTabWidget.tabCloseRequested.connect(self.closeHostToolTab)
        self.ui.BruteTabWidget.tabCloseRequested.connect(self.closeBruteTab)
        self.ui.keywordTextInput.returnPressed.connect(self.ui.FilterApplyButton.click)
        self.filterdialog.applyButton.clicked.connect(self.updateFilter)
        self.ui.ProcessStatusFilterComboBox.currentIndexChanged.connect(self.onProcessStatusFilterChanged)
        #self.settingsWidget.applyButton.clicked.connect(self.applySettings)
        #self.settingsWidget.cmdCancelButton.clicked.connect(self.cancelSettings)
        #self.settingsWidget.applyButton.clicked.connect(self.controller.applySettings(self.settingsWidget.settings))
        #self.tick.connect(self.importProgressWidget.setProgress, QtCore.Qt.ConnectionType.QueuedConnection)

        # Connect tab click to reset highlight
        self.ui.ServicesTabWidget.currentChanged.connect(self.resetTabHighlight)
        
        # Connect to trigger blinking when Information tab is viewed
        self.ui.ServicesTabWidget.currentChanged.connect(self.onInformationTabViewed)

    def onInformationTabViewed(self, index):
        """
        Called when user switches tabs - trigger blinking if Information tab is selected
        """
        log.debug("========== onInformationTabViewed START ==========")
        log.debug(f"onInformationTabViewed: index={index}")
        
        # Check flag - if set, skip to preserve colors during tab operations
        if hasattr(self, 'suppress_reset_highlight') and self.suppress_reset_highlight:
            log.debug("onInformationTabViewed: suppress_reset_highlight is True, SKIPPING")
            log.debug("========== onInformationTabViewed END (suppressed) ==========\n")
            return
        
        tabname = self.ui.ServicesTabWidget.tabText(index)
        log.debug(f"onInformationTabViewed: tabname='{tabname}'")
        
        if tabname == 'Information':
            log.debug("onInformationTabViewed: Starting blinking animation")
            self.hostInfoWidget.onTabViewed()
            
            # Reset the tab color to default after user views it
            if 'Information' in self.unread_tabs and self.unread_tabs['Information']:
                log.debug("onInformationTabViewed: Resetting Information tab to white")
                self.unread_tabs['Information'] = False
                tabbar = self.ui.ServicesTabWidget.tabBar()
                tabbar.setTabTextColor(index, self.app.palette().color(QtGui.QPalette.ColorRole.WindowText))
                log.debug(f"onInformationTabViewed: Information reset, unread_tabs={self.unread_tabs}")
                
        log.debug("========== onInformationTabViewed END ==========\n")



    #################### AUXILIARY ####################

    def initTables(self):  # this function prepares the default settings for each table
        # hosts table (left)
        headers = ["Id", "OS", "Accuracy", "Host", "IPv4", "IPv6", "Mac", "Status", "Hostname", "Vendor", "Uptime",
                   "Lastboot", "Distance", "CheckedHost", "Country Code", "State", "City", "Latitude", "Longitude",
                   "Count", "Closed"]
        setTableProperties(self.ui.HostsTableView, len(headers), [0, 2, 4, 5, 6, 7, 8, 9, 10 , 11, 12, 13, 14, 15, 16,
                                                                  17, 18, 19, 20, 21, 22, 23, 24])
        self.ui.HostsTableView.horizontalHeader().resizeSection(1, 120)
        ##
        self.HostsTableModel = HostsTableModel(self.controller.getHostsFromDB(self.viewState.filters), headers)
        # Set the model of the HostsTableView to the HostsTableModel
        self.ui.HostsTableView.setModel(self.HostsTableModel)
        # Resize the OS column
        self.ui.HostsTableView.horizontalHeader().resizeSection(1, 120)
        # Sort the model by the Host column in descending order
        self.HostsTableModel.sort(3, Qt.SortOrder.DescendingOrder)
        # Connect the clicked signal of the HostsTableView to the hostTableClick() method
        self.ui.HostsTableView.clicked.connect(self.hostTableClick)
        self.ui.HostsTableView.doubleClicked.connect(self.hostTableDoubleClick)

        ##

        # service names table (left)
        headers = ["Name"]
        setTableProperties(self.ui.ServiceNamesTableView, len(headers))

        # cves table (right)
        headers = ["CVE Id", "Severity", "Product", "Version", "CVE URL", "Source", "ExploitDb ID", "ExploitDb",
                   "ExploitDb URL"]
        setTableProperties(self.ui.CvesTableView, len(headers))
        self.ui.CvesTableView.setSortingEnabled(True)

        # tools table (left)
        headers = ["Progress", "Display", "Pid", "Tool", "Tool", "Host", "Port", "Protocol", "Command", "Start time",
                   "OutputFile", "Output", "Status"]
        setTableProperties(self.ui.ToolsTableView, len(headers),
                           [i for i in range(len(headers)) if i != 5])

        # service table (right)
        headers = ["Host", "Port", "Port", "Protocol", "State", "HostId", "ServiceId", "Name", "Product", "Version",
                   "Extrainfo", "Fingerprint"]
        setTableProperties(self.ui.ServicesTableView, len(headers), [0, 1, 5, 6, 8, 10, 11])

        # ports by service (right)
        headers = ["Host", "Port", "Port", "Protocol", "State", "HostId", "ServiceId", "Name", "Product", "Version",
                   "Extrainfo", "Fingerprint"]
        setTableProperties(self.ui.ServicesTableView, len(headers), [2, 5, 6, 8, 10, 11])
        self.ui.ServicesTableView.horizontalHeader().resizeSection(0, 130)       # resize IP

        # scripts table (right)
        headers = ["Id", "Script", "Port", "Protocol"]
        setTableProperties(self.ui.ScriptsTableView, len(headers), [0, 3])

        # tool hosts table (right)
        headers = ["Progress", "Display", "Pid", "Name", "Action", "Target", "Port", "Protocol", "Command",
                   "Start time", "OutputFile", "Output", "Status"]
        setTableProperties(self.ui.ToolHostsTableView, len(headers), [0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12])
        self.ui.ToolHostsTableView.horizontalHeader().resizeSection(5,150)      # default width for Host column

        # os list table (left)
        headers = ["OS", "Hosts"]
        setTableProperties(self.ui.OsListTableView, len(headers))
        self.ui.OsListTableView.setSortingEnabled(False)

        # os hosts table (right)
        headers = ["IP", "Hostname", "OS", "Status"]
        setTableProperties(self.ui.OsHostsTableView, len(headers))

        # process table
        headers = ["Progress", "Display", "Run time", "Percent Complete", "Pid", "Name", "Tool", "Host", "Port",
                   "Protocol", "Command", "Start time", "End time", "OutputFile", "Output", "Status", "Closed"]
        setTableProperties(self.ui.ProcessesTableView, len(headers), [1, 3, 4, 5, 8, 9, 10, 13, 14, 16])
        self.ui.ProcessesTableView.setSortingEnabled(True)

    def setMainWindowTitle(self, title):
        self.ui_mainwindow.setWindowTitle(str(title))

    def yesNoDialog(self, message, title):
        dialog = QtWidgets.QMessageBox.question(self.ui.centralwidget, title, message,
                                                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                                QtWidgets.QMessageBox.StandardButton.No)
        return dialog
        
    def setDirty(self, status=True):   # this function is called for example when the user edits notes
        self.viewState.dirty = status
        title = ''
        
        if self.viewState.dirty:
            title = '*'
        if self.controller.isTempProject():
            title += 'untitled'
        else:
            title += ntpath.basename(str(self.controller.getProjectName()))
        
        self.setMainWindowTitle(applicationInfo["name"] + ' ' + getVersion() + ' - ' + title + ' - ' +
                                self.controller.getCWD())
        
    #################### ACTIONS ####################

    def connectProcessTableHeaderResize(self):
        self.ui.ProcessesTableView.horizontalHeader().sectionResized.connect(self.saveProcessHeaderWidth)

    def saveProcessHeaderWidth(self, index, oldSize, newSize):
        columnWidths = self.controller.getSettings().gui_process_tab_column_widths.split(',')
        # Ensure columnWidths has enough entries
        while len(columnWidths) <= index:
            columnWidths.append(str(newSize))
        # Validate current value
        try:
            current_width = int(columnWidths[index])
        except (ValueError, TypeError):
            current_width = newSize
        difference = abs(current_width - newSize)
        if difference >= 5:
            columnWidths[index] = str(newSize)
            self.controller.settings.gui_process_tab_column_widths = ','.join(columnWidths)
            self.controller.applySettings(self.controller.settings)

    def dealWithRunningProcesses(self, exiting=False):
        """
        Handle running processes before exit or project operations.
        Returns True if we can proceed, False if user canceled.
        """
        log.info(f'=== dealWithRunningProcesses called (exiting={exiting}) ===')
        
        running_processes = self.controller.getRunningProcesses()
        num_running = len(running_processes)
        log.info(f'Number of running processes: {num_running}')
        
        if num_running > 0:
            log.info('Running processes detected, showing confirmation dialog')
            message = "There are still processes running. If you continue, every process will be terminated. " + \
                      "Are you sure you want to continue?"
            reply = self.yesNoDialog(message, 'Confirm')
            
            log.info(f'User reply to process termination: {reply}')
                    
            if not reply == QtWidgets.QMessageBox.StandardButton.Yes:
                log.info('User canceled process termination')
                return False
            
            log.info('User confirmed, killing processes...')
            try:
                self.controller.killRunningProcesses()
                log.info('killRunningProcesses completed successfully')
            except Exception as e:
                log.error(f'EXCEPTION in killRunningProcesses: {type(e).__name__}: {e}')
                import traceback
                log.error(f'Traceback:\n{traceback.format_exc()}')
                return False
        
        elif exiting:
            log.info('No running processes, checking exit confirmation')
            result = self.confirmExit()
            log.info(f'confirmExit returned: {result}')
            return result
        
        log.info('dealWithRunningProcesses returning True')
        return True

    # returns True if we can proceed with: creating/opening a project or exiting
    def dealWithCurrentProject(self, exiting=False):
        """
        Handle current project state (unsaved changes, running processes) before major operations.
        Returns True if we can proceed, False if user canceled.
        """
        log.info(f'=== dealWithCurrentProject called (exiting={exiting}) ===')
        log.info(f'Project dirty state: {self.viewState.dirty}')
        
        if self.viewState.dirty:   # if there are unsaved changes, show save dialog first
            log.info('Unsaved changes detected, calling saveOrDiscard')
            if not self.saveOrDiscard():                                # if the user canceled, stop
                log.info('User canceled save/discard, aborting operation')
                return False
            log.info('saveOrDiscard completed successfully')
        
        log.info('Proceeding to dealWithRunningProcesses')
        result = self.dealWithRunningProcesses(exiting)                   # deal with running processes
        log.info(f'dealWithCurrentProject returning: {result}')
        return result

    def confirmExit(self):
        """
        Show exit confirmation dialog.
        Returns True if user confirms exit, False otherwise.
        """
        log.info('=== confirmExit called ===')
        message = "Are you sure to exit the program?"
        reply = self.yesNoDialog(message, 'Confirm')
        result = (reply == QtWidgets.QMessageBox.StandardButton.Yes)
        log.info(f'confirmExit returning: {result}')
        return result

    def killProcessConfirmation(self):
        """
        Show kill process confirmation dialog.
        Returns True if user confirms kill, False otherwise.
        """
        log.info('=== killProcessConfirmation called ===')
        message = "Are you sure you want to kill the selected processes?"
        reply = self.yesNoDialog(message, 'Confirm')
        result = (reply == QtWidgets.QMessageBox.StandardButton.Yes)
        log.info(f'killProcessConfirmation returning: {result}')
        return result

    def connectCreateNewProject(self):
        self.ui.actionNew.triggered.connect(self.createNewProject)

    def createNewProject(self):
        if self.dealWithCurrentProject():
            log.info('Creating new project..')
            self.controller.createNewProject()

    def connectOpenExistingProject(self):
        self.ui.actionOpen.triggered.connect(self.openExistingProject)

    def openExistingProject(self):
        if self.dealWithCurrentProject():
            filename = QtWidgets.QFileDialog.getOpenFileName(
                self.ui.centralwidget, 'Open project', self.controller.getCWD(),
                filter='Legion session (*.legion);; Sparta session (*.sprt)')[0]
        
            if not filename == '':                                      # check for permissions
                if not os.access(filename, os.R_OK) or not os.access(filename, os.W_OK):
                    log.info('Insufficient permissions to open this file.')
                    QtWidgets.QMessageBox.warning(self.ui.centralwidget, 'Warning',
                                                          "You don't have the necessary permissions on this file.",
                                                          "Ok")
                    return

                if '.legion' in str(filename):
                    projectType = 'legion'
                elif '.sprt' in str(filename):
                    projectType = 'sparta'
                                
                self.controller.openExistingProject(filename, projectType)
                self.viewState.firstSave = False  # overwrite this variable because we are opening an existing file
                # do not show the overlay because the hosttableview is already populated
                self.displayAddHostsOverlay(False)
            else:
                log.info('No file chosen..')

    def connectSaveProject(self):
        self.ui.actionSave.triggered.connect(self.saveProject)
    
    def saveProject(self):
        self.ui.statusbar.showMessage('Saving..')
        if self.viewState.firstSave:
            self.saveProjectAs()
        else:
            log.info('Saving project..')
            self.controller.saveProject(self.viewState.lastHostIdClicked, self.ui.NotesTextEdit.toPlainText())

            self.setDirty(False)
            self.ui.statusbar.showMessage('Saved!', msecs=1000)
            log.info('Saved!')

    def connectSaveProjectAs(self):
        self.ui.actionSaveAs.triggered.connect(self.saveProjectAs)

    def saveProjectAs(self):
        self.ui.statusbar.showMessage('Saving..')
        log.info('Saving project..')

        self.controller.saveProject(self.viewState.lastHostIdClicked, self.ui.NotesTextEdit.toPlainText())

        filename = QtWidgets.QFileDialog.getSaveFileName(self.ui.centralwidget, 'Save project as',
                                                         self.controller.getCWD(), filter='Legion session (*.legion)',
                                                         options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)[0]
            
        while not filename =='':
            if not os.access(ntpath.dirname(str(filename)), os.R_OK) or not os.access(
                    ntpath.dirname(str(filename)), os.W_OK):
                log.info('Insufficient permissions on this folder.')
                reply = QtWidgets.QMessageBox.warning(self.ui.centralwidget, 'Warning',
                                                      "You don't have the necessary permissions on this folder.")
                
            else:
                if self.controller.saveProjectAs(filename):
                    break
                    
                if not str(filename).endswith('.legion'):
                    filename = str(filename) + '.legion'
                msgBox = QtWidgets.QMessageBox()
                reply = msgBox.question(self.ui.centralwidget, 'Confirm',
                                        "A file named \""+ntpath.basename(str(filename))+"\" already exists.  " +
                                        "Do you want to replace it?",
                                        QtWidgets.QMessageBox.StandardButton.Abort | QtWidgets.QMessageBox.StandardButton.Save)
            
                if reply == QtWidgets.QMessageBox.StandardButton.Save:
                    self.controller.saveProjectAs(filename, 1)          # replace
                    break

            filename = QtWidgets.QFileDialog.getSaveFileName(self.ui.centralwidget, 'Save project as', '.',
                                                             filter='Legion session (*.legion)',
                                                             options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)[0]

        if not filename == '':
            self.setDirty(False)
            self.viewState.firstSave = False
            self.ui.statusbar.showMessage('Saved!', msecs=1000)
            self.controller.updateOutputFolder()
            log.info('Saved!')
        else:
            log.info('No file chosen..')

    def saveOrDiscard(self):
        reply = QtWidgets.QMessageBox.question(
            self.ui.centralwidget, 'Confirm', "The project has been modified. Do you want to save your changes?",
            QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Save)
        
        if reply == QtWidgets.QMessageBox.StandardButton.Save:
            self.saveProject()
            return True
        elif reply == QtWidgets.QMessageBox.StandardButton.Discard:
            return True
        else:
            return False                                                # the user cancelled
            
    def closeProject(self):
        self.ui.statusbar.showMessage('Closing project..', msecs=1000)
        
        # Wait for NmapImporter thread to finish before cleanup (WITH TIMEOUT)
        try:
            if hasattr(self.controller, "nmapImporter") and self.controller.nmapImporter.isRunning():
                log.info("Waiting for NmapImporter thread to finish before closing project...")
                if not self.controller.nmapImporter.wait(5000):  # 5 second timeout
                    log.warning("NmapImporter thread did not finish in time, forcing termination")
                    self.controller.nmapImporter.terminate()
                    self.controller.nmapImporter.wait(2000)  # Wait 2 more seconds for termination
        except Exception as e:
            log.info(f"Error waiting for NmapImporter: {e}")
        
        self.controller.closeProject()
        self.removeToolTabs()  # to make them disappear from the UI
                                       # to make them disappear from the UI
                
    def connectAddHosts(self):
        self.ui.actionAddHosts.triggered.connect(self.connectAddHostsDialog)
        
    def connectAddHostsDialog(self):
        self.adddialog.cmdAddButton.setDefault(True)
        self.adddialog.txtHostList.setFocus(Qt.FocusReason.OtherFocusReason)
        self.adddialog.validationLabel.hide()
        self.adddialog.spacer.changeSize(15, 15)
        self.adddialog.show()
        self.adddialog.cmdAddButton.clicked.connect(self.callAddHosts)
        self.adddialog.cmdCancelButton.clicked.connect(self.adddialog.close)
        
    def callAddHosts(self):
        hostListStr = str(self.adddialog.txtHostList.toPlainText()).replace(';',' ')
        nmapOptions = []
        scanMode = 'Unset'

        if validateNmapInput(hostListStr):
            self.adddialog.close()
            hostList = []
            splitTypes = [';', ' ', '\n']

            for splitType in splitTypes:
                hostListStr = hostListStr.replace(splitType, ';')

            hostList = hostListStr.split(';')
            hostList = [hostEntry for hostEntry in hostList if len(hostEntry) > 0]

            hostAddOptionControls = [self.adddialog.rdoScanOptTcpConnect, self.adddialog.rdoScanOptObfuscated,
                                     self.adddialog.rdoScanOptFin, self.adddialog.rdoScanOptNull,
                                     self.adddialog.rdoScanOptXmas, self.adddialog.rdoScanOptPingTcp,
                                     self.adddialog.rdoScanOptPingUdp, self.adddialog.rdoScanOptPingDisable,
                                     self.adddialog.rdoScanOptPingRegular, self.adddialog.rdoScanOptPingSyn,
                                     self.adddialog.rdoScanOptPingAck, self.adddialog.rdoScanOptPingTimeStamp,
                                     self.adddialog.rdoScanOptPingNetmask, self.adddialog.chkScanOptFragmentation]
            nmapOptions = []

            if self.adddialog.rdoModeOptEasy.isChecked():
                scanMode = 'Easy'
            else:
                scanMode = 'Hard'
                for hostAddOptionControl in hostAddOptionControls:
                    if hostAddOptionControl.isChecked():
                       nmapOptionValue = str(hostAddOptionControl.toolTip())
                       nmapOptionValueSplit = nmapOptionValue.split('[')
                       if len(nmapOptionValueSplit) > 1:
                           nmapOptionValue = nmapOptionValueSplit[1].replace(']','')
                           nmapOptions.append(nmapOptionValue)
                nmapOptions.append(str(self.adddialog.txtCustomOptList.text()))
            # Hostname resolution option
            # Remove any existing -n or -R from nmapOptions to avoid conflicts
            nmapOptions = [opt for opt in nmapOptions if opt.strip() not in ['-n', '-R']]
            if self.adddialog.chkResolveHostnames.isChecked():
                nmapOptions.append('-R')
            else:
                nmapOptions.append('-n')

            for hostListEntry in hostList:
                self.controller.addHosts(targetHosts=hostListEntry,
                                         runHostDiscovery=self.adddialog.chkDiscovery.isChecked(),
                                         runStagedNmap=self.adddialog.chkNmapStaging.isChecked(),
                                         nmapSpeed=self.adddialog.sldScanTimingSlider.value(),
                                         scanMode=scanMode,
                                         nmapOptions=nmapOptions,
                                         enableIPv6=self.adddialog.chkEnableIPv6.isChecked())
            self.adddialog.cmdAddButton.clicked.disconnect()   # disconnect all the signals from that button
        else:
            self.adddialog.spacer.changeSize(0,0)
            self.adddialog.validationLabel.show()
            self.adddialog.cmdAddButton.clicked.disconnect()  # disconnect all the signals from that button
            self.adddialog.cmdAddButton.clicked.connect(self.callAddHosts)

    ###
    
    def connectImportNmap(self):
        self.ui.actionImportNmap.triggered.connect(self.importNmap)

    def importNmap(self):
        self.ui.statusbar.showMessage('Importing nmap xml..', msecs=1000)
        filename = QtWidgets.QFileDialog.getOpenFileName(self.ui.centralwidget, 'Choose nmap file',
                                                         self.controller.getCWD(), filter='XML file (*.xml)')[0]
        log.info('Importing nmap xml from {0}...'.format(str(filename)))
        if not filename == '':
            if not os.access(filename, os.R_OK):                        # check for read permissions on the xml file
                log.info('Insufficient permissions to read this file.')
                QtWidgets.QMessageBox.warning(self.ui.centralwidget, 'Warning',
                                                      "You don't have the necessary permissions to read this file.",
                                                      "Ok")
                return

            self.controller.nmapImporter.setFilename(str(filename))
            self.importProgressBar.setValue(0)
            log.debug(f"importNmap: setVisible(True) called, importProgressBar id={id(self.importProgressBar)}, \
                       parent={self.importProgressBar.parent()}")
            self.importProgressBar.setVisible(True)
            self.cancelImportButton.setVisible(True)
            self.importInProgress = True
            self.controller.nmapImporter.start()
            self.controller.copyNmapXMLToOutputFolder(str(filename))
        else:
            log.info('No file chosen..')

    def cancelImportNmap(self):
        try:
            if hasattr(self.controller, "nmapImporter"):
                log.info("Canceling Nmap import at user request.")
                self.controller.nmapImporter.cancel()
        except Exception as e:
            log.info(f"Error canceling Nmap import: {e}")

    def updateImportProgress(self, progress, title):
        # If import is not in progress, always hide the bar and cancel button, and force UI update
        if not getattr(self, "importInProgress", True):
            self.importProgressBar.setVisible(False)
            self.cancelImportButton.setVisible(False)
            self.importProgressBar.repaint()
            if hasattr(self, "ui") and hasattr(self.ui, "statusbar"):
                self.ui.statusbar.repaint()
            return
        # If "Processing ports..." just reached 100%, show "Finishing up..." and hide cancel button
        if title.lower().startswith("processing ports") and progress >= 100:
            self.importProgressBar.setValue(100)
            self.importProgressBar.setFormat("Finishing up... (100%)")
            self.cancelImportButton.setVisible(False)
            return
        self.importProgressBar.setValue(int(progress))
        self.importProgressBar.setFormat(f"{title} ({int(progress)}%)")
        if "almost done" in title.lower():
            log.debug(f"updateImportProgress: 'Almost done...' progressBar id={id(self.importProgressBar)}, \
                      parent={self.importProgressBar.parent()}, format={self.importProgressBar.format()}, \
                        visible={self.importProgressBar.isVisible()}")
        # Hide the cancel button if we're finishing up, but keep the progress bar visible until import is truly done
        if title.lower().startswith("finishing up") and progress >= 100:
            self.cancelImportButton.setVisible(False)
        # Only hide the progress bar when the import is truly finished, not just when any stage hits 100%
        # The progress bar will be hidden by a separate signal/slot when the import is done.

    def importFinished(self):
        import traceback
        log.debug("importFinished called - hiding progress bar and cancel button")
        log.debug(f"importFinished: importProgressBar id={id(self.importProgressBar)}, \
                  parent={self.importProgressBar.parent()}")
        log.debug("".join(traceback.format_stack()))
        self.importInProgress = False
        self.importProgressBar.setVisible(False)
        log.debug(f"importFinished: setVisible(False) called, visible={self.importProgressBar.isVisible()}")
        self.cancelImportButton.setVisible(False)
        log.debug(f"importFinished: cancelImportButton setVisible(False), \
                  visible={self.cancelImportButton.isVisible()}")
        self.importProgressBar.repaint()
        if hasattr(self, "ui") and hasattr(self.ui, "statusbar"):
            self.ui.statusbar.repaint()
        # Delayed hide as failsafe
        from PyQt6.QtCore import QTimer
        def delayed_hide():
            log.debug("Delayed hide of progress bar and cancel button")
            log.debug(f"delayed_hide: importProgressBar id={id(self.importProgressBar)}, \
                      parent={self.importProgressBar.parent()}")
            log.debug("".join(traceback.format_stack()))
            self.importProgressBar.setVisible(False)
            log.debug(f"delayed_hide: setVisible(False) called, visible={self.importProgressBar.isVisible()}")
            self.cancelImportButton.setVisible(False)
            log.debug(f"delayed_hide: cancelImportButton setVisible(False), \
                      visible={self.cancelImportButton.isVisible()}")
            self.importProgressBar.repaint()
            if hasattr(self, "ui") and hasattr(self.ui, "statusbar"):
                self.ui.statusbar.repaint()
        QTimer.singleShot(2000, delayed_hide)
    def connectSettings(self):
        self.ui.actionSettings.triggered.connect(self.showSettingsWidget)

    def showSettingsWidget(self):
        self.settingsWidget.resetTabIndexes()
        self.settingsWidget.show()

    def applySettings(self):
        if self.settingsWidget.applySettings():
            self.controller.applySettings(self.settingsWidget.settings)
            self.settingsWidget.hide()

    def cancelSettings(self):
        log.debug('Cancel button pressed')  # LEO: we can use this later to test ESC button once implemented.
        self.settingsWidget.hide()
        self.controller.cancelSettings()

    def connectHelp(self):
        self.ui.actionHelp.triggered.connect(self.helpDialog.show)

    def connectConfig(self):
        self.ui.actionConfig.triggered.connect(self.configDialog.show)

    def connectExportJson(self):
        self.ui.actionExportJson.triggered.connect(self.exportAsJson)

    def connectAppExit(self):
        self.ui.actionExit.triggered.connect(self.appExit)

    def exportAsJson(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.ui.centralwidget, 'Export as JSON', self.controller.getCWD(), filter='JSON file (*.json)')
        if filename:
            self.controller.exportAsJson(filename)

    def appExit(self):
        # Prevent re-entry into exit sequence
        if hasattr(self, '_exiting') and self._exiting:
            log.info('appExit already in progress, ignoring duplicate call')
            return
        
        self._exiting = True
        log.info('appExit called - setting exit flag')
        
        if self.dealWithCurrentProject(True):  # the parameter indicates that we are exiting the application
            self.closeProject()
            log.info('Exiting application..')
            
            # Directly quit without deferring - event filter will not trigger again due to flag
            QCoreApplication.quit()



    ### TABLE ACTIONS ###

    def connectAddHostsOverlayClick(self):
        self.ui.addHostsOverlay.selectionChanged.connect(self.connectAddHostsDialog)

    def connectHostTableClick(self):
        self.ui.HostsTableView.clicked.connect(self.hostTableClick)

    # TODO: review - especially what tab is selected when coming from another host
    def hostTableClick(self):
        log.debug("========== hostTableClick START ==========")
        
        if self.ui.HostsTableView.selectionModel().selectedRows():
            row = self.ui.HostsTableView.selectionModel().selectedRows()[len(self.ui.HostsTableView.
                selectionModel().selectedRows())-1].row()
            ip = self.HostsTableModel.getHostIPForRow(row)
            log.debug(f"hostTableClick - Selected row {row}, ip = {ip}")
            
            self.viewState.ip_clicked = ip
            save = self.ui.ServicesTabWidget.currentIndex()
            log.debug(f"hostTableClick - Saved ServicesTabWidget index = {save}")
            log.debug("hostTableClick - About to call removeToolTabs()")
            
            self.removeToolTabs()
            log.debug("hostTableClick - removeToolTabs() completed")
            log.debug("hostTableClick - About to call restoreToolTabsForHost()")
            
            self.restoreToolTabsForHost(self.viewState.ip_clicked)
            log.debug("hostTableClick - restoreToolTabsForHost() completed")
            log.debug(f"hostTableClick - Restoring ServicesTabWidget index to {save}")
            
            # Display services tab if we are coming from a dynamic tab (non-fixed)
            # Block signals to prevent currentChanged from firing and resetting colors
            self.ui.ServicesTabWidget.blockSignals(True)
            self.ui.ServicesTabWidget.setCurrentIndex(save)
            self.ui.ServicesTabWidget.blockSignals(False)
            
            log.debug("hostTableClick - About to call updateRightPanel()")
            
            self.updateRightPanel(self.viewState.ip_clicked)
            log.debug("hostTableClick - updateRightPanel() completed")
        else:
            log.debug("hostTableClick - No rows selected")
            self.removeToolTabs()
            log.debug("hostTableClick - About to call updateRightPanel with empty string")
            self.updateRightPanel('')
            log.debug("hostTableClick - updateRightPanel() completed")
            
        log.debug("========== hostTableClick END ==========\n")




    ###
    
    def connectServiceNamesTableClick(self):
        self.ui.ServiceNamesTableView.clicked.connect(self.serviceNamesTableClick)

    def hostTableDoubleClick(self, index):
        # Get the item from the model using the index
        model = self.ui.HostsTableView.model()
        row = index.row()
        new_index = model.index(row, 3)
        data = model.data(new_index, QtCore.Qt.ItemDataRole.DisplayRole)
        if data:
            self.controller.copyToClipboard(data)
        
    def serviceNamesTableClick(self):
        if self.ui.ServiceNamesTableView.selectionModel().selectedRows():
            row = self.ui.ServiceNamesTableView.selectionModel().selectedRows()[len(
                self.ui.ServiceNamesTableView.selectionModel().selectedRows())-1].row()
            self.viewState.service_clicked = self.ServiceNamesTableModel.getServiceNameForRow(row)
            self.updatePortsByServiceTableView(self.viewState.service_clicked)
        
    ###
    
    def connectToolsTableClick(self):
        self.ui.ToolsTableView.clicked.connect(self.toolsTableClick)
        
    def toolsTableClick(self):
        if self.ui.ToolsTableView.selectionModel().selectedRows():
            row = self.ui.ToolsTableView.selectionModel().selectedRows()[len(
                self.ui.ToolsTableView.selectionModel().selectedRows())-1].row()
            self.viewState.tool_clicked = self.ToolsTableModel.getToolNameForRow(row)
            self.updateToolHostsTableView(self.viewState.tool_clicked)
            # if we clicked on the screenshooter we need to display the screenshot widget
            self.displayScreenshots(self.viewState.tool_clicked == 'screenshooter')

        # update the updateToolHostsTableView when the user closes all the host tabs
        # TODO: this doesn't seem right
        else:
            self.updateToolHostsTableView('')
            self.ui.DisplayWidgetLayout.addWidget(self.ui.toolOutputTextView)
            
    ###
    
    def connectScriptTableClick(self):
        self.ui.ScriptsTableView.clicked.connect(self.scriptTableClick)
        
    def scriptTableClick(self):
        if self.ui.ScriptsTableView.selectionModel().selectedRows():
            row = self.ui.ScriptsTableView.selectionModel().selectedRows()[len(
                self.ui.ScriptsTableView.selectionModel().selectedRows())-1].row()
            self.viewState.script_clicked = self.ScriptsTableModel.getScriptDBIdForRow(row)
            self.updateScriptsOutputView(self.viewState.script_clicked)
                
    ###

    def connectToolHostsClick(self):
        self.ui.ToolHostsTableView.clicked.connect(self.toolHostsClick)
    
    #for matching
    def ensureLabelUpdated(self, tab):
        """Ensure the label in a tab is properly displayed if matches exist"""
        if not tab:
            return
            
        matches = tab.property('matches')
        label = tab.findChild(QtWidgets.QLabel)
        
        if matches and label:
            matchText = 'Matches: ' + str(matches)
            label.setText(matchText)
            label.setVisible(True)
            label.setStyleSheet("color: black; background-color: yellow; font-weight: bold;")
            #print(f"DEBUG ensureLabelUpdated: Set label for {tab.objectName()}")


    def toolHostsClick(self):
        if self.ui.ToolHostsTableView.selectionModel().selectedRows():
            row = self.ui.ToolHostsTableView.selectionModel().selectedRows()[len(
                self.ui.ToolHostsTableView.selectionModel().selectedRows())-1].row()
            self.viewState.tool_host_clicked = self.ToolHostsTableModel.getProcessIdForRow(row)
            ip = self.ToolHostsTableModel.getIpForRow(row)
            
            if self.viewState.tool_clicked == 'screenshooter':
                filename = self.ToolHostsTableModel.getOutputfileForRow(row)
                self.ui.ScreenshotWidget.open(str(self.controller.getOutputFolder())+'/screenshots/'+str(filename))
            
            else:
                # restore the tool output textview now showing in the tools display panel to its original host tool tab
                self.restoreToolTabWidget()

                # remove the tool output currently in the tools display panel (if any)
                if self.ui.DisplayWidget.findChild(QtWidgets.QTextEdit):
                    self.ui.DisplayWidget.findChild(QtWidgets.QTextEdit).setParent(None)
                
                # Remove any existing display labels
                for label in self.ui.DisplayWidget.findChildren(QtWidgets.QLabel):
                    label.setParent(None)

                tabs = []
                if str(ip) in self.viewState.hostTabs:
                    tabs = self.viewState.hostTabs[str(ip)]
                
                for tab in tabs:
                    text_widget = tab.findChild(QtWidgets.QTextEdit)
                    if text_widget and str(text_widget.property('dbId')) == str(self.viewState.tool_host_clicked):
                        # ENSURE the label in the tab is updated first
                        self.ensureLabelUpdated(tab)
                        
                        # Check if tab has matches and create a COPY of the label for DisplayWidget
                        label_in_tab = tab.findChild(QtWidgets.QLabel)
                        matches = tab.property('matches')
                        
                        if label_in_tab and matches:
                            # Create a NEW label for DisplayWidget (don't move the original)
                            display_label = QtWidgets.QLabel()
                            display_label.setText(label_in_tab.text())
                            display_label.setStyleSheet(label_in_tab.styleSheet())
                            display_label.setVisible(True)
                            self.ui.DisplayWidgetLayout.addWidget(display_label)
                        
                        # Add the text widget (this DOES get moved)
                        self.ui.DisplayWidgetLayout.addWidget(text_widget)
                        break

    ###

    def connectAddHostClick(self):
        self.ui.AddHostButton.clicked.connect(self.connectAddHostsDialog)

    def connectAdvancedFilterClick(self):
        self.ui.FilterAdvancedButton.clicked.connect(self.advancedFilterClick)

    def advancedFilterClick(self, current):
        # to make sure we don't show filters than have been clicked but cancelled
        self.filterdialog.setCurrentFilters(self.viewState.filters.getFilters())
        self.filterdialog.show()

    def updateFilter(self):
        f = self.filterdialog.getFilters()
        self.viewState.filters.apply(f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8])
        self.ui.keywordTextInput.setText(" ".join(f[8]))
        self.updateInterface()

    def updateFilterKeywords(self):
        self.viewState.filters.setKeywords(unicode(self.ui.keywordTextInput.text()).split())
        self.updateInterface()

    ###
    
    def connectTableDoubleClick(self):
        self.ui.ServicesTableView.doubleClicked.connect(self.tableDoubleClick)
        self.ui.ToolHostsTableView.doubleClicked.connect(self.tableDoubleClick)
        self.ui.OsHostsTableView.doubleClicked.connect(self.tableDoubleClick)
        self.ui.CvesTableView.doubleClicked.connect(self.rightTableDoubleClick)
 
    def rightTableDoubleClick(self, signal):
        row = signal.row()  # RETRIEVES ROW OF CELL THAT WAS DOUBLE CLICKED
        column = signal.column()  # RETRIEVES COLUMN OF CELL THAT WAS DOUBLE CLICKED
        model = self.CvesTableModel
        cell_dict = model.itemData(signal)  # RETURNS DICT VALUE OF SIGNAL
        cell_value = cell_dict.get(0)  # RETRIEVE VALUE FROM DICT
 
        index = signal.sibling(row, 0)
        index_dict = model.itemData(index)
        index_value = index_dict.get(0)
        log.info('Row {}, Column {} clicked - value: {}\nColumn 1 contents: {}'
                 .format(row, column, cell_value, index_value))

        ## Does not work under WSL!
        df = pd.DataFrame([cell_value])
        df.to_clipboard(index = False, header = False)


    def tableDoubleClick(self):
        tab = self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex())

        if tab == 'Services':
            row = self.ui.ServicesTableView.selectionModel().selectedRows()[len(
                self.ui.ServicesTableView.selectionModel().selectedRows())-1].row()
            ip = self.PortsByServiceTableModel.getIpForRow(row)
        elif tab == 'Tools':
            row = self.ui.ToolHostsTableView.selectionModel().selectedRows()[len(
                self.ui.ToolHostsTableView.selectionModel().selectedRows())-1].row()
            ip = self.ToolHostsTableModel.getIpForRow(row)
        elif tab == 'OS':
            if not self.ui.OsHostsTableView.selectionModel().selectedRows():
                return
            row = self.ui.OsHostsTableView.selectionModel().selectedRows()[
                len(self.ui.OsHostsTableView.selectionModel().selectedRows())-1].row()
            ip = self.OsHostsTableModel.getIpForRow(row)
        else:
            return

        hostrow = self.HostsTableModel.getRowForIp(ip)
        if hostrow is not None:
            self.ui.HostsTabWidget.setCurrentIndex(0)
            self.ui.HostsTableView.selectRow(hostrow)
            self.hostTableClick()
    
    ###
    
    def connectSwitchTabClick(self):
        self.ui.HostsTabWidget.currentChanged.connect(self.switchTabClick)

    def switchTabClick(self):
        log.debug("========== switchTabClick START ==========")
        if self.ServiceNamesTableModel:
            selectedTab = self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex())
            log.debug(f"switchTabClick - selectedTab = '{selectedTab}'")
            log.debug(f"switchTabClick - BEFORE: unread_tabs = {self.unread_tabs}")
            
            if selectedTab == 'Hosts':
                log.debug("switchTabClick - Entering Hosts tab logic")
                log.debug("switchTabClick - About to insert fixed tabs back")
                
                # Save current tab index BEFORE operations
                saved_tab_index = self.ui.ServicesTabWidget.currentIndex()
                log.debug(f"switchTabClick - Saved tab index = {saved_tab_index}")
                
                # Set flag to prevent resetTabHighlight from resetting colors
                log.debug("switchTabClick - Setting suppress_reset_highlight flag")
                self.suppress_reset_highlight = True
                
                self.ui.ServicesTabWidget.insertTab(1,self.ui.ScriptsTab,("Scripts"))
                self.ui.ServicesTabWidget.insertTab(2,self.ui.InformationTab,("Information"))
                self.ui.ServicesTabWidget.insertTab(3,self.ui.CvesRightTab,("CVEs"))
                self.ui.ServicesTabWidget.insertTab(4,self.ui.NotesTab,("Notes"))
                
                log.debug("switchTabClick - Fixed tabs inserted")
                log.debug(f"switchTabClick - ServicesTabWidget count = {self.ui.ServicesTabWidget.count()}")
                
                self.ui.ServicesTabWidget.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
                self.ui.ServicesTabWidget.tabBar().setTabButton(1, QTabBar.ButtonPosition.RightSide, None)
                self.ui.ServicesTabWidget.tabBar().setTabButton(2, QTabBar.ButtonPosition.RightSide, None)
                self.ui.ServicesTabWidget.tabBar().setTabButton(3, QTabBar.ButtonPosition.RightSide, None)
                self.ui.ServicesTabWidget.tabBar().setTabButton(4, QTabBar.ButtonPosition.RightSide, None)
                
                log.debug("switchTabClick - About to call restoreToolTabWidget()")
                self.restoreToolTabWidget()
                log.debug("switchTabClick - restoreToolTabWidget() completed")
                
                # Always restore tool tabs for the current host BEFORE preserving colors
                if self.viewState.ip_clicked:
                    log.debug(f"switchTabClick - Restoring tool tabs for host {self.viewState.ip_clicked}")
                    self.restoreToolTabsForHost(self.viewState.ip_clicked)
                    log.debug("switchTabClick - Tool tabs restored")
                
                # Preserve colors while flag is set (AFTER all tabs are added)
                log.debug("switchTabClick - About to call preserveFixedTabColors()")
                self.preserveFixedTabColors()
                log.debug("switchTabClick - preserveFixedTabColors() completed")
                
                # Restore the previously selected tab (clamped to fixed tabs only)
                if saved_tab_index >= self.fixedTabsCount:
                    saved_tab_index = 0  # Default to Services if was on a tool tab
                
                log.debug(f"switchTabClick - Restoring ServicesTabWidget to index {saved_tab_index}")
                self.ui.ServicesTabWidget.blockSignals(True)
                self.ui.ServicesTabWidget.setCurrentIndex(saved_tab_index)
                self.ui.ServicesTabWidget.blockSignals(False)
                log.debug(f"switchTabClick - ServicesTabWidget set to index {saved_tab_index}")
                
                # Manually reset the now-visible tab since it's being viewed
                # BUT skip Information tab - it has special blinking behavior
                current_tab_name = self.ui.ServicesTabWidget.tabText(saved_tab_index)
                log.debug(f"switchTabClick - Checking if '{current_tab_name}' should be reset")
                
                if current_tab_name != 'Information' and self.unread_tabs.get(current_tab_name, False):
                    log.debug(f"switchTabClick - Manually resetting '{current_tab_name}' tab to white (now visible)")
                    self.unread_tabs[current_tab_name] = False
                    self.ui.ServicesTabWidget.tabBar().setTabTextColor(saved_tab_index, self.app.palette().color(QtGui.QPalette.ColorRole.WindowText))
                    log.debug(f"switchTabClick - '{current_tab_name}' tab reset to white")
                elif current_tab_name == 'Information' and self.unread_tabs.get(current_tab_name, False):
                    # Information tab is visible - manually trigger its viewed behavior
                    log.debug("switchTabClick - Information tab is visible, triggering blinking")
                    self.hostInfoWidget.onTabViewed()
                    self.unread_tabs['Information'] = False
                    self.ui.ServicesTabWidget.tabBar().setTabTextColor(saved_tab_index, self.app.palette().color(QtGui.QPalette.ColorRole.WindowText))
                    log.debug("switchTabClick - Information tab reset to white with blinking")
                else:
                    log.debug(f"switchTabClick - NOT resetting '{current_tab_name}' (not unread)")
                
                if self.viewState.lazy_update_hosts == True:
                    log.debug("switchTabClick - lazy_update_hosts is True, calling updateHostsTableView()")
                    self.updateHostsTableView()
                
                log.debug("switchTabClick - About to call hostTableClick()")
                self.hostTableClick()
                log.debug("switchTabClick - hostTableClick() completed")
                
                # Use QTimer to clear flag AND reapply colors after queued events process
                log.debug("switchTabClick - Scheduling flag clear and color reapply via QTimer.singleShot()")
                def clearFlagAndReapplyColors():
                    log.debug("_clearFlagAndReapplyColors - Clearing suppress_reset_highlight flag")
                    self.suppress_reset_highlight = False
                    log.debug("_clearFlagAndReapplyColors - Reapplying fixed tab colors")
                    self.preserveFixedTabColors()
                    # Reset visible tab again if needed (except Information)
                    visible_index = self.ui.ServicesTabWidget.currentIndex()
                    visible_name = self.ui.ServicesTabWidget.tabText(visible_index)
                    if visible_name != 'Information' and visible_index < self.fixedTabsCount and self.unread_tabs.get(visible_name, False):
                        self.unread_tabs[visible_name] = False
                        self.ui.ServicesTabWidget.tabBar().setTabTextColor(visible_index, self.app.palette().color(QtGui.QPalette.ColorRole.WindowText))
                        log.debug(f"_clearFlagAndReapplyColors - Reset {visible_name} to white")
                
                QtCore.QTimer.singleShot(100, clearFlagAndReapplyColors)
                
            elif selectedTab == 'Services':
                log.debug("switchTabClick - Entering Services tab logic")
                self.ui.ServicesTabWidget.setCurrentIndex(0)
                self.removeToolTabs(0)
                self.controller.saveProject(self.viewState.lastHostIdClicked, self.ui.NotesTextEdit.toHtml())
                if self.viewState.lazy_update_services == True:
                    self.updateServiceNamesTableView()
                    self.serviceNamesTableClick()
                    
            elif selectedTab == 'Tools':
                log.debug("switchTabClick - Entering Tools tab logic")
                # Set flag when switching TO Tools to preserve unread_tabs state
                log.debug("switchTabClick - Setting suppress_reset_highlight flag for Tools tab")
                self.suppress_reset_highlight = True
                
                log.debug("switchTabClick - About to call updateToolsTableView()")
                self.updateToolsTableView()
                log.debug("switchTabClick - updateToolsTableView() completed")
                
                # Clear flag with timer and reapply colors
                def clearFlagForTools():
                    log.debug("clearFlagForTools - Clearing flag and reapplying colors")
                    self.suppress_reset_highlight = False
                    self.preserveFixedTabColors()
                
                QtCore.QTimer.singleShot(100, clearFlagForTools)
                
            elif selectedTab == 'OS':
                log.debug("switchTabClick - Entering OS tab logic")
                if self.viewState.lazy_update_os or not self.OsListTableModel:
                    self.updateOsListView()
                else:
                    self.updateOsHostsTableView(self.viewState.os_clicked or 'Unknown')
            
            log.debug("switchTabClick - About to call displayToolPanel()")
            self.displayToolPanel(selectedTab == 'Tools')
            log.debug("switchTabClick - displayToolPanel() completed")
            
            log.debug(f"switchTabClick - AFTER: unread_tabs = {self.unread_tabs}")
            log.debug("========== switchTabClick END ==========\n")




    
    def _clearSuppressFlag(self):
        """Helper to clear the suppress_reset_highlight flag after queued events process"""
        log.debug("_clearSuppressFlag - Clearing suppress_reset_highlight flag")
        self.suppress_reset_highlight = False

    ###

    def connectSwitchMainTabClick(self):
        self.ui.MainTabWidget.currentChanged.connect(self.switchMainTabClick)

    def switchMainTabClick(self):
        selectedTab = self.ui.MainTabWidget.tabText(self.ui.MainTabWidget.currentIndex())
        
        if selectedTab == 'Scan':
            self.switchTabClick()
        
        elif selectedTab == 'Brute':
            self.ui.BruteTabWidget.currentWidget().runButton.setFocus()
            self.restoreToolTabWidget()

        # in case the Brute tab was red because hydra found stuff, change it back to black
        self.ui.MainTabWidget.tabBar().setTabTextColor(1, QtGui.QColor())

    ###
    # indicates that a context menu is showing so that the ui doesn't get updated disrupting the user
    def setVisible(self):
        self.viewState.menuVisible = True

    # indicates that a context menu has now closed and any pending ui updates can take place now
    def setInvisible(self):
        self.viewState.menuVisible = False
    ###
    
    def connectHostsTableContextMenu(self):
        self.ui.HostsTableView.customContextMenuRequested.connect(self.contextMenuHostsTableView)

    def contextMenuHostsTableView(self, pos):
        if len(self.ui.HostsTableView.selectionModel().selectedRows()) > 0:
            row = self.ui.HostsTableView.selectionModel().selectedRows()[
                len(self.ui.HostsTableView.selectionModel().selectedRows())-1].row()
            # because when we right click on a different host, we need to select it
            self.viewState.ip_clicked = self.HostsTableModel.getHostIPForRow(row)
            self.ui.HostsTableView.selectRow(row)                       # select host when right-clicked
            self.hostTableClick()

            menu, actions = self.controller.getContextMenuForHost(
                str(self.HostsTableModel.getHostCheckStatusForRow(row)))
            # Add Copy action
            copyAction = menu.addAction("Copy")
            addPortAction = menu.addAction("Add Port")
            menu.aboutToShow.connect(self.setVisible)
            menu.aboutToHide.connect(self.setInvisible)
            hostid = self.HostsTableModel.getHostIdForRow(row)
            action = menu.exec(self.ui.HostsTableView.viewport().mapToGlobal(pos))

            if action == copyAction:
                # Copy selected hosts' IP and Hostname to clipboard (tab-separated, one per line)
                selected_rows = self.ui.HostsTableView.selectionModel().selectedRows()
                clipboard_data = ""
                for idx in selected_rows:
                    ip = self.HostsTableModel.getHostIPForRow(idx.row())
                    hostname = self.HostsTableModel.getHostnameForRow(idx.row()) if hasattr(self.HostsTableModel, "getHostnameForRow") else ""
                    clipboard_data += f"{ip}\t{hostname}\n"
                clipboard = QtWidgets.QApplication.clipboard()
                clipboard.setText(clipboard_data.strip())
            elif action == addPortAction:
                dialog = AddPortDialog(self.ui.centralwidget)
                if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                    port_data = dialog.get_port_data()
                    # Pass the selected host's IP and port data to the controller
                    self.controller.addPortToHost(self.viewState.ip_clicked, port_data)
            elif action:
                self.controller.handleHostAction(self.viewState.ip_clicked, hostid, actions, action)

    ###

    def connectServiceNamesTableContextMenu(self):
        self.ui.ServiceNamesTableView.customContextMenuRequested.connect(self.contextMenuServiceNamesTableView)

    def contextMenuServiceNamesTableView(self, pos):
        if len(self.ui.ServiceNamesTableView.selectionModel().selectedRows()) > 0:
            row = self.ui.ServiceNamesTableView.selectionModel().selectedRows()[len(
                self.ui.ServiceNamesTableView.selectionModel().selectedRows())-1].row()
            self.viewState.service_clicked = self.ServiceNamesTableModel.getServiceNameForRow(row)
            self.ui.ServiceNamesTableView.selectRow(row)                # select service when right-clicked
            self.serviceNamesTableClick()

            menu, actions, shiftPressed = self.controller.getContextMenuForServiceName(self.viewState.service_clicked)
            menu.aboutToShow.connect(self.setVisible)
            menu.aboutToHide.connect(self.setInvisible)
            action = menu.exec(self.ui.ServiceNamesTableView.viewport().mapToGlobal(pos))

            if action:
                # because we will need to populate the right-side panel in order to select those rows
                self.serviceNamesTableClick()
                # we must only fetch the targets on which we haven't run the tool yet
                tool = None
                for i in range(0,len(actions)):                         # fetch the tool name
                    if action == actions[i][1]:
                        srvc_num = actions[i][0]
                        tool = self.controller.getSettings().portActions[srvc_num][1]
                        break

                if action.text() == 'Take screenshot':
                    tool = 'screenshooter'
                        
                targets = []  # get (IP,port,protocol) combinations for this service
                for row in range(self.PortsByServiceTableModel.rowCount("")):
                    targets.append([self.PortsByServiceTableModel.getIpForRow(row),
                                    self.PortsByServiceTableModel.getPortForRow(row),
                                    self.PortsByServiceTableModel.getProtocolForRow(row)])

                # if the user pressed SHIFT+Right-click, ignore the rule of only running the tool on targets on
                # which we haven't ran it yet
                if shiftPressed:
                    tool=None

                if tool:
                    # fetch the hosts that we already ran the tool on
                    hosts=self.controller.getHostsForTool(tool, 'FetchAll')
                    oldTargets = []
                    for i in range(0,len(hosts)):
                        oldTargets.append([hosts[i][5], hosts[i][6], hosts[i][7]])

                    # remove from the targets the hosts:ports we have already run the tool on
                    for host in oldTargets:
                        if host in targets:
                            targets.remove(host)
                
                self.controller.handleServiceNameAction(targets, actions, action)

    ###
    
    def connectToolHostsTableContextMenu(self):
        self.ui.ToolHostsTableView.customContextMenuRequested.connect(self.contextToolHostsTableContextMenu)

    def contextToolHostsTableContextMenu(self, pos):
        if len(self.ui.ToolHostsTableView.selectionModel().selectedRows()) > 0:
            
            row = self.ui.ToolHostsTableView.selectionModel().selectedRows()[len(
                self.ui.ToolHostsTableView.selectionModel().selectedRows())-1].row()
            ip = self.ToolHostsTableModel.getIpForRow(row)
            port = self.ToolHostsTableModel.getPortForRow(row)
            
            if port:
                serviceName = self.controller.getServiceNameForHostAndPort(ip, port)[0]

                menu, actions, terminalActions = self.controller.getContextMenuForPort(str(serviceName))
                menu.aboutToShow.connect(self.setVisible)
                menu.aboutToHide.connect(self.setInvisible)
     
                 # this can handle multiple host selection if we apply it in the future
                targets = []  # get (IP,port,protocol,serviceName) combinations for each selected row
                # context menu when the left services tab is selected
                for row in self.ui.ToolHostsTableView.selectionModel().selectedRows():
                    targets.append([self.ToolHostsTableModel.getIpForRow(row.row()),
                                    self.ToolHostsTableModel.getPortForRow(row.row()),
                                    self.ToolHostsTableModel.getProtocolForRow(row.row()),
                                    self.controller.getServiceNameForHostAndPort(
                                        self.ToolHostsTableModel.getIpForRow(row.row()),
                                        self.ToolHostsTableModel.getPortForRow(row.row()))[0]])
                    restore = True

                action = menu.exec(self.ui.ToolHostsTableView.viewport().mapToGlobal(pos))
     
                if action:
                    self.controller.handlePortAction(targets, actions, terminalActions, action, restore)
            
            else:   # in case there was no port, we show the host menu (without the portscan / mark as checked)
                host_row = self.HostsTableModel.getRowForIp(ip)
                if host_row is None:
                    log.warning(f"ToolHosts context menu: unable to find host row for IP {ip}")
                    return
                menu, actions = self.controller.getContextMenuForHost(
                    str(self.HostsTableModel.getHostCheckStatusForRow(host_row)), False)
                menu.aboutToShow.connect(self.setVisible)
                menu.aboutToHide.connect(self.setInvisible)
                hostid = self.HostsTableModel.getHostIdForRow(host_row)

                action = menu.exec(self.ui.ToolHostsTableView.viewport().mapToGlobal(pos))

                if action:
                    self.controller.handleHostAction(self.viewState.ip_clicked, hostid, actions, action)
    
    ###

    def connectServicesTableContextMenu(self):
        self.ui.ServicesTableView.customContextMenuRequested.connect(self.contextMenuServicesTableView)

    # this function is longer because there are two cases we are in the services table
    def contextMenuServicesTableView(self, pos):
        if len(self.ui.ServicesTableView.selectionModel().selectedRows()) > 0:
            # if there is only one row selected, get service name
            if len(self.ui.ServicesTableView.selectionModel().selectedRows()) == 1:
                row = self.ui.ServicesTableView.selectionModel().selectedRows()[len(
                    self.ui.ServicesTableView.selectionModel().selectedRows())-1].row()
                
                if self.ui.ServicesTableView.isColumnHidden(0):   # if we are in the services tab of the hosts view
                    serviceName = self.ServicesTableModel.getServiceNameForRow(row)
                else:   # if we are in the services tab of the services view
                    serviceName = self.PortsByServiceTableModel.getServiceNameForRow(row)
                    
            else:
                serviceName = '*'                                       # otherwise show full menu
                
            menu, actions, terminalActions = self.controller.getContextMenuForPort(serviceName)
            menu.aboutToShow.connect(self.setVisible)
            menu.aboutToHide.connect(self.setInvisible)

            targets = []   # get (IP,port,protocol,serviceName) combinations for each selected row
            if self.ui.ServicesTableView.isColumnHidden(0):
                for row in self.ui.ServicesTableView.selectionModel().selectedRows():
                    targets.append([self.ServicesTableModel.getIpForRow(row.row()),
                                    self.ServicesTableModel.getPortForRow(row.row()),
                                    self.ServicesTableModel.getProtocolForRow(row.row()),
                                    self.ServicesTableModel.getServiceNameForRow(row.row())])
                    restore = False
            
            else:   # context menu when the left services tab is selected
                for row in self.ui.ServicesTableView.selectionModel().selectedRows():
                    targets.append([self.PortsByServiceTableModel.getIpForRow(row.row()),
                                    self.PortsByServiceTableModel.getPortForRow(row.row()),
                                    self.PortsByServiceTableModel.getProtocolForRow(row.row()),
                                    self.PortsByServiceTableModel.getServiceNameForRow(row.row())])
                    restore = True

            action = menu.exec(self.ui.ServicesTableView.viewport().mapToGlobal(pos))

            if action:
                self.controller.handlePortAction(targets, actions, terminalActions, action, restore)
    
    ###

    def connectProcessesTableContextMenu(self):
        self.ui.ProcessesTableView.customContextMenuRequested.connect(self.contextMenuProcessesTableView)

    def contextMenuProcessesTableView(self, pos):
        if self.ui.ProcessesTableView.selectionModel() and self.ui.ProcessesTableView.selectionModel().selectedRows():
    
            menu = self.controller.getContextMenuForProcess()
            menu.aboutToShow.connect(self.setVisible)
            menu.aboutToHide.connect(self.setInvisible)

            selectedProcesses = []                                  # list of tuples (pid, status, procId)
            for row in self.ui.ProcessesTableView.selectionModel().selectedRows():
                pid = self.ProcessesTableModel.getProcessPidForRow(row.row())
                selectedProcesses.append([int(pid), self.ProcessesTableModel.getProcessStatusForRow(row.row()),
                                          self.ProcessesTableModel.getProcessIdForRow(row.row())])

            action = menu.exec(self.ui.ProcessesTableView.viewport().mapToGlobal(pos))

            if action:
                self.controller.handleProcessAction(selectedProcesses, action)

    ###
    
    def connectScreenshotContextMenu(self):
        self.ui.ScreenshotWidget.scrollArea.customContextMenuRequested.connect(self.contextMenuScreenshot)

    def contextMenuScreenshot(self, pos):
        menu = QMenu()

        zoomInAction = menu.addAction("Zoom in (25%)")
        zoomOutAction = menu.addAction("Zoom out (25%)")
        fitToWindowAction = menu.addAction("Fit to window")
        normalSizeAction = menu.addAction("Original size")

        menu.aboutToShow.connect(self.setVisible)
        menu.aboutToHide.connect(self.setInvisible)
        
        action = menu.exec(self.ui.ScreenshotWidget.scrollArea.viewport().mapToGlobal(pos))

        if action == zoomInAction:
            self.ui.ScreenshotWidget.zoomIn()
        elif action == zoomOutAction:
            self.ui.ScreenshotWidget.zoomOut()
        elif action == fitToWindowAction:
            self.ui.ScreenshotWidget.fitToWindow()
        elif action == normalSizeAction:
            self.ui.ScreenshotWidget.normalSize()
            
    #################### LEFT PANEL INTERFACE UPDATE FUNCTIONS ####################

    def updateHostsTableView(self):
        # Update the data source of the model with the hosts from the database
        self.HostsTableModel.setHosts(self.controller.getHostsFromDB(self.viewState.filters))

        # Set the viewState.lazy_update_hosts to False to indicate that it doesn't need to be updated anymore
        self.viewState.lazy_update_hosts = False

        ## Resize the OS column of the HostsTableView
        #self.ui.HostsTableView.horizontalHeader().resizeSection(1, 120)

        # Sort the model by the Host column in descending order
        self.HostsTableModel.sort(3, Qt.SortOrder.DescendingOrder)

        # Get the list of IPs from the model
        ips = []   # ensure that there is always something selected
        for row in range(self.HostsTableModel.rowCount("")):
            ips.append(self.HostsTableModel.getHostIPForRow(row))

        # Check if the IP we previously clicked is still visible
        if self.viewState.ip_clicked in ips:
            # Get the row for the IP we previously clicked
            row = self.HostsTableModel.getRowForIp(self.viewState.ip_clicked)
        else:
            # Select the first row
            row = 0

        # Check if the row is not None
        if row is not None:
            # Select the row in the HostsTableView
            self.ui.HostsTableView.selectRow(row)
            # Call the hostTableClick() method
            self.hostTableClick()

        # Resize the OS column of the HostsTableView
        self.ui.HostsTableView.horizontalHeader().resizeSection(1, 120)

        # Hide colmns we don't want
        for i in [0, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]:
            self.ui.HostsTableView.hideColumn(i)

        self.viewState.lazy_update_os = True

    def updateHostsTableViewX(self):
        headers = ["Id", "OS", "Accuracy", "Host", "IPv4", "IPv6", "Mac", "Status", "Hostname", "Vendor", "Uptime",
                   "Lastboot", "Distance", "CheckedHost", "Country Code", "State", "City", "Latitude", "Longitude",
                   "Count", "Closed"]
        self.HostsTableModel = HostsTableModel(self.controller.getHostsFromDB(self.viewState.filters), headers)
        self.ui.HostsTableView.setModel(self.HostsTableModel)
        #self.HostsTableModel.setHosts(self.controller.getHostsFromDB(self.viewState.filters))

        self.viewState.lazy_update_hosts = False  # to indicate that it doesn't need to be updated anymore

        # hide some columns
        for i in [0, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]:
            self.ui.HostsTableView.setColumnHidden(i, True)

        self.ui.HostsTableView.horizontalHeader().resizeSection(1, 120)
        self.HostsTableModel.sort(3, Qt.SortOrder.DescendingOrder)

        self.ui.HostsTableView.repaint()
        self.ui.HostsTableView.update()

        ips = []   # ensure that there is always something selected
        for row in range(self.HostsTableModel.rowCount("")):
            ips.append(self.HostsTableModel.getHostIPForRow(row))

        # the ip we previously clicked may not be visible anymore (eg: due to filters)
        if self.viewState.ip_clicked in ips:
            row = self.HostsTableModel.getRowForIp(self.viewState.ip_clicked)
        else:
            row = 0                                                     # or select the first row
            
        if not row == None:
            self.ui.HostsTableView.selectRow(row)
            self.hostTableClick()

        self.viewState.lazy_update_os = True

    def updateServiceNamesTableView(self):
        headers = ["Name"]
        self.ServiceNamesTableModel = ServiceNamesTableModel(
            self.controller.getServiceNamesFromDB(self.viewState.filters), headers)
        self.ui.ServiceNamesTableView.setModel(self.ServiceNamesTableModel)

        self.viewState.lazy_update_services = False   # to indicate that it doesn't need to be updated anymore

        services = []                                                   # ensure that there is always something selected
        for row in range(self.ServiceNamesTableModel.rowCount("")):
            services.append(self.ServiceNamesTableModel.getServiceNameForRow(row))

        # the service we previously clicked may not be visible anymore (eg: due to filters)
        if self.viewState.service_clicked in services:
            row = self.ServiceNamesTableModel.getRowForServiceName(self.viewState.service_clicked)
        else:
            row = 0                                                     # or select the first row
            
        if not row == None:
            self.ui.ServiceNamesTableView.selectRow(row)
            self.serviceNamesTableClick()

    def setupToolsTableView(self):
        headers = ["Progress", "Display", "Elapsed", "Percent Complete", "Pid", "Name", "Tool", "Host", "Port",
                   "Protocol", "Command", "Start time", "End time", "OutputFile", "Output", "Status", "Closed"]
        tools = self.controller.getProcessesFromDB(
            self.viewState.filters, showProcesses='noNmap',
            sort=self.toolsTableViewSort,
            ncol=self.toolsTableViewSortColumn)
        self.ToolsTableModel = ProcessesTableModel(self, self._dedupeTools(tools), headers)
        self.ui.ToolsTableView.setModel(self.ToolsTableModel)

    def refreshToolsTableModel(self):
        if not self.ToolsTableModel:
            return
        processes = self.controller.getProcessesFromDB(
            self.viewState.filters,
            showProcesses='noNmap',
            sort=self.toolsTableViewSort,
            ncol=self.toolsTableViewSortColumn
        )
        self.ToolsTableModel.setDataList(self._dedupeTools(processes))

    def updateToolsTableView(self):
        if self.ui.MainTabWidget.tabText(self.ui.MainTabWidget.currentIndex()) == 'Scan' and \
                self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex()) == 'Tools':
            processes = self.controller.getProcessesFromDB(
                self.viewState.filters,
                showProcesses='noNmap',
                sort=self.toolsTableViewSort,
                ncol=self.toolsTableViewSortColumn)
            self.ToolsTableModel.setDataList(self._dedupeTools(processes))
            self.ui.ToolsTableView.repaint()
            self.ui.ToolsTableView.update()

            self.viewState.lazy_update_tools = False  # to indicate that it doesn't need to be updated anymore

            # Hides columns we don't want to see
            column_count = self.ToolsTableModel.columnCount(None)
            for i in range(column_count):
                self.ui.ToolsTableView.setColumnHidden(i, i != 5)

            tools = []                                                  # ensure that there is always something selected
            for row in range(self.ToolsTableModel.rowCount("")):
                tools.append(self.ToolsTableModel.getToolNameForRow(row))

            # the tool we previously clicked may not be visible anymore (eg: due to filters)
            if self.viewState.tool_clicked in tools:
                row = self.ToolsTableModel.getRowForToolName(self.viewState.tool_clicked)
            else:
                row = 0                                                 # or select the first row

            if not row == None:
                self.ui.ToolsTableView.selectRow(row)
                self.toolsTableClick()

    def setupOsTabViews(self):
        headers = ["OS", "Hosts"]
        summary = self.controller.getOperatingSystemsSummary()
        self.OsListTableModel = OsSummaryTableModel(summary, headers)
        self.ui.OsListTableView.setModel(self.OsListTableModel)
        self.ui.OsListTableView.horizontalHeader().setStretchLastSection(False)
        self.ui.OsListTableView.horizontalHeader().resizeSection(0, 160)
        if self.OsListTableModel.columnCount(None) > 1:
            self.ui.OsListTableView.horizontalHeader().resizeSection(1, 80)
        self._ensureOsSelectionModelConnection()

        if summary:
            if self.viewState.os_clicked and self.OsListTableModel.getRowForOs(self.viewState.os_clicked) is not None:
                selected_os = self.viewState.os_clicked
            else:
                selected_os = summary[0].get('os')
                self.viewState.os_clicked = selected_os
            row = self.OsListTableModel.getRowForOs(selected_os)
            if row is not None:
                self.ui.OsListTableView.selectRow(row)
        else:
            self.viewState.os_clicked = 'Unknown'

        self.updateOsHostsTableView(self.viewState.os_clicked or 'Unknown')
        self.viewState.lazy_update_os = False

    def setupOsHostsTableModel(self):
        headers = ["IP", "Hostname", "OS", "Status"]
        self.OsHostsTableModel = OsHostsTableModel([], headers)
        self.ui.OsHostsTableView.setModel(self.OsHostsTableModel)
        self.ui.OsHostsTableView.horizontalHeader().setStretchLastSection(False)
        self.ui.OsHostsTableView.horizontalHeader().resizeSection(0, 150)
        self.ui.OsHostsTableView.horizontalHeader().resizeSection(1, 200)
        self.ui.OsHostsTableView.horizontalHeader().resizeSection(2, 200)

    def updateOsListView(self):
        summary = self.controller.getOperatingSystemsSummary()
        if not self.OsListTableModel:
            self.setupOsTabViews()
            return

        self.OsListTableModel.setEntries(summary)
        self._ensureOsSelectionModelConnection()

        if not summary:
            self.viewState.os_clicked = 'Unknown'
            self.updateOsHostsTableView('Unknown')
            self.viewState.lazy_update_os = False
            return

        selected_os = self.viewState.os_clicked
        if not selected_os and summary:
            selected_os = summary[0].get('os')
            self.viewState.os_clicked = selected_os

        row = self.OsListTableModel.getRowForOs(selected_os)
        if row is None and summary:
            row = 0
            self.viewState.os_clicked = self.OsListTableModel.getOsForRow(row)

        if row is not None:
            self.ui.OsListTableView.selectRow(row)

        self.updateOsHostsTableView(self.viewState.os_clicked or 'Unknown')
        self.viewState.lazy_update_os = False

    def updateOsHostsTableView(self, os_name):
        if not self.OsHostsTableModel:
            self.setupOsHostsTableModel()
        target_os = os_name or 'Unknown'
        hosts = self.controller.getHostsForOperatingSystem(target_os)
        self.OsHostsTableModel.setHosts(hosts)
        self.ui.OsHostsTableView.repaint()
        self.ui.OsHostsTableView.update()
        if not hosts:
            self.ui.OsHostsTableView.clearSelection()
        else:
            self.ui.OsHostsTableView.selectRow(0)

    def connectOsListClick(self):
        self.ui.OsListTableView.clicked.connect(self.osListClick)
        self._ensureOsSelectionModelConnection()

    def _osCurrentRowChanged(self, current, _previous):
        if not current.isValid():
            return
        self.osListClick(current)

    def _ensureOsSelectionModelConnection(self):
        selection_model = self.ui.OsListTableView.selectionModel()
        if selection_model and selection_model is not self._os_selection_model:
            if self._os_selection_model:
                try:
                    self._os_selection_model.currentRowChanged.disconnect(self._osCurrentRowChanged)
                except (TypeError, RuntimeError):
                    pass
            selection_model.currentRowChanged.connect(self._osCurrentRowChanged)
            self._os_selection_model = selection_model

    def osListClick(self, index):
        if not self.OsListTableModel:
            return
        os_name = self.OsListTableModel.getOsForRow(index.row())
        if os_name is None:
            return
        self.viewState.os_clicked = os_name
        self.updateOsHostsTableView(os_name)

    def connectOsHostsClick(self):
        self.ui.OsHostsTableView.clicked.connect(self.osHostsClick)
        self.ui.OsHostsTableView.doubleClicked.connect(self.osHostsDoubleClick)

    def osHostsClick(self, index):
        host_entry = self.OsHostsTableModel.getHostDisplay(index.row()) if self.OsHostsTableModel else None
        if not host_entry:
            return
        ip = host_entry.get('ip')
        hostname = host_entry.get('hostname')
        identifier = ip
        if hostname:
            identifier = f"{ip} ({hostname})"
        self.viewState.ip_clicked = identifier
        host_row = self.HostsTableModel.getRowForIp(ip)
        if host_row is not None:
            self.ui.HostsTableView.selectRow(host_row)
            self.hostTableClick()
        self.viewState.os_clicked = self.OsListTableModel.getOsForRow(
            self.ui.OsListTableView.selectionModel().currentIndex().row()
        ) if self.OsListTableModel else ''

    def osHostsDoubleClick(self, index):
        self.osHostsClick(index)

        
    #################### RIGHT PANEL INTERFACE UPDATE FUNCTIONS ####################
    
    def updateServiceTableView(self, hostIP):
        headers = ["Host", "Port", "Port", "Protocol", "State", "HostId", "ServiceId", "Name", "Product", "Version",
                   "Extrainfo", "Fingerprint"]
        self.ServicesTableModel = ServicesTableModel(
            self.controller.getPortsAndServicesForHostFromDB(hostIP, self.viewState.filters), headers)
        self.ui.ServicesTableView.setModel(self.ServicesTableModel)

        for i in range(0, len(headers)): # reset all the hidden columns
                self.ui.ServicesTableView.setColumnHidden(i, False)

        for i in [0,1,5,6,8,10,11]: # hide some columns
            self.ui.ServicesTableView.setColumnHidden(i, True)
        
        self.ServicesTableModel.sort(2, Qt.SortOrder.DescendingOrder) # sort by port by default (override default)
        self.highlightTab('Services')

    def updatePortsByServiceTableView(self, serviceName):
        headers = ["Host", "Port", "Port", "Protocol", "State", "HostId", "ServiceId", "Name", "Product", "Version",
                   "Extrainfo", "Fingerprint"]
        self.PortsByServiceTableModel = ServicesTableModel(
            self.controller.getHostsAndPortsForServiceFromDB(serviceName, self.viewState.filters), headers)
        self.ui.ServicesTableView.setModel(self.PortsByServiceTableModel)

        for i in range(0, len(headers)):# reset all the hidden columns
                self.ui.ServicesTableView.setColumnHidden(i, False)

        for i in [2,5,6,7,8,10,11]: # hide some columns
            self.ui.ServicesTableView.setColumnHidden(i, True)
        
        self.ui.ServicesTableView.horizontalHeader().resizeSection(0,165) # resize IP
        self.ui.ServicesTableView.horizontalHeader().resizeSection(1,65) # resize port
        self.ui.ServicesTableView.horizontalHeader().resizeSection(3,100) # resize protocol
        self.PortsByServiceTableModel.sort(0, Qt.SortOrder.DescendingOrder) # sort by IP by default (override default)

    def updateInformationView(self, hostIP):
        log.debug("=" * 60)
        log.debug("updateInformationView START")
        log.debug(f"  hostIP: {hostIP}")
        
        if hostIP:
            log.debug(f"  Calling getHostInformation for {hostIP}...")
            host = self.controller.getHostInformation(hostIP)
            log.debug(f"  Host query result: {host}")
            
            if host:
                log.debug(f"  Host EXISTS in database - updating Information tab with data")
                states = self.controller.getPortStatesForHost(host.id)
                counterOpen = counterClosed = counterFiltered = 0
                for s in states:
                    if s[0] == 'open':
                        counterOpen += 1
                    elif s[0] == 'closed':
                        counterClosed += 1
                    else:
                        counterFiltered += 1
                if host.state == 'closed':
                    counterClosed = 65535 - counterOpen - counterFiltered
                else:
                    counterFiltered = 65535 - counterOpen - counterClosed
                
                log.debug(f"  Updating widget with: status={host.status}, open={counterOpen}, closed={counterClosed}, filtered={counterFiltered}")
                self.hostInfoWidget.updateFields(
                    status=host.status, openPorts=counterOpen, closedPorts=counterClosed, filteredPorts=counterFiltered,
                    ipv4=host.ipv4, ipv6=host.ipv6, macaddr=host.macaddr, osMatch=host.osMatch,
                    osAccuracy=host.osAccuracy, vendor=host.vendor, asn=host.asn, isp=host.isp,
                    countryCode=host.countryCode, city=host.city, latitude=host.latitude, longitude=host.longitude
                )
                log.debug(f"  Widget updated successfully with host data")
            else:
                # Host doesn't exist in database - clear the widget
                log.debug(f"  Host DOES NOT EXIST in database - clearing Information tab")
                self.hostInfoWidget.updateFields(
                    status=None, openPorts=0, closedPorts=0, filteredPorts=0,
                    ipv4=None, ipv6=None, macaddr=None, osMatch=None,
                    osAccuracy=None, vendor=None, asn=None, isp=None,
                    countryCode=None, city=None, latitude=None, longitude=None
                )
                log.debug(f"  Widget cleared - host {hostIP} was deleted or doesn't exist")
        else:
            # No IP provided - clear the widget
            log.debug(f"  No hostIP provided (None or empty) - clearing Information tab")
            self.hostInfoWidget.updateFields(
                status=None, openPorts=0, closedPorts=0, filteredPorts=0,
                ipv4=None, ipv6=None, macaddr=None, osMatch=None,
                osAccuracy=None, vendor=None, asn=None, isp=None,
                countryCode=None, city=None, latitude=None, longitude=None
            )
            log.debug(f"  Widget cleared - no IP provided")
        
        log.debug("updateInformationView END")
        log.debug("=" * 60)


    def updateScriptsView(self, hostIP):
        headers = ['Id', 'Script', 'Port', 'Protocol']
        scripts_data = self.controller.getScriptsFromDB(hostIP)
        self.ScriptsTableModel = ScriptsTableModel(self, scripts_data, headers)
        self.ui.ScriptsTableView.setModel(self.ScriptsTableModel)
        
        for i in [0,3]:  # hide some columns
            self.ui.ScriptsTableView.setColumnHidden(i, True)
        
        scripts = []  # ensure that there is always something selected
        for row in range(self.ScriptsTableModel.rowCount(QtCore.QModelIndex())):
            scripts.append(self.ScriptsTableModel.getScriptDBIdForRow(row))
        
        # the script we previously clicked may not be visible anymore (e.g. due to filters)
        if self.viewState.script_clicked in scripts:
            row = self.ScriptsTableModel.getRowForDBId(self.viewState.script_clicked)
        else:
            row = 0  # or select the first row
        
        if not (row is None):
            self.ui.ScriptsTableView.selectRow(row)
            self.scriptTableClick()
        
        self.ui.ScriptsTableView.repaint()
        self.ui.ScriptsTableView.update()
        
        # Track script count and only highlight if NEW scripts were added
        current_count = len(scripts_data) if scripts_data else 0
        previous_count = self.previous_data_counts.get(f'{hostIP}_scripts', 0)
        
        # Only highlight if we have more scripts than before
        if current_count > previous_count:
            self.highlightTab('Scripts')
        
        # Update the count
        self.previous_data_counts[f'{hostIP}_scripts'] = current_count



    def updateCvesByHostView(self, hostIP):
        headers = ['CVE Id', 'CVSS Score', 'Product', 'Version', 'CVE URL', 'Source', 'ExploitDb ID', 'ExploitDb', 'ExploitDb URL']
        cves = self.controller.getCvesFromDB(hostIP)
        
        # Check if CVE data has changed
        cves_changed = False
        
        # Create a hashable representation of current CVEs for comparison
        current_cve_signature = str([(c.get('name'), c.get('severity'), c.get('product'), c.get('version')) for c in cves]) if cves else ""
        
        # Store previous CVE data per host
        if not hasattr(self, 'previous_cves'):
            self.previous_cves = {}
        
        # Get previous CVE signature for this host
        previous_cve_signature = self.previous_cves.get(hostIP, "")
        
        # Only update if CVEs have changed
        if current_cve_signature != previous_cve_signature:
            cves_changed = True
            self.previous_cves[hostIP] = current_cve_signature
            
            # Update the model
            self.CvesTableModel = CvesTableModel(self, cves, headers)
            self.ui.CvesTableView.horizontalHeader().resizeSection(0,175)
            self.ui.CvesTableView.horizontalHeader().resizeSection(2,175)
            self.ui.CvesTableView.horizontalHeader().resizeSection(4,225)
            self.ui.CvesTableView.setModel(self.CvesTableModel)
            self.ui.CvesTableView.repaint()
            self.ui.CvesTableView.update()
            
            # Only highlight if there are actually CVEs AND data changed
            if cves and len(cves) > 0:
                self.highlightTab('CVEs')





    def updateScriptsOutputView(self, scriptId):
        self.ui.ScriptsOutputTextEdit.clear()
        lines = self.controller.getScriptOutputFromDB(scriptId)
        for line in lines:
            self.ui.ScriptsOutputTextEdit.insertPlainText(line['output'].rstrip())

    # TODO: check if this hack can be improved because we are calling setDirty more than we need
    def updateNotesView(self, hostid):
        self.viewState.lastHostIdClicked = str(hostid)
        note = self.controller.getNoteFromDB(hostid)
        saveddirty = self.viewState.dirty
        
        # Store current content before clearing
        old_content = self.ui.NotesTextEdit.toPlainText()
        
        self.ui.NotesTextEdit.clear()
        
        new_content = ""
        if note:
            if '<' in note.text and '>' in note.text:
                self.ui.NotesTextEdit.setHtml(note.text)
                new_content = self.ui.NotesTextEdit.toPlainText()
            else:
                self.ui.NotesTextEdit.insertPlainText(note.text)
                new_content = note.text
        
        if saveddirty == False:
            self.setDirty(False)
        
        # Only highlight if content actually changed (new content added)
        # Don't highlight when just switching between hosts
        if new_content and new_content.strip() != old_content.strip():
            self.highlightTab('Notes')



    def updateToolHostsTableView(self, toolname):
        headers = ["Progress", "Display", "Elapsed", "Percent Complete", "Pid", "Name", "Tool", "Host", "Port",
                   "Protocol", "Command", "Start time", "End time", "OutputFile", "Output", "Status", "Closed"]
        self.ToolHostsTableModel = ProcessesTableModel(self, self.controller.getHostsForTool(toolname), headers)
        self.ui.ToolHostsTableView.setModel(self.ToolHostsTableModel)

        for i in [0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15]:                         # hide some columns
            self.ui.ToolHostsTableView.setColumnHidden(i, True)
        
        self.ui.ToolHostsTableView.horizontalHeader().resizeSection(7, 150)  # default width for Host column

        ids = []                                                        # ensure that there is always something selected
        for row in range(self.ToolHostsTableModel.rowCount("")):
            ids.append(self.ToolHostsTableModel.getProcessIdForRow(row))

        # the host we previously clicked may not be visible anymore (eg: due to filters)
        if self.viewState.tool_host_clicked in ids:
            row = self.ToolHostsTableModel.getRowForDBId(self.viewState.tool_host_clicked)

        else:
            row = 0  # or select the first row

        if not row == None and self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex()) == 'Tools':
            self.ui.ToolHostsTableView.selectRow(row)
            self.toolHostsClick()

    def updateRightPanel(self, hostIP):
        self.updateServiceTableView(hostIP)
        self.updateScriptsView(hostIP)
        self.updateCvesByHostView(hostIP)
        self.updateInformationView(hostIP)
        self.controller.saveProject(self.viewState.lastHostIdClicked, self.ui.NotesTextEdit.toHtml())

        if hostIP:
            self.updateNotesView(self.HostsTableModel.getHostIdForRow(self.HostsTableModel.getRowForIp(hostIP)))
        else:
            self.updateNotesView('')


        if hostIP:
            self.updateNotesView(self.HostsTableModel.getHostIdForRow(self.HostsTableModel.getRowForIp(hostIP)))
        else:
            self.updateNotesView('')
            
    def displayToolPanel(self, display=False):
        log.debug("========== displayToolPanel START ==========")
        log.debug(f"displayToolPanel - display = {display}")
        
        size = self.ui.splitter.parentWidget().width() - self.leftPanelSize - 24  # note: 24 is a fixed value
        log.debug(f"displayToolPanel - Calculated size = {size}")
        
        if display:
            log.debug("displayToolPanel - Showing tool panel")
            self.ui.ServicesTabWidget.hide()
            self.ui.splitter_3.show()
            self.ui.splitter.setSizes([self.leftPanelSize, 0, size])  # reset hoststableview width
            log.debug(f"displayToolPanel - Set splitter sizes: [{self.leftPanelSize}, 0, {size}]")
            
            if self.viewState.tool_clicked == 'screenshooter':
                log.debug("displayToolPanel - Tool is screenshooter, calling displayScreenshots(True)")
                self.displayScreenshots(True)
            else:
                log.debug("displayToolPanel - Tool is not screenshooter")
                self.displayScreenshots(False)
        else:
            log.debug("displayToolPanel - Hiding tool panel")
            self.ui.splitter_3.hide()
            self.ui.ServicesTabWidget.show()
            self.ui.splitter.setSizes([self.leftPanelSize, size, 0])
            log.debug(f"displayToolPanel - Set splitter sizes: [{self.leftPanelSize}, {size}, 0]")
            
        log.debug("========== displayToolPanel END ==========\n")




    def displayScreenshots(self, display=False):
        size = self.ui.splitter.parentWidget().width() - self.leftPanelSize - 24       # note: 24 is a fixed value

        if display:
            self.ui.DisplayWidget.hide()
            self.ui.ScreenshotWidget.scrollArea.show()
            self.ui.splitter_3.setSizes([275, 0, size - 275])               # reset middle panel width

        else:
            self.ui.ScreenshotWidget.scrollArea.hide()
            self.ui.DisplayWidget.show()
            self.ui.splitter_3.setSizes([275, size - 275, 0])               # reset middle panel width

    def displayAddHostsOverlay(self, display=False):
        if display:
            self.ui.addHostsOverlay.show()
            self.ui.HostsTableView.hide()
        else:
            self.ui.addHostsOverlay.hide()
            self.ui.HostsTableView.show()
            
    #################### BOTTOM PANEL INTERFACE UPDATE FUNCTIONS ####################

    def onProcessStatusFilterChanged(self, _index):
        self.processStatusFilter = self.ui.ProcessStatusFilterComboBox.currentData()
        if self.ProcessesTableModel is None:
            self.setupProcessesTableView()
        else:
            self.updateProcessesTableView()

    def _normalizeProcessRows(self, raw_processes):
        process_columns = [
            "pid", "id", "display", "name", "tabTitle", "hostIp", "port", "protocol", "command",
            "startTime", "endTime", "estimatedRemaining", "elapsed", "outputfile", "status", "closed", "percent"
        ]
        processes = []
        for row in raw_processes:
            if isinstance(row, dict):
                proc = dict(row)
            else:
                try:
                    proc = dict(zip(process_columns, row))
                except Exception:
                    proc = {}
            if "percent" not in proc:
                proc["percent"] = "Unknown"
            if proc.get("elapsed") in (None, ""):
                proc["elapsed"] = 0
            processes.append(proc)
        return processes

    def _getProcessesForDisplay(self):
        raw_processes = self.controller.getProcessesFromDB(
            self.viewState.filters,
            showProcesses=True,
            sort=self.processesTableViewSort,
            ncol=self.processesTableViewSortColumn,
            status_filter=self.processStatusFilter
        )
        return self._normalizeProcessRows(raw_processes)

    def setupProcessesTableView(self):
        headers = ["Progress", "Display", "Run time", "Percent Complete", "Pid", "Name", "Tool", "Host", "Port",
                   "Protocol", "Command", "Start time", "End time", "OutputFile", "Output", "Status", "Closed"]
        processes = self._getProcessesForDisplay()
        self.ProcessesTableModel = ProcessesTableModel(self, processes, headers)
        self.ui.ProcessesTableView.setModel(self.ProcessesTableModel)
        self.ProcessesTableModel.sort(15, Qt.SortOrder.DescendingOrder)
        self._configureProcessesColumns()

    def updateProcessesTableView(self):
        processes = self._getProcessesForDisplay()
        self.ProcessesTableModel.setDataList(processes)
        self._configureProcessesColumns()
        self.ui.ProcessesTableView.repaint()
        self.ui.ProcessesTableView.update()
        # Update animations
        self.updateProcessesIcon()

    def _configureProcessesColumns(self):
        if not self.ProcessesTableModel:
            return
        header = self.ui.ProcessesTableView.horizontalHeader()
        visible_columns = {0, 2, 6, 7, 15}
        total_columns = self.ProcessesTableModel.columnCount(None)
        for col in range(total_columns):
            self.ui.ProcessesTableView.setColumnHidden(col, col not in visible_columns)
        header.resizeSection(0, 125)
        header.resizeSection(2, 110)
        header.resizeSection(6, 260)
        header.resizeSection(7, 260)
        header.resizeSection(15, 110)

    def _initToolTabContextMenu(self):
        tabBar = self.ui.ServicesTabWidget.tabBar()
        tabBar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tabBar.customContextMenuRequested.connect(self._showToolTabContextMenu)

    def _showToolTabContextMenu(self, pos):
        tabBar = self.ui.ServicesTabWidget.tabBar()
        index = tabBar.tabAt(pos)
        if index < 0 or index < getattr(self, 'fixedTabsCount', 0):
            return

        widget = self.ui.ServicesTabWidget.widget(index)
        if widget is None:
            return

        menu = QtWidgets.QMenu(self.ui.ServicesTabWidget)
        saveAction = menu.addAction('Save')
        globalPos = tabBar.mapToGlobal(pos)
        chosen = menu.exec(globalPos)
        if chosen == saveAction:
            self._saveToolTabContent(index, widget)

    def _suggest_filename(self, base_name, extension):
        safe = ''.join(ch if ch.isalnum() or ch in (' ', '_', '-') else '_' for ch in base_name or 'output')
        safe = safe.strip().replace(' ', '_') or 'output'
        if not safe.lower().endswith(f".{extension}"):
            safe += f".{extension}"
        return safe

    def _save_tool_text(self, widget, tab_title):
        text_edit = widget if isinstance(widget, QtWidgets.QTextEdit) else widget.findChild(QtWidgets.QTextEdit)
        if not text_edit:
            log.info(f"No textual content found for tab '{tab_title}'")
            return
        content = text_edit.toPlainText()
        default_path = self._suggest_filename(tab_title, 'txt')
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.ui.centralwidget,
            'Save Tool Output',
            default_path,
            'Text Files (*.txt);;All Files (*)'
        )
        if not filename:
            return
        if not filename.lower().endswith('.txt'):
            filename += '.txt'
        try:
            log.info(f"Saving tool output from tab '{tab_title}' to {filename}")
            with open(filename, 'w', encoding='utf-8') as fh:
                fh.write(content)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self.ui.centralwidget,
                'Save Failed',
                f'Unable to save file:\n{exc}'
            )

    def _save_tool_image(self, widget, tab_title):
        image_viewer = None
        if isinstance(widget, ImageViewer):
            image_viewer = widget
        elif isinstance(widget, QtWidgets.QScrollArea):
            viewer_ref = getattr(widget, '_imageViewerRef', None)
            if isinstance(viewer_ref, ImageViewer):
                image_viewer = viewer_ref
        elif hasattr(widget, 'imageLabel') and isinstance(widget, QtWidgets.QWidget):
            image_viewer = widget

        if image_viewer is None and isinstance(widget, QtWidgets.QWidget):
            parent = widget.parentWidget()
            while parent and image_viewer is None:
                if isinstance(parent, ImageViewer):
                    image_viewer = parent
                    break
                parent = parent.parentWidget()

        if image_viewer is None:
            log.info(f"No screenshot content found for tab '{tab_title}'")
            return

        default_path = self._suggest_filename(tab_title, 'png')
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.ui.centralwidget,
            'Save Screenshot',
            default_path,
            'PNG Images (*.png);;All Files (*)'
        )
        if not filename:
            return
        if not filename.lower().endswith('.png'):
            filename += '.png'

        image_path = getattr(image_viewer, 'currentImagePath', None)
        try:
            if image_path and os.path.isfile(image_path):
                log.info(f"Copying screenshot from {image_path} to {filename}")
                shutil.copyfile(image_path, filename)
                return
            image_label = getattr(image_viewer, 'imageLabel', None)
            pixmap = image_label.pixmap() if image_label else None
            if pixmap:
                log.info(f"Saving screenshot pixmap from tab '{tab_title}' to {filename}")
                pixmap.save(filename, 'PNG')
            else:
                raise IOError('No image data available.')
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self.ui.centralwidget,
                'Save Failed',
                f'Unable to save screenshot:\n{exc}'
            )

    def _saveToolTabContent(self, index, widget):
        tab_title = self.ui.ServicesTabWidget.tabText(index)
        log.info(f"Tool tab save requested: index={index}, title='{tab_title}', widget={type(widget)}")
        if widget.findChild(QtWidgets.QTextEdit):
            self._save_tool_text(widget, tab_title)
            return
        if hasattr(widget, 'imageLabel'):
            self._save_tool_image(widget, tab_title)
            return
        # If widget is directly a QTextEdit or ImageViewer
        if isinstance(widget, QtWidgets.QTextEdit):
            self._save_tool_text(widget, tab_title)
        elif isinstance(widget, ImageViewer):
            self._save_tool_image(widget, tab_title)
        elif isinstance(widget, QtWidgets.QScrollArea):
            self._save_tool_image(widget, tab_title)

    def updateProcessesIcon(self):
        if self.ProcessesTableModel:
            for row in range(len(self.ProcessesTableModel.getProcesses())):
                status = self.ProcessesTableModel.getProcesses()[row]['status']
                
                directStatus = {'Waiting':'waiting', 'Running':'running', 'Finished':'finished', 'Crashed':'killed'}
                defaultStatus = 'killed'

                processIconName = directStatus.get(status) or defaultStatus
                processIcon = './images/{processIconName}.gif'.format(processIconName=processIconName)

                self.runningWidget = ImagePlayer(processIcon)
                self.ui.ProcessesTableView.setIndexWidget(self.ui.ProcessesTableView.model().index(row,0),
                                                          self.runningWidget)

    #################### GLOBAL INTERFACE UPDATE FUNCTION ####################
    
    # TODO: when nmap file is imported select last IP clicked (or first row if none)
    from PyQt6 import QtCore
    @QtCore.pyqtSlot()
    def updateInterface(self):
        self.ui_mainwindow.show()

        if self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex()) == 'Hosts':
            self.updateHostsTableView()
            self.viewState.lazy_update_services = True
            self.viewState.lazy_update_tools = True
            self.viewState.lazy_update_os = True

        elif self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex()) == 'Services':
            self.updateServiceNamesTableView()
            self.viewState.lazy_update_hosts = True
            self.viewState.lazy_update_tools = True
            self.viewState.lazy_update_os = True

        elif self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex()) == 'Tools':
            self.updateToolsTableView()
            self.viewState.lazy_update_hosts = True
            self.viewState.lazy_update_services = True
            self.viewState.lazy_update_os = True

        elif self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex()) == 'OS':
            if self.viewState.lazy_update_os or not self.OsListTableModel:
                self.updateOsListView()
            else:
                self.updateOsHostsTableView(self.viewState.os_clicked or 'Unknown')
            self.viewState.lazy_update_hosts = True
            self.viewState.lazy_update_services = True
            self.viewState.lazy_update_tools = True

        # After initial setup is complete, enable tab highlighting
        self.app_initialized = True
    #################### TOOL TABS ####################

    # this function creates a new tool tab for a given host
    # TODO: refactor/review, especially the restoring part. we should not check if toolname=nmap everywhere in the code
    # ..maybe we should do it here. rethink
    def createNewTabForHost(self, ip, tabTitle, restoring=False, content='', filename=''):
        # TODO: use regex otherwise tools with 'screenshot' in the name are screwed.
        if 'screenshot' in str(tabTitle):
            tempWidget = ImageViewer()
            tempWidget.setObjectName(str(tabTitle))
            tempWidget.open(str(filename))
            tempTextView = tempWidget.scrollArea
            tempTextView.setObjectName(str(tabTitle))
        else:
            tempWidget = QtWidgets.QWidget()
            tempWidget.setObjectName(str(tabTitle))
            
            # Create label for displaying matches
            tempMatches = QtWidgets.QLabel()
            tempMatches.setVisible(True)
            
            tempTextView = QtWidgets.QTextEdit(tempWidget)
            tempTextView.setReadOnly(True)
            if self.controller.getSettings().general_tool_output_black_background == 'True':
                p = tempTextView.palette()
                p.setColor(QtGui.QPalette.ColorRole.Base, Qt.GlobalColor.black)
                p.setColor(QtGui.QPalette.ColorRole.Text, Qt.GlobalColor.white)
                tempTextView.setPalette(p)
                tempTextView.setStyleSheet("QMenu { color:black;}")
            
            # Use VBoxLayout to stack label on top of text view
            tempLayout = QtWidgets.QVBoxLayout(tempWidget)
            tempLayout.addWidget(tempMatches)
            tempLayout.addWidget(tempTextView)
        
            if not content == '':
                tempTextView.setHtml(content)

        # if restoring tabs (after opening a project) don't show the tab in the ui
        if restoring == False:
            self.ui.ServicesTabWidget.addTab(tempWidget, str(tabTitle))
    
        hosttabs = []
        if str(ip) in self.viewState.hostTabs:
            hosttabs = self.viewState.hostTabs[str(ip)]
        
        if 'screenshot' in str(tabTitle):
            hosttabs.append(tempWidget.scrollArea)
        else:
            hosttabs.append(tempWidget)
        
        self.viewState.hostTabs.update({str(ip):hosttabs})

        return tempTextView


    def createNewConsole(self, tabTitle, content='Hello\n', filename=''):

        tempWidget = QtWidgets.QWidget()
        tempWidget.setObjectName(str(tabTitle))
        tempTextView = QtWidgets.QTextEdit(tempWidget)
        tempTextView.setReadOnly(True)
        if self.controller.getSettings().general_tool_output_black_background == 'True':
            p = tempTextView.palette()
            p.setColor(QtGui.QPalette.ColorRole.Base, Qt.GlobalColor.black)               # black background
            p.setColor(QtGui.QPalette.ColorRole.Text, Qt.GlobalColor.white)               # white font
            tempTextView.setPalette(p)
            # font-size:18px; width: 150px; color:red; left: 20px;}"); # set the menu font color: black
            tempTextView.setStyleSheet("QMenu { color:black;}")
        tempLayout = QtWidgets.QHBoxLayout(tempWidget)
        tempLayout.addWidget(tempTextView)
        self.ui.PythonTabLayout.addWidget(tempWidget)

        if not content == '':                                       # if there is any content to display
            tempTextView.appendPlainText(content)


        return tempTextView

    def closeHostToolTab(self, index):
        self._closeProcessTab(
            tabWidget=self.ui.ServicesTabWidget,
            index=index,
            getStatusFunc=self.controller.getProcessStatusForDBId,
            getPidFunc=self.controller.getPidForProcess,
            killFunc=self.controller.killProcess,
            cancelFunc=self.controller.cancelProcess,
            storeCloseFunc=self.controller.storeCloseTabStatusInDB,
            hostTabsDict=self.viewState.hostTabs,
            isBruteTab=False
        )

    def _closeProcessTab(self, tabWidget, index, getStatusFunc, getPidFunc, killFunc, cancelFunc, storeCloseFunc, hostTabsDict, isBruteTab):
        """
        Helper to close a process tab (host tool or brute tab) with shared logic.
        """
        currentTabIndex = tabWidget.currentIndex()
        tabWidget.setCurrentIndex(index)
        currentWidget = tabWidget.currentWidget()

        # Get dbId depending on tab type
        if not isBruteTab and 'screenshot' in str(currentWidget.objectName()):
            dbId_prop = currentWidget.property('dbId')
            dbId = int(dbId_prop) if dbId_prop is not None else None
        elif not isBruteTab:
            text_widget = currentWidget.findChild(QtWidgets.QTextEdit)
            dbId_prop = text_widget.property('dbId') if text_widget else None
            dbId = int(dbId_prop) if dbId_prop is not None else None
        else:
            dbId_prop = getattr(currentWidget.display, 'property', lambda x: None)('dbId')
            dbId = int(dbId_prop) if dbId_prop not in (None, '') else None

        if dbId is None:
            log.warning("No dbId found for tab being closed; skipping DB status update.")
            tabWidget.removeTab(index)
            return

        pid = getPidFunc(dbId)

        status = str(getStatusFunc(dbId))
        if status == 'Running':
            message = "This process is still running. Are you sure you want to kill it?"
            reply = self.yesNoDialog(message, 'Confirm')
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                killFunc(pid, dbId)
            else:
                return

        if status == 'Waiting':
            message = "This process is waiting to start. Are you sure you want to cancel it?"
            reply = self.yesNoDialog(message, 'Confirm')
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                cancelFunc(dbId)
            else:
                return

        # Remove tab from hostTabs
        for ip in list(hostTabsDict.keys()):
            if currentWidget in hostTabsDict[ip]:
                hostTabsDict[ip].remove(currentWidget)
                hostTabsDict.update({ip: hostTabsDict[ip]})
                break

        storeCloseFunc(dbId)
        tabWidget.removeTab(index)

        if currentTabIndex >= tabWidget.currentIndex():
            tabWidget.setCurrentIndex(currentTabIndex - 1)
        else:
            tabWidget.setCurrentIndex(currentTabIndex)

        # For brute tabs, add default tab if none remain
        if isBruteTab and tabWidget.count() == 0:
            self.createNewBruteTab('127.0.0.1', '22', 'ssh')

    # this function removes tabs that were created when running tools (starting from the end to avoid index problems)
    def removeToolTabs(self, position=-1):
        log.debug("========== removeToolTabs START ==========")
        log.debug(f"removeToolTabs - position = {position}")
        log.debug(f"removeToolTabs - fixedTabsCount = {self.fixedTabsCount}")
        log.debug(f"removeToolTabs - ServicesTabWidget count BEFORE = {self.ui.ServicesTabWidget.count()}")
        
        if position == -1:
            position = self.fixedTabsCount - 1
            
        log.debug(f"removeToolTabs - Adjusted position = {position}")
        log.debug(f"removeToolTabs - Will remove tabs from index {self.ui.ServicesTabWidget.count() - 1} down to {position + 1}")
        
        for i in range(self.ui.ServicesTabWidget.count() - 1, position, -1):
            tabName = self.ui.ServicesTabWidget.tabText(i)
            log.debug(f"removeToolTabs - Removing tab at index {i}: '{tabName}'")
            self.ui.ServicesTabWidget.removeTab(i)
            
        log.debug(f"removeToolTabs - ServicesTabWidget count AFTER = {self.ui.ServicesTabWidget.count()}")
        log.debug("========== removeToolTabs END ==========\n")





    # this function restores the tool tabs based on the DB content (should be called when opening an existing project).
    def restoreToolTabs(self):
        # false means we are fetching processes with display flag=False, which is the case for every process once
        # a project is closed.
        tools = self.controller.getProcessesForRestore()
        nbr = len(tools)  # show a progress bar because this could take long
        if nbr==0:
            nbr=1
        progress = 100.0 / nbr
        totalprogress = 0
        self.tick.emit(int(totalprogress))
        def _get_process_field(process_info, key, default_value=''):
            if isinstance(process_info, dict):
                return process_info.get(key, default_value)
            return getattr(process_info, key, default_value)
        for t in tools:
            tab_title = _get_process_field(t, 'tabTitle', '')
            if tab_title != '':
                host_ip = _get_process_field(t, 'hostIp', '')
                output_file = _get_process_field(t, 'outputfile', '')
                output_content = _get_process_field(t, 'output', '')
                process_id = _get_process_field(t, 'id', '')
                if 'screenshot' in str(tab_title):
                    imageviewer = self.createNewTabForHost(
                        host_ip, tab_title, True, '',
                        str(self.controller.getOutputFolder())+'/screenshots/'+str(output_file))
                    imageviewer.setObjectName(str(tab_title))
                    imageviewer.setProperty('dbId', str(process_id))
                else:
                    # True means we are restoring tabs. Set the widget's object name to the DB id of the process
                    tab_widget = self.createNewTabForHost(host_ip, tab_title, True, output_content)
                    tab_widget.setProperty('dbId', str(process_id))

            totalprogress += progress                                   # update the progress bar
            self.tick.emit(int(totalprogress))
        
    def restoreToolTabsForHost(self, ip):
        log.debug("========== restoreToolTabsForHost START ==========")
        log.debug(f"restoreToolTabsForHost - ip = {ip}")
        
        settings = self.controller.getSettings()
        if not hasattr(self, 'viewState') or not hasattr(self.viewState, 'hostTabs'):
            log.debug("restoreToolTabsForHost - No viewState or hostTabs, returning")
            return
            
        if self.viewState.hostTabs and ip in self.viewState.hostTabs:
            tabs = self.viewState.hostTabs[ip]
            log.debug(f"restoreToolTabsForHost - Found {len(tabs)} tabs for host {ip}")
            
            matchedTabs = []
            nonMatchedTabs = []
            
            for tab in tabs:
                tabName = tab.objectName()
                matches = tab.property('matches')
                matched = False
                tabIndex = self.ui.ServicesTabWidget.indexOf(tab)
                
                log.debug(f"Checking tab '{tabName}', matches property = {matches}")
                
                if matches:
                    matched = True
                    matchText = 'Matches:' + str(matches).strip()
                    label = tab.findChild(QtWidgets.QLabel)
                    log.debug(f"Found matches! Label found = {label is not None}")
                    
                    if label:
                        log.debug(f"Setting label text to '{matchText}'")
                        label.setText(matchText)
                        label.setVisible(True)
                        label.setStyleSheet("color: black; background-color: yellow; font-weight: bold;")
                    else:
                        log.debug(f"ERROR - Label not found in tab '{tabName}'")
                        
                if 'hydra' in tabName or 'nmap' in tabName:
                    continue
                    
                if matched:
                    matchedTabs.append(tab)
                else:
                    nonMatchedTabs.append(tab)
                    
            log.debug(f"restoreToolTabsForHost - matchedTabs count = {len(matchedTabs)}")
            log.debug(f"restoreToolTabsForHost - nonMatchedTabs count = {len(nonMatchedTabs)}")
            log.debug(f"restoreToolTabsForHost - ServicesTabWidget count BEFORE adding tabs = {self.ui.ServicesTabWidget.count()}")
            
            for tab in matchedTabs:
                tabindex = self.ui.ServicesTabWidget.addTab(tab, tab.objectName())
                log.debug(f"restoreToolTabsForHost - Added matched tab '{tab.objectName()}' at index {tabindex}")
                self.ui.ServicesTabWidget.tabBar().setTabTextColor(tabindex, QtGui.QColor('red'))
                
            for tab in nonMatchedTabs:
                tabindex = self.ui.ServicesTabWidget.addTab(tab, tab.objectName())
                log.debug(f"restoreToolTabsForHost - Added non-matched tab '{tab.objectName()}' at index {tabindex}")
                
            log.debug(f"restoreToolTabsForHost - ServicesTabWidget count AFTER adding tabs = {self.ui.ServicesTabWidget.count()}")
            # After all tabs are restored, preserve the colors on fixed tabs
            self.preserveFixedTabColors()
            log.debug("restoreToolTabsForHost - preserveFixedTabColors() completed")
        else:
            log.debug(f"restoreToolTabsForHost - No tabs found for host {ip}")
            
        log.debug("========== restoreToolTabsForHost END ==========\n")





    # this function restores the textview widget (now in the tools display widget) to its original tool tab
    # (under the correct host)
    def restoreToolTabWidget(self, clear=False):
        log.debug("========== restoreToolTabWidget START ==========")
        log.debug(f"restoreToolTabWidget - clear = {clear}")
        log.debug("restoreToolTabWidget - Checking for QTextEdit in DisplayWidget")
        
        if self.ui.DisplayWidget.findChild(QtWidgets.QTextEdit) == self.ui.toolOutputTextView:
            log.debug("restoreToolTabWidget - toolOutputTextView already in DisplayWidget, returning early")
            return
            
        log.debug("restoreToolTabWidget - Looking through hostTabs to restore QTextEdit")
        for host in self.viewState.hostTabs.keys():
            hosttabs = self.viewState.hostTabs[host]
            log.debug(f"restoreToolTabWidget - Checking host {host}, has {len(hosttabs)} tabs")
            
            for tab in hosttabs:
                tabName = str(tab.objectName())
                log.debug(f"restoreToolTabWidget - Checking tab '{tabName}'")
                
                if 'screenshot' not in str(tab.objectName()) and not tab.findChild(QtWidgets.QTextEdit):
                    log.debug(f"restoreToolTabWidget - Found tab without QTextEdit: '{tabName}'")
                    log.debug("restoreToolTabWidget - Adding DisplayWidget's QTextEdit to this tab")
                    tab.layout().addWidget(self.ui.DisplayWidget.findChild(QtWidgets.QTextEdit))
                    break
                    
        if clear:
            log.debug("restoreToolTabWidget - clear=True, clearing toolOutputTextView")
            if self.ui.DisplayWidget.findChild(QtWidgets.QTextEdit):
                self.ui.DisplayWidget.findChild(QtWidgets.QTextEdit).setParent(None)
            self.ui.DisplayWidgetLayout.addWidget(self.ui.toolOutputTextView)
            
        log.debug("========== restoreToolTabWidget END ==========\n")




    #################### BRUTE TABS ####################
    
    def createNewBruteTab(self, ip, port, service):
        self.ui.statusbar.showMessage('Sending to Brute: '+str(ip)+':'+str(port)+' ('+str(service)+')', msecs=1000)
        bWidget = BruteWidget(ip, port, service, self.controller.getSettings())
        bWidget.runButton.clicked.connect(lambda: self.callHydra(bWidget))
        self.ui.BruteTabWidget.addTab(bWidget, str(self.viewState.bruteTabCount))
        self.viewState.bruteTabCount += 1                                                     # update tab count
        # show the last added tab in the brute widget
        self.ui.BruteTabWidget.setCurrentIndex(self.ui.BruteTabWidget.count()-1)

    def closeBruteTab(self, index):
        self._closeProcessTab(
            tabWidget=self.ui.BruteTabWidget,
            index=index,
            getStatusFunc=lambda dbId: self.ProcessesTableModel.getProcessStatusForPid(self.ui.BruteTabWidget.currentWidget().pid),
            getPidFunc=lambda dbId: self.ui.BruteTabWidget.currentWidget().pid,
            killFunc=lambda pid, dbId: self.killBruteProcess(self.ui.BruteTabWidget.currentWidget()),
            cancelFunc=lambda dbId: self.killBruteProcess(self.ui.BruteTabWidget.currentWidget()),
            storeCloseFunc=lambda dbId: self.controller.storeCloseTabStatusInDB(int(self.ui.BruteTabWidget.currentWidget().display.property('dbId'))),
            hostTabsDict=self.viewState.hostTabs,
            isBruteTab=True
        )

    def resetBruteTabs(self):
        count = self.ui.BruteTabWidget.count()
        for i in range(0, count):
            self.ui.BruteTabWidget.removeTab(count -i -1)
        self.createNewBruteTab('127.0.0.1', '22', 'ssh')

    # TODO: show udp in tabTitle when udp service
    def callHydra(self, bWidget):
        if validateNmapInput(bWidget.ipTextinput.text()) and validateNmapInput(bWidget.portTextinput.text()):
                                                                        # check if host is already in scope
            if not self.controller.isHostInDB(bWidget.ipTextinput.text()):
                message = "This host is not in scope. Add it to scope and continue?"
                reply = self.yesNoDialog(message, 'Confirm')
                if reply == QtWidgets.QMessageBox.StandardButton.No:
                    return
                else:
                    log.info('Adding host to scope here!!')
                    self.controller.addHosts(
                        targetHosts=str(bWidget.ipTextinput.text()).replace(';', ' '),
                        runHostDiscovery=False,
                        runStagedNmap=False,
                        nmapSpeed="unset",
                        scanMode="unset",
                        nmapOptions=[],
                        enableIPv6=False
                    )
            
            bWidget.validationLabel.hide()
            bWidget.toggleRunButton()
            bWidget.resetDisplay()                                      # fixes tab bug
            
            hydraCommand = bWidget.buildHydraCommand(self.controller.getRunningFolder(),
                                                     self.controller.getUserlistPath(),
                                                     self.controller.getPasslistPath())
            bWidget.setObjectName(str("hydra"+" ("+bWidget.getPort()+"/tcp)"))
            
            hosttabs = []  # add widget to host tabs (needed to be able to move the widget between brute/tools tabs)
            if str(bWidget.ip) in self.viewState.hostTabs:
                hosttabs = self.viewState.hostTabs[str(bWidget.ip)]
                
            hosttabs.append(bWidget)
            self.viewState.hostTabs.update({str(bWidget.ip):hosttabs})
            
            bWidget.pid = self.controller.runCommand("hydra", bWidget.objectName(), bWidget.ip, bWidget.getPort(),
                                                     'tcp', unicode(hydraCommand), getTimestamp(human=True),
                                                     bWidget.outputfile, bWidget.display)
            bWidget.runButton.clicked.disconnect()
            bWidget.runButton.clicked.connect(lambda: self.killBruteProcess(bWidget))
            
        else:
            bWidget.validationLabel.show()
        
    def killBruteProcess(self, bWidget):
        dbId = str(bWidget.display.property('dbId'))
        status = self.controller.getProcessStatusForDBId(dbId)
        if status == "Running":                                         # check if we need to kill or cancel
            self.controller.killProcess(self.controller.getPidForProcess(dbId), dbId)
            
        elif status == "Waiting":
            self.controller.cancelProcess(dbId)
        self.bruteProcessFinished(bWidget)
        
    def bruteProcessFinished(self, bWidget):
        bWidget.toggleRunButton()
        bWidget.pid = -1
        
        # disassociate textview from bWidget (create new textview for bWidget) and replace it with a new host tab
        self.createNewTabForHost(
            str(bWidget.ip), str(bWidget.objectName()), restoring=True,
            content=unicode(bWidget.display.toPlainText())).setProperty('dbId', str(bWidget.display.property('dbId')))
        
        hosttabs = []  # go through host tabs and find the correct bWidget
        if str(bWidget.ip) in self.viewState.hostTabs:
            hosttabs = self.viewState.hostTabs[str(bWidget.ip)]

        if hosttabs.count(bWidget) > 1:
            hosttabs.remove(bWidget)
        
        self.viewState.hostTabs.update({str(bWidget.ip):hosttabs})

        bWidget.runButton.clicked.disconnect()
        bWidget.runButton.clicked.connect(lambda: self.callHydra(bWidget))

    def findFinishedBruteTab(self, pid):
        for i in range(0, self.ui.BruteTabWidget.count()):
            if str(self.ui.BruteTabWidget.widget(i)) == pid:
                self.bruteProcessFinished(self.ui.BruteTabWidget.widget(i))
                return

    def findFinishedServiceTab(self, pid):
        for i in range(0, self.ui.ServicesTabWidget.count()):
            if str(self.ui.ServicesTabWidget.widget(i)) == pid:
                self.bruteProcessFinished(self.ui.BruteTabWidget.widget(i))
                log.info("Close Tab: {0}".format(str(i)))
                return

    def blinkBruteTab(self, bWidget):
        self.ui.MainTabWidget.tabBar().setTabTextColor(1, QtGui.QColor('red'))
        for i in range(0, self.ui.BruteTabWidget.count()):
            if self.ui.BruteTabWidget.widget(i) == bWidget:
                self.ui.BruteTabWidget.tabBar().setTabTextColor(i, QtGui.QColor('red'))
                return
    def _dedupeTools(self, processes):
        deduped = OrderedDict()
        for proc in processes:
            if isinstance(proc, Mapping):
                name = proc.get('name')
            else:
                name = getattr(proc, 'name', None)
            if not name:
                continue
            if name not in deduped:
                deduped[name] = dict(proc) if isinstance(proc, Mapping) else proc
        if deduped:
            return list(deduped.values())
        return list(processes)

    def cleanupBeforeExit(self):
        """
        Comprehensive cleanup before Qt application exit.
        This MUST be called via QApplication.aboutToQuit signal.
        Prevents segmentation faults by cleaning up in proper order.
        """
        log.info('!!! CLEANUPBEFOREEXIT WAS CALLED !!!')  # THIS LINE FIRST
        log.info('=== CLEANUP BEFORE EXIT STARTED ===')
        
        # === DIAGNOSTIC CODE ===
        import threading
        import sys
        import os
        import gc
        import traceback
        
        log.info("=== EXIT DIAGNOSTIC START ===")
        log.info(f"Active threads: {threading.active_count()}")
        for t in threading.enumerate():
            log.info(f"  Thread: {t.name}, daemon={t.daemon}, alive={t.is_alive()}")
        
        # Force exit with timeout watchdog - INCREASED TO 15 SECONDS FOR MORE DEBUG TIME
        def force_exit():
            import time
            time.sleep(15)
            log.error("!!! HUNG - FORCING EXIT AFTER 15 SECONDS !!!")
            log.error("=== DUMPING STACK TRACES ===")
            for thread_id, frame in sys._current_frames().items():
                log.error(f"\nThread {thread_id}:")
                log.error(''.join(traceback.format_stack(frame)))
            log.error("=== END STACK TRACES ===")
            os._exit(0)
        
        watchdog = threading.Thread(target=force_exit, daemon=True)
        watchdog.start()
        log.info("Started 15-second watchdog timer")
        # === END DIAGNOSTIC CODE ===
        
        try:
            # STEP 1: Stop all timers first
            log.info('Step 1: Stopping all QTimer objects...')
            timers_stopped = 0
            for attr_name in dir(self):
                try:
                    attr = getattr(self, attr_name)
                    if isinstance(attr, QtCore.QTimer):
                        if attr.isActive():
                            log.info(f'  Stopping timer: {attr_name}')
                            attr.stop()
                            try:
                                attr.disconnect()
                            except:
                                pass
                            timers_stopped += 1
                except (RuntimeError, AttributeError) as e:
                    log.warning(f'  Timer cleanup warning for {attr_name}: {e}')
            log.info(f'  Stopped {timers_stopped} timers')
            log.info('Step 1: COMPLETE')
            
            # STEP 2: Kill remaining processes
            log.info('Step 2: Cleaning up processes...')
            if hasattr(self, 'controller') and self.controller:
                running = self.controller.getRunningProcesses()
                if running:
                    log.info(f'  Found {len(running)} running processes')
                    self.controller.killRunningProcesses()
                else:
                    log.info('  No running processes to clean')
                
                log.info('  Waiting for process cleanup to complete...')
                QtWidgets.QApplication.processEvents()
                import time
                time.sleep(0.2)
                log.info('  Process cleanup wait completed')
            log.info('Step 2: COMPLETE')
            
            # STEP 3: Save settings with EXTENSIVE debugging
            log.info('Step 3: Saving settings...')
            if hasattr(self, 'controller') and self.controller:
                try:
                    log.info('  [3A] About to call saveSettings()...')
                    log.info(f'  [3A] Thread count before: {threading.active_count()}')
                    
                    self.controller.saveSettings()
                    
                    log.info('  [3B] saveSettings() RETURNED successfully')
                    log.info(f'  [3B] Thread count after: {threading.active_count()}')
                    
                    log.info('  [3C] Threads after saveSettings:')
                    for t in threading.enumerate():
                        log.info(f'    - {t.name}, daemon={t.daemon}')
                    
                    log.info('  [3D] Processing events after saveSettings...')
                    QtWidgets.QApplication.processEvents()
                    log.info('  [3E] Events processed')
                    
                except Exception as e:
                    log.error(f'  [3ERROR] saveSettings() exception: {e}')
                    log.error(f'  [3ERROR] Traceback: {traceback.format_exc()}')
            log.info('Step 3: COMPLETE')
            
            # STEP 3.5: Delete QSettings object
            log.info('Step 3.5: Cleaning up QSettings...')
            if hasattr(self, 'controller') and self.controller:
                if hasattr(self.controller, 'settingsFile'):
                    try:
                        log.info('  [3.5A] Found settingsFile')
                        if hasattr(self.controller.settingsFile, 'actions'):
                            log.info('  [3.5B] Syncing QSettings...')
                            self.controller.settingsFile.actions.sync()
                            log.info('  [3.5C] QSettings synced')
                            
                            log.info('  [3.5D] Deleting QSettings.actions...')
                            del self.controller.settingsFile.actions
                            log.info('  [3.5E] QSettings.actions deleted')
                        
                        log.info('  [3.5F] Deleting settingsFile...')
                        del self.controller.settingsFile
                        log.info('  [3.5G] settingsFile deleted')
                    except Exception as e:
                        log.error(f'  [3.5ERROR] QSettings cleanup error: {e}')
                        log.error(f'  [3.5ERROR] Traceback: {traceback.format_exc()}')
            log.info('Step 3.5: COMPLETE')
            
            # STEP 4: Force garbage collection
            log.info('Step 4: Running garbage collection...')
            collected1 = gc.collect()
            log.info(f'  First pass collected: {collected1} objects')
            collected2 = gc.collect()
            log.info(f'  Second pass collected: {collected2} objects')
            log.info('Step 4: COMPLETE')
            
            # STEP 5: Process pending events
            log.info('Step 5: Processing pending Qt events...')
            QtWidgets.QApplication.processEvents()
            QtCore.QCoreApplication.processEvents()
            log.info('Step 5: COMPLETE')
            
            log.info('=== CLEANUP BEFORE EXIT COMPLETED SUCCESSFULLY ===')
            log.info(f"Final thread count: {threading.active_count()}")
            log.info("Final threads:")
            for t in threading.enumerate():
                log.info(f"  - {t.name}, daemon={t.daemon}")
            log.info("About to exit normally")
            
        except Exception as e:
            log.error(f'EXCEPTION during cleanupBeforeExit: {type(e).__name__}: {e}')
            log.error(f'Traceback:\n{traceback.format_exc()}')
            log.error('Forcing exit due to exception')
            os._exit(1)

    
    def closeEvent(self, event):
        """
        Handle window close event (X button clicked).
        Uses flag to prevent double confirmation dialog.
        """
        log.info('=== closeEvent triggered ===')
        
        # Prevent double close confirmation (Qt bug on some platforms)
        if self._closing:
            log.info('closeEvent: Already closing, accepting immediately')
            event.accept()
            return
        
        # Check if we can proceed with closing
        if self.dealWithCurrentProject(exiting=True):
            log.info('closeEvent: User confirmed exit, setting closing flag')
            self._closing = True
            event.accept()
            # Cleanup will be handled by aboutToQuit signal
        else:
            log.info('closeEvent: User canceled exit, ignoring event')
            event.ignore()

    def updateTabHighlight(self, hostIp, tabTitle):
        if not hasattr(self, 'viewState') or not hasattr(self.viewState, 'hostTabs'):
            return
            
        tabs = self.viewState.hostTabs.get(hostIp, [])
        
        for tab in tabs:
            if tab.objectName() == tabTitle:
                tabIndex = self.ui.ServicesTabWidget.indexOf(tab)
                if tabIndex == -1:
                    return
                
                tabBar = self.ui.ServicesTabWidget.tabBar()
                matches = tab.property('matches')
                
                #print(f"DEBUG updateTabHighlight: tab={tabTitle}, matches={matches}")
                
                if matches:
                    # Update tab styling
                    tabBar.setStyleSheet(
                        f"QTabBar::tab:nth-child({tabIndex + 1}) {{"
                        "   color: red;"
                        "   background-color: yellow;"
                        "   font-weight: bold;"
                        "}"
                        f"QTabBar::tab:selected:nth-child({tabIndex + 1}) {{"
                        "   color: red;"
                        "   background-color: yellow;"
                        "   font-weight: bold;"
                        "}"
                    )
                    tabBar.setTabTextColor(tabIndex, QColor('red'))
                    
                    # Update the label with match text
                    matchText = 'Matches: ' + str(matches)
                    label = tab.findChild(QtWidgets.QLabel)
                    
                    #print(f"DEBUG updateTabHighlight: Looking for label in tab, found: {label is not None}")
                    
                    if label:
                        #print(f"DEBUG updateTabHighlight: Setting label text to: {matchText}")
                        label.setText(matchText)
                        label.setVisible(True)
                        label.setStyleSheet("color: black; background-color: yellow; font-weight: bold;")
                    #else:
                        #print(f"DEBUG updateTabHighlight: No label found, tab children: {[child.__class__.__name__ for child in tab.children()]}")
                else:
                    tabBar.setStyleSheet('')
                    tabBar.setTabTextColor(tabIndex, QColor('black'))
                
                # Force the ToolsTableView to repaint so tool names update color
                if hasattr(self, 'ToolsTableModel'):
                    self.ToolsTableModel.layoutChanged.emit()
                if hasattr(self, 'ui') and hasattr(self.ui, 'ToolsTableView'):
                    self.ui.ToolsTableView.viewport().update()
                  
                return
            
    def sendSelectionToNotes(self):
        textEdit = None
        title = ""
        
        # Check if we're in the Scripts tab
        selectedTab = self.ui.ServicesTabWidget.tabText(self.ui.ServicesTabWidget.currentIndex())
        if selectedTab == 'Scripts':
            cursor = self.ui.ScriptsOutputTextEdit.textCursor()
            if cursor.hasSelection():
                textEdit = self.ui.ScriptsOutputTextEdit
                # Get the script name and port from the currently selected row
                if self.ui.ScriptsTableView.selectionModel().selectedRows():
                    row = self.ui.ScriptsTableView.selectionModel().selectedRows()[0].row()
                    # Get script name from column 1 (headers are: Id, Script, Port, Protocol)
                    scriptNameIndex = self.ScriptsTableModel.index(row, 1)
                    scriptName = self.ScriptsTableModel.data(scriptNameIndex, Qt.ItemDataRole.DisplayRole)
                    # Get port from column 2
                    portIndex = self.ScriptsTableModel.index(row, 2)
                    port = self.ScriptsTableModel.data(portIndex, Qt.ItemDataRole.DisplayRole)
                    # Build title with port if present
                    if port:
                        title = f"Scripts - {scriptName} (Port {port})"
                    else:
                        title = f"Scripts - {scriptName}"
                else:
                    title = "Scripts Output"
        
        # First, check if we're in the DisplayWidget (tool output view)
        if not textEdit:
            displayTextEdit = self.ui.DisplayWidget.findChild(QtWidgets.QTextEdit)
            if displayTextEdit and displayTextEdit.textCursor().hasSelection():
                textEdit = displayTextEdit
                # Try to get a meaningful title from the tool host clicked
                if self.viewState.tool_host_clicked:
                    title = f"Tool Output (Process {self.viewState.tool_host_clicked})"
                else:
                    title = "Tool Output"
        
        # If not in DisplayWidget, check the standard tab location
        if not textEdit:
            selectedTab = self.ui.HostsTabWidget.tabText(self.ui.HostsTabWidget.currentIndex())
            if not selectedTab == 'Hosts':
                return
            currentIndex = self.ui.ServicesTabWidget.currentIndex()
            if currentIndex <= 3:
                return
            widget = self.ui.ServicesTabWidget.widget(currentIndex)
            textEdit = widget.findChild(QtWidgets.QTextEdit)
            if not textEdit:
                return
            title = self.ui.ServicesTabWidget.tabText(currentIndex)
        
        cursor = textEdit.textCursor()
        if not cursor.hasSelection():
            return
        
        # Flash effect - save original stylesheet
        originalStyle = textEdit.styleSheet()
        # Set orange background
        textEdit.setStyleSheet("QTextEdit { background-color: rgba(255, 165, 0, 180); }")
        # Create timer to restore original background after 200ms
        QtCore.QTimer.singleShot(200, lambda: textEdit.setStyleSheet(originalStyle))
        
        # Get selection boundaries
        selectionStart = cursor.selectionStart()
        selectionEnd = cursor.selectionEnd()
        
        # Create a temporary document with the selection
        tempDocument = QtGui.QTextDocument()
        tempCursor = QtGui.QTextCursor(tempDocument)
        # Copy the selected fragment to temp document
        tempCursor.insertFragment(cursor.selection())
        
        # Apply QSyntaxHighlighter formats from original document to temp document
        startBlock = textEdit.document().findBlock(selectionStart)
        endBlock = textEdit.document().findBlock(selectionEnd)
        endBlock = endBlock.next()
        endOfTempDocument = tempDocument.characterCount() - 1
        currentBlock = startBlock
        
        while currentBlock.isValid() and currentBlock != endBlock:
            layout = currentBlock.layout()
            if layout:
                # Get the additional formats applied by QSyntaxHighlighter
                additionalFormats = layout.formats()
                for formatRange in additionalFormats:
                    # Calculate position in temp document
                    start = currentBlock.position() + formatRange.start - selectionStart
                    end = start + formatRange.length
                    # Skip if outside temp document bounds
                    if end <= 0 or start >= endOfTempDocument:
                        continue
                    # Clamp to document bounds
                    start = max(start, 0)
                    end = min(end, endOfTempDocument)
                    # Apply the format to temp document
                    tempCursor.setPosition(start)
                    tempCursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
                    tempCursor.mergeCharFormat(formatRange.format)
            currentBlock = currentBlock.next()
        
        # Get the HTML with all formatting preserved
        tempCursor.select(QtGui.QTextCursor.SelectionType.Document)
        htmlWithHighlighting = tempCursor.selection().toHtml()
        
        # Insert into notes with orange header
        notesCursor = self.ui.NotesTextEdit.textCursor()
        notesCursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        
        # Create format for orange background with black text
        headerFormat = QtGui.QTextCharFormat()
        headerFormat.setBackground(QtGui.QColor(255, 165, 0)) # Orange
        headerFormat.setForeground(QtGui.QColor(0, 0, 0)) # Black
        
        # Insert the header with formatting
        notesCursor.insertText("=== Selection from {} ===\n".format(title), headerFormat)
        
        # Insert the highlighted content
        notesCursor.insertHtml(htmlWithHighlighting)
        
        # IMPORTANT: Clear the character format to prevent bleeding
        notesCursor.setCharFormat(QtGui.QTextCharFormat())
        
        # Insert spacing with cleared format
        notesCursor.insertText('\n\n')
        
        self.ui.NotesTextEdit.setTextCursor(notesCursor)
        self.highlightTab('Notes')

    def clearAllTabHighlights(self):
        """Clear all orange tab highlights (reset all tabs to default color)."""
        log.info("=== clearAllTabHighlights START ===")
        log.info(f"unread_tabs BEFORE: {self.unread_tabs}")
        
        # Reset all unread tab states
        for tabname in list(self.unread_tabs.keys()):
            self.unread_tabs[tabname] = False
            log.info(f"  - Set {tabname} unread state to False")
        
        # Reset all tab colors to default
        tabwidget = self.ui.ServicesTabWidget
        tabbar = tabwidget.tabBar()
        defaultcolor = self.app.palette().color(QtGui.QPalette.ColorRole.WindowText)
        
        fixedtabs = ['Services', 'Scripts', 'Information', 'CVEs', 'Notes']
        for i in range(min(len(fixedtabs), tabwidget.count())):
            tabname = tabwidget.tabText(i)
            if tabname in fixedtabs:
                tabbar.setTabTextColor(i, defaultcolor)
                log.info(f"  - Reset tab '{tabname}' at index {i} to default color")
        
        log.info(f"unread_tabs AFTER: {self.unread_tabs}")
        log.info("=== clearAllTabHighlights END ===")






