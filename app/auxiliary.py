#!/usr/bin/env python

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

import os, sys, socket, locale, webbrowser, \
    re, platform  # for webrequests, screenshot timeouts, timestamps, browser stuff and regex
import tempfile
import shlex
from six import u as unicode
import ipaddress
import subprocess

from app.httputil.isHttps import isHttps
from app.logging.legionLog import getAppLogger
from app.timing import timing

# Qt imports — optional. Only needed for Qt GUI mode (MyQProcess, BrowserOpener).
# Flask --web mode uses Filters, checkHydraResults, sortArrayWithArray etc. which have no Qt dependency.
try:
    from PyQt6 import QtCore, QtWidgets
    from PyQt6.QtCore import QProcess, QObject, pyqtSignal, pyqtSlot, QThread, Qt
    from PyQt6.QtWidgets import QAbstractItemView
    from PyQt6.QtGui import QTextDocument, QTextCursor
    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False
    # Provide stubs so module-level code that references these doesn't crash
    class _Stub:
        def __getattr__(self, name): return _Stub()
        def __call__(self, *a, **k): return _Stub()
    QtCore = QtWidgets = QProcess = QObject = QThread = Qt = _Stub()
    QAbstractItemView = QTextDocument = QTextCursor = _Stub()
    def pyqtSignal(*a, **k): return None
    def pyqtSlot(*a, **k):
        def decorator(fn): return fn
        return decorator
    QObject = object

#for matching
try:
    from ansi2html import Ansi2HTMLConverter
except ImportError:
    Ansi2HTMLConverter = None


log = getAppLogger()

# Convert Windows path to Posix
def winPath2Unix(windowsPath):
    windowsPath = windowsPath.replace("\\", "/")
    windowsPath = windowsPath.replace("C:", "/mnt/c")
    return windowsPath

# Convert Posix path to Windows
def unixPath2Win(posixPath):
    posixPath = posixPath.replace("/", "\\")
    posixPath = posixPath.replace("\\mnt\\c", "C:")
    return posixPath

# Check if running in WSL
def isWsl():
    release = str(platform.uname().release).lower()
    return "microsoft" in release

# Check if running in Kali
def isKali():
    release = subprocess.check_output(["uname", "-a"]).decode().strip()    
    return "kali" in release

# Get the AppData Temp directory path if WSL
def getAppdataTemp():
    try:
        username = os.environ["WSL_USER_NAME"]
    except KeyError:
        raise Exception(
            "WSL detected but environment variable 'WSL_USER_NAME' is unset. "
            "Please run 'export WSL_USER_NAME=' followed by your username as it appears in c:\\Users\\"
        )

    appDataTemp = "C:\\Users\\{0}\\AppData\\Local\\Temp".format(username)
    appDataTempUnix = winPath2Unix(appDataTemp)

    if os.path.exists(appDataTempUnix):
        return appDataTemp
    else:
        raise Exception("The AppData Temp directory path {0} does not exist.".format(appDataTemp))

# Get the temp folder based on os. Create if missing from *nix
def getTempFolder():
    # Prefer environment variable for configurability
    tempPath = os.environ.get("LEGION_TMPDIR")
    if tempPath is None:
        # Use system temp dir + 'legion'
        tempPath = os.path.join(tempfile.gettempdir(), "legion")
    if not os.path.isdir(tempPath):
        os.makedirs(tempPath, exist_ok=True)
    log.info(f"Using temp directory: {tempPath}")
    return tempPath

def getPid(qprocess):
    pid = qprocess.processId()
    return pid

def formatCommandQProcess(inputCommand):
    if isinstance(inputCommand, (list, tuple)):
        parts = list(inputCommand)
    else:
        parts = shlex.split(inputCommand)
    if not parts:
        return "", []
    program = parts[0]
    arguments = parts[1:]
    return program, arguments

