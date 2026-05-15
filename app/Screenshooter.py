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

import os
import warnings
import signal
warnings.filterwarnings("ignore", category=UserWarning)

from PyQt6 import QtCore

from app.logging.legionLog import getAppLogger
from app.httputil.isHttps import isHttps
from app.timing import getTimestamp
from app.auxiliary import isKali

logger = getAppLogger()

class Screenshooter(QtCore.QThread):

    done = QtCore.pyqtSignal(str, str, str, name="done")  # signal sent after each individual screenshot is taken
    log = QtCore.pyqtSignal(str, name="log")

    def __init__(self, timeout):
        QtCore.QThread.__init__(self, parent=None)
        self.queue = []
        self.processing = False
        self.timeout = timeout  # screenshooter timeout (ms)
        self.current_subprocess = None  # Track running subprocess
        self.blacklisted_ips = set()  # IPs to skip screenshots for
        self.current_ip = None  # Track which IP we're currently processing

    def tsLog(self, msg):
        self.log.emit(str(msg))
        logger.info(msg)

    def addToQueue(self, ip, port, url):
        self.queue.append([ip, port, url])

    # this function should be called when the project is saved/saved as as the tool-output folder changes
    def updateOutputFolder(self, screenshotsFolder):
        self.outputfolder = screenshotsFolder

    def run(self):
        while self.processing == True:
            self.sleep(1)  # effectively a semaphore

        self.processing = True

        for i in range(0, len(self.queue)):
            try:
                queueItem = self.queue.pop(0)
                ip = queueItem[0]
                port = queueItem[1]
                url = queueItem[2]
                
                # Check blacklist before processing
                if ip in self.blacklisted_ips:
                    self.tsLog(f'Skipping screenshot for blacklisted IP: {ip}')
                    continue
                
                self.current_ip = ip
                outputfile = getTimestamp() + '-screenshot-' + url.replace(':', '-') + '.png'
                self.save(url, ip, port, outputfile)
                self.current_ip = None
            except Exception as e:
                self.tsLog('Unable to take the screenshot. Error follows.')
                self.tsLog(e)
                continue

        self.processing = False

        if not len(self.queue) == 0:
            # if meanwhile queue were added to the queue, start over unless we are in pause mode
            self.run()

    def save(self, url, ip, port, outputfile):
        # Check if this IP is blacklisted
        if ip in self.blacklisted_ips:
            self.tsLog(f'Skipping screenshot for blacklisted IP: {ip}')
            self.done.emit(ip, port, "")
            return
        
        # Handle single node URI case by pivot to IP
        if len(str(url).split('.')) == 1:
            url = '{0}:{1}'.format(str(ip), str(port))

        host_for_https = str(url)
        if '://' in host_for_https:
            host_for_https = host_for_https.split('://', 1)[1]
        host_for_https = host_for_https.split(':', 1)[0]

        try:
            if isHttps(host_for_https, port):
                url = 'https://{0}'.format(url)
            else:
                url = 'http://{0}'.format(url)
        except Exception as e:
            self.tsLog(f"Error determining HTTPS for {host_for_https}:{port} - {e}. Defaulting to HTTP.")
            url = 'http://{0}'.format(url)

        self.tsLog('Taking Screenshot of: {0}'.format(str(url)))

        if isKali():
            eyewitness_path = "/usr/bin/eyewitness"
        else:
            eyewitness_path = "/usr/local/bin/eyewitness"

        import tempfile
        import subprocess

        try:
            tmpOutputfolder = tempfile.mkdtemp(dir=self.outputfolder)

            if not os.path.isfile(eyewitness_path):
                raise FileNotFoundError("EyeWitness not found at /usr/bin/eyewitness. Please install it.")

            command = (
                'xvfb-run -a {eyewitness} --single {url} --no-prompt --web --delay 5 -d {outputfolder}'
            ).format(
                eyewitness=eyewitness_path,
                url=url,
                outputfolder=tmpOutputfolder
            )

            self.tsLog(f'Executing: {command}')

            # Store subprocess so we can kill it if needed
            self.current_subprocess = subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.current_subprocess.wait()  # wait for command to finish
            self.current_subprocess = None

            # Check again if IP was blacklisted while we were processing
            if ip in self.blacklisted_ips:
                self.tsLog(f'IP {ip} was blacklisted during screenshot - discarding result')
                self.done.emit(ip, port, "")
                return

            screens_dir = os.path.join(tmpOutputfolder, 'screens')
            if not os.path.isdir(screens_dir):
                raise FileNotFoundError(f"EyeWitness did not create expected directory: {screens_dir}")

            files = [f for f in os.listdir(screens_dir) if f.lower().endswith('.png')]
            if not files:
                raise FileNotFoundError(f"No screenshot PNG found in {screens_dir}. EyeWitness may have failed.")

            fileName = files[0]

            if tmpOutputfolder.startswith(self.outputfolder):
                rel_tmp = tmpOutputfolder[len(self.outputfolder):].lstrip(os.sep)
            else:
                rel_tmp = tmpOutputfolder

            outputfile = os.path.join(rel_tmp, 'screens', fileName)
            normalized_outputfile = outputfile.replace("\\", "/")
            outputfile = normalized_outputfile

            deterministic_name = f"{ip}-{port}-screenshot.png"
            deterministic_path = os.path.join(self.outputfolder, deterministic_name)

            try:
                import shutil
                src_path = os.path.join(tmpOutputfolder, 'screens', fileName)
                shutil.copy2(src_path, deterministic_path)
                self.tsLog(f"Copied screenshot to deterministic filename: {deterministic_path}")
            except Exception as e:
                self.tsLog(f"Failed to copy screenshot to deterministic filename: {e}")

        except Exception as e:
            self.tsLog(f"EyeWitness screenshot failed: {e}")
            self.done.emit(ip, port, "")
            return

        self.tsLog('Saving screenshot as: {0}'.format(str(outputfile)))
        self.done.emit(ip, port, outputfile)

    def cancelScreenshotsForIp(self, ip):
        """Cancel all queued and in-progress screenshots for a specific IP."""
        self.tsLog(f"=== cancelScreenshotsForIp START for IP: {ip} ===")
        self.tsLog(f"Queue length BEFORE: {len(self.queue)}")
        
        # Add to blacklist
        self.blacklisted_ips.add(ip)
        self.tsLog(f"Added {ip} to blacklist")
        
        # Remove from queue
        original_length = len(self.queue)
        self.queue = [item for item in self.queue if item[0] != ip]
        removed_from_queue = original_length - len(self.queue)
        self.tsLog(f"Removed {removed_from_queue} items from queue")
        
        # Kill current subprocess if it's for this IP
        if self.current_subprocess and self.current_ip == ip:
            try:
                self.current_subprocess.send_signal(signal.SIGKILL)
                self.current_subprocess = None
                self.tsLog(f"Killed running screenshot subprocess for {ip}")
            except Exception as e:
                self.tsLog(f"Error killing subprocess: {e}")
        
        self.tsLog(f"Queue length AFTER: {len(self.queue)}")
        self.tsLog(f"=== cancelScreenshotsForIp END ===")
        return removed_from_queue

    def removeFromBlacklist(self, ip):
        """Remove an IP from the blacklist."""
        if ip in self.blacklisted_ips:
            self.blacklisted_ips.remove(ip)
            self.tsLog(f"Removed {ip} from blacklist")
            return True
        return False