# bubble sort algorithm that sorts an array (in place) based on the values in another array
# the values in the array must be comparable and in the corresponding positions
# used to sort objects by one of their attributes.
@timing
def sortArrayWithArray(array, arrayToSort):
    # Sorts array and arrayToSort in place based on the values in array
    # Handle None values and mixed types by converting to comparable format
    def sort_key(x):
        val = x[0]
        if val is None:
            return (0, '')  # None values first
        elif isinstance(val, (int, float)):
            return (1, val)  # Numbers second, sorted numerically
        else:
            return (2, str(val))  # Strings last, sorted alphabetically
    
    combined = sorted(zip(array, arrayToSort), key=sort_key)
    if combined:
        array[:], arrayToSort[:] = zip(*combined)
    else:
        array[:], arrayToSort[:] = [], []


# converts an IP address to an integer (for the sort function)
def IP2Int(ip):
    try:
        ip_clean = str(ip).split("/")[0].strip()
        return int(ipaddress.ip_address(ip_clean))
    except Exception:
        log.error("Input IP {0} is not valid. Passing for now.".format(str(ip)))
        return 0


# used by the settings dialog when a user cancels and the GUI needs to be reset
def clearLayout(layout):
    if layout != None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget != None:
                widget.deleteLater()
            else:
                clearLayout(item.layout())


# this function sets a table view's properties
@timing
def setTableProperties(table, headersLen, hiddenColumnIndexes=[]):
    table.verticalHeader().setVisible(False)  # hide the row headers
    table.setShowGrid(False)  # hide the table grid
    # select entire row instead of single cell
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSortingEnabled(True)  # enable column sorting
    table.horizontalHeader().setStretchLastSection(True)  # header behaviour
    table.horizontalHeader().setSortIndicatorShown(False)  # hide sort arrow from column header
    table.setWordWrap(False)  # row behaviour
    table.resizeRowsToContents()

    for i in range(0, headersLen):  # reset all the hidden columns
        table.setColumnHidden(i, False)

    for i in hiddenColumnIndexes:  # hide some columns
        table.hideColumn(i)

    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)  # create the right-click context menu


def checkHydraResults(output):
    usernames = []
    passwords = []
    string = r'\[[0-9]+\]\[[a-z-]+\].+'  # when a password is found, the line contains [port#][plugin-name]
    results = re.findall(string, output, re.I)
    if results:
        for line in results:
            login = re.search(r'(login:[\s]*)([^\s]+)', line)
            if login:
                log.info('Found username: ' + login.group(2))
                usernames.append(login.group(2))
            password = re.search(r'(password:[\s]*)([^\s]+)', line)
            if password:
                # #print(f"DEBUG 'Found password: ' + password.group(2)

                passwords.append(password.group(2))
        return True, usernames, passwords  # returns the lists of found usernames and passwords
    return False, [], []


# this class is used for example to store found usernames/passwords
class Wordlist():
    def __init__(self, filename):  # needs full path
        self.filename = filename
        self.wordlist = []
        with open(filename, 'a+') as f:  # open for appending + reading
            self.wordlist = f.readlines()
            log.info('Wordlist was created/opened: ' + str(filename))

    def setFilename(self, filename):
        self.filename = filename

    # adds a word to the wordlist (without duplicates)
    def add(self, word):
        with open(self.filename, 'a+') as f:
            f.seek(0)
            self.wordlist = f.readlines()
            if not word + '\n' in self.wordlist:
                log.info('Adding ' + word + ' to the wordlist..')
                self.wordlist.append(word + '\n')
                f.write(word + '\n')


# Base classes — use Qt types when available, plain object otherwise
# This lets MyQProcess/BrowserOpener be defined at module level in both modes.
# Flask only uses Filters and checkHydraResults — never MyQProcess.
_QProcessBase = QProcess if _QT_AVAILABLE else object
_QThreadBase = (QtCore.QThread if _QT_AVAILABLE else object)

# Custom QProcess class
class MyQProcess(_QProcessBase):
    sigHydra = QtCore.pyqtSignal(QObject, list, list, name="hydra")
    sigTooltip = QtCore.pyqtSignal(str)
    sigHasMatch = QtCore.pyqtSignal(str, name="hasMatch")

    def __init__(self, name, tabTitle, hostIp, port, protocol, command, startTime, outputfile, textbox, settings=None):
        if _QT_AVAILABLE:
            QProcess.__init__(self)
        self.id = -1
        self.name = name
        self.tabTitle = tabTitle
        self.hostIp = hostIp
        self.port = port
        self.protocol = protocol
        self.command = command
        self.startTime = startTime
        self.outputfile = outputfile
        self.display = textbox
        self.elapsed = -1
        self.settings = settings
        self.matches = set()
        self.isInteractive = False 

        if settings:
            from ui.gui import MatchHighlighter
            self.highlighter = MatchHighlighter(self.display.document())
        else:
            self.highlighter = None
        
        # CRITICAL: Connect the signals
        #print(f"DEBUG: Connecting signals for {self.name}")
        try:
            self.readyReadStandardOutput.connect(self.readStdOutput)
            #self.readyReadStandardError.connect(self.readStdError)
            #print(f"DEBUG("DEBUG: Signals connected successfully")
        except Exception as e:
            print(f"DEBUG: Error connecting signals: {e}")

    def setupChildProcess(self):
        os.setpgrp()

    def getMatches(self, line, settings, name):
        matches = set()
        
        if name not in settings:
            return matches
        
        currentSettings = settings[name]
        
        # Check negative patterns FIRST
        if 'negative' in currentSettings:
            for match in currentSettings['negative']:
                if match in line:
                    return matches
        
        # Check positive patterns
        if 'positive' in currentSettings:
            for match in currentSettings['positive']:
                if match in line:
                    matches.add(match)
        
        return matches


    def handleMatches(self, output):
        if not self.settings or not hasattr(self.settings, 'matchSettings'):
            return '<br />'.join(output.split('\n'))
        
        matchSettings = self.settings.matchSettings
        hlOutput = []
        lines = output.split('\n')
        
        # Collect negative patterns for the highlighter
        negativePatterns = []
        if 'global' in matchSettings and 'negative' in matchSettings['global']:
            negativePatterns.extend(matchSettings['global']['negative'])
        if self.name in matchSettings and 'negative' in matchSettings[self.name]:
            negativePatterns.extend(matchSettings[self.name]['negative'])
        
        for line in lines:
            globalMatches = self.getMatches(line, matchSettings, 'global')
            toolMatches = self.getMatches(line, matchSettings, self.name)
            matches = globalMatches.union(toolMatches)
            
            if matches:
                self.matches.update(matches)
            
            hlOutput.append(line)
        
        # Filter out matches that are substrings of negative patterns
        # If a positive pattern appears within a negative pattern string, remove it
        filteredMatches = set(self.matches)
        patternsToRemove = set()
        
        for pattern in filteredMatches:
            for negPattern in negativePatterns:
                if pattern in negPattern and pattern != negPattern:
                    # This positive pattern is a substring of a negative pattern
                    patternsToRemove.add(pattern)
                    break
        
        # Remove substring patterns from matches
        filteredMatches = filteredMatches - patternsToRemove
        
        if filteredMatches:
            self.sigHasMatch.emit(', '.join(filteredMatches))
        
        if self.highlighter:
            self.highlighter.updateMatches(self.matches, negativePatterns)
        
        return '<br />'.join(hlOutput)


    @pyqtSlot()
    def readStdOutput(self):
        #print(f"DEBUG: readStdOutput called for {self.name}")
        output = str(self.readAllStandardOutput(), 'utf-8')
        #print(f"DEBUG: Got output length: {len(output)}")

        try:
            #print(f"DEBUG: Starting ANSI conversion")
            from ansi2html import Ansi2HTMLConverter
            conv = Ansi2HTMLConverter(inline=True, linkify=True)
            html = conv.convert(output, full=False)
            #print(f"DEBUG: HTML conversion successful, length: {len(html)}")
            #print(f"DEBUG: HTML preview: {html[:200]}")

            #print(f"DEBUG: Getting text cursor")
            cursor = self.display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            #print(f"DEBUG: Inserting HTML")
            cursor.insertHtml('<pre>' + html + ' < /pre>')  #spaces matter
            #print(f"DEBUG: HTML inserted successfully")

            doc = QTextDocument()
            doc.setHtml(html)
            plain_text = doc.toPlainText()
            #print(f"DEBUG: Plain text extracted, length: {len(plain_text)}")

            self.handleMatches(plain_text)
            #print(f"DEBUG: handleMatches completed")
            
        except ImportError as e:
            #print(f"DEBUG: ImportError - ansi2html not available: {e}")
            self.display.insertPlainText(unicode(output).strip())
            self.handleMatches(output)
        except (IndexError, KeyError, ValueError) as e:
            #print(f"DEBUG: ANSI conversion error - falling back to plain text: {e}")
            self.display.insertPlainText(unicode(output).strip())
            self.handleMatches(output)
        except Exception as e:
            #print(f"DEBUG: Exception in readStdOutput: {e}")
            import traceback
            traceback.print_exc()
            self.display.insertPlainText(unicode(output).strip())
            self.handleMatches(output)

        if self.name == 'hydra':
            found, userlist, passlist = checkHydraResults(output)
            if found:
                self.sigHydra.emit(self.display.parentWidget(), userlist, passlist)

        # Note: stderr is merged with stdout via MergedChannels in QProcess setup
        # Both stdout and stderr are already included in readAllStandardOutput() above

# browser opener class with queue and semaphores
class BrowserOpener(_QThreadBase):
    done = QtCore.pyqtSignal(name="done")  # signals that we are done opening urls in browser
    log = QtCore.pyqtSignal(str, name="log")

    def __init__(self):
        if _QT_AVAILABLE:
            QtCore.QThread.__init__(self, parent=None)
        self.urls = []
        self.processing = False

    def tsLog(self, msg):
        self.log.emit(str(msg))

    def addToQueue(self, url):
        self.urls.append(url)

    def run(self):
        while self.processing:
            self.sleep(1)  # effectively a semaphore

        self.processing = True
        first = True
        while self.urls:
            try:
                url = self.urls.pop(0)
                self.tsLog('Opening url in browser: ' + url)
                if isHttps(url.split(':')[0], url.split(':')[1]):
                    webbrowser.open_new_tab('https://' + url)
                else:
                    webbrowser.open_new_tab('http://' + url)
                if first:
                    self.sleep(3)
                    first = False
                else:
                    self.sleep(1)
            except Exception:
                self.tsLog('Problem while opening url in browser. Moving on..')
                continue

        self.processing = False
        self.done.emit()


# This class handles what is to be shown in each panel
class Filters():
    def __init__(self):
        # host filters
        self.checked = True
        self.up = True
        self.down = False
        # port/service filters
        self.tcp = True
        self.udp = True
        self.portopen = True
        self.portclosed = False
        self.portfiltered = False
        self.keywords = []

    @timing
    def apply(self, up, down, checked, portopen, portfiltered, portclosed, tcp, udp, keywords=[]):
        self.checked = checked
        self.up = up
        self.down = down
        self.tcp = tcp
        self.udp = udp
        self.portopen = portopen
        self.portclosed = portclosed
        self.portfiltered = portfiltered
        self.keywords = keywords

    @timing
    def setKeywords(self, keywords):
        log.info(str(keywords))
        self.keywords = keywords

    @timing
    def getFilters(self):
        return [self.up, self.down, self.checked, self.portopen, self.portfiltered, self.portclosed, self.tcp, self.udp,
                self.keywords]

    @timing
    def display(self):
        log.info('Filters are:')
        log.info('Show checked hosts: ' + str(self.checked))
        log.info('Show up hosts: ' + str(self.up))
        log.info('Show down hosts: ' + str(self.down))
        log.info('Show tcp: ' + str(self.tcp))
        log.info('Show udp: ' + str(self.udp))
        log.info('Show open ports: ' + str(self.portopen))
        log.info('Show closed ports: ' + str(self.portclosed))
        log.info('Show filtered ports: ' + str(self.portfiltered))
        log.info('Keyword search:')
        for w in self.keywords:
            log.info(w)


# Validation functions moved to app/validation.py
from app.validation import (
    validateNmapInput,
    validateCommandFormat,
    validateNumeric,
    validateString,
    validateStringWithSpace,
    validateNmapPorts,
)
