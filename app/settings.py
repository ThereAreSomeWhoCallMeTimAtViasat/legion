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

import shutil
import os
#for matching
import csv
import time

from app.auxiliary import *  # for timestamp

# Qt-free INI settings store (replaces QtCore.QSettings)
# Falls back to QSettings if config_store unavailable and Qt is present
try:
    from app.core.ini_settings import IniSettingsStore as _IniSettings
    _USE_QT_SETTINGS = False
except ImportError:
    _USE_QT_SETTINGS = True

if _USE_QT_SETTINGS:
    try:
        from PyQt6 import QtCore
    except ImportError:
        raise RuntimeError(
            "Neither app.core.ini_settings nor PyQt6 is available. "
            "Cannot load settings."
        )


# this class reads and writes application settings
from app.timing import getTimestamp

log = getAppLogger()

class AppSettings():
    def __init__(self):
        configdir = os.path.expanduser('~/.local/share/legion')
        #configdir = '/home/kali/.local/share/legion'
        #configpath = os.path.join(configdir, 'legion.conf')
        configpath = os.path.expanduser('~/.local/share/legion/legion.conf')
        
        # ADD THESE DEBUG LINES
        #print(f"DEBUG: Config file path: {configpath}")
        #print(f"DEBUG: Config file exists: {os.path.exists(configpath)}")
        #if os.path.exists(configpath):
            #print(f"DEBUG: Config file size: {os.path.getsize(configpath)} bytes")
            #print(f"DEBUG: Config file modified: {os.path.getmtime(configpath)}")
        
        # Clean up stale lock files FIRST
        self.cleanupStaleLockFiles()
        
        if not os.path.exists(configpath):
            if not os.path.isdir(configdir):
                os.makedirs(configdir, exist_ok=True)
            # Try repo legion.conf first, then bundled masterLegion.conf as fallback
            reporoot = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
            defaultconf = os.path.join(reporoot, 'legion.conf')
            masterconf = os.path.join(os.path.dirname(__file__), 'masterLegion.conf')
            if os.path.exists(defaultconf):
                shutil.copy(defaultconf, configpath)
                log.info(f"Created legion.conf from repo default: {defaultconf}")
            elif os.path.exists(masterconf):
                shutil.copy(masterconf, configpath)
                log.info(f"Created legion.conf from bundled master: {masterconf}")
            else:
                log.error(f"No default config found at {defaultconf} or {masterconf}")
        
        log.info(f"Loading settings file: {configpath}")
        
        # ADD THESE DEBUG LINES
        log.debug(f"DEBUG: Loading QSettings from: {configpath}")
        if _USE_QT_SETTINGS:
            self.actions = QtCore.QSettings(configpath, QtCore.QSettings.Format.IniFormat)
        else:
            self.actions = _IniSettings(configpath)
        log.debug(f"DEBUG: Settings fileName: {self.actions.fileName()}")


    #for matching
    def cleanupStaleLockFiles(self):
        """Remove stale .lock files that can cause hangs on startup/exit"""
        config_dir = os.path.expanduser("~/.local/share/legion")
        config_path = os.path.join(config_dir, "legion.conf")
        lock_file = config_path + ".lock"
        
        if os.path.exists(lock_file):
            try:
                # Check if lock file is stale (older than 5 seconds typically means crash)
                lock_age = time.time() - os.path.getmtime(lock_file)
                if lock_age > 5:
                    log.warning(f"Removing stale lock file: {lock_file} (age: {lock_age:.1f}s)")
                    os.remove(lock_file)
            except Exception as e:
                log.error(f"Failed to remove stale lock file: {e}")


    def getGeneralSettings(self):
        return self.getSettingsByGroup("GeneralSettings")

    def getBruteSettings(self):
        return self.getSettingsByGroup("BruteSettings")

    def getStagedNmapSettings(self):
        return self.getSettingsByGroup('StagedNmapSettings')

    def getToolSettings(self):
        return self.getSettingsByGroup('ToolSettings')

    def getGUISettings(self):
        return self.getSettingsByGroup('GUISettings')

    def getAISettings(self):
        return self.getSettingsByGroup('AISettings')

    def getHostActions(self):
        self.actions.beginGroup('HostActions')
        hostactions = []
        sortArray = []
        keys = self.actions.childKeys()
        for k in keys:
            hostactions.append([self.actions.value(k)[0], str(k), self.actions.value(k)[1]])
            sortArray.append(self.actions.value(k)[0])
        self.actions.endGroup()
        sortArrayWithArray(sortArray, hostactions)  # sort by label so that it appears nicely in the context menu
        return hostactions

    # this function fetches all the host actions from the settings file
    def getPortActions(self):
        self.actions.beginGroup('PortActions')
        portactions = []
        sortArray = []
        keys = self.actions.childKeys()
        for k in keys:
            portactions.append([self.actions.value(k)[0], str(k), self.actions.value(k)[1], self.actions.value(k)[2]])
            sortArray.append(self.actions.value(k)[0])
        self.actions.endGroup()
        sortArrayWithArray(sortArray, portactions)  # sort by label so that it appears nicely in the context menu
        return portactions

    # this function fetches all the port actions from the settings file
    def getPortTerminalActions(self):
        self.actions.beginGroup('PortTerminalActions')
        portactions = []
        sortArray = []
        keys = self.actions.childKeys()
        for k in keys:
            portactions.append([self.actions.value(k)[0], str(k), self.actions.value(k)[1], self.actions.value(k)[2]])
            sortArray.append(self.actions.value(k)[0])
        self.actions.endGroup()
        sortArrayWithArray(sortArray, portactions)  # sort by label so that it appears nicely in the context menu
        return portactions

    # this function fetches all the port actions that will be run as terminal commands from the settings file
    def getSchedulerSettings(self):
        settings = []
        self.actions.beginGroup('SchedulerSettings')
        keys = self.actions.childKeys()
        for k in keys:
            settings.append([str(k), self.actions.value(k)[0], self.actions.value(k)[1]])
        self.actions.endGroup()
        return settings

    def getSettingsByGroup(self, name: str) -> dict:
        self.actions.beginGroup(name)
        settings = dict()
        keys = self.actions.childKeys()
        for k in keys:
            settings.update({str(k): str(self.actions.value(k))})
        self.actions.endGroup()
        log.debug("getSettingsByGroup name:{0}, result:{1}".format(str(name), str(settings)))
        return settings
    
    #for matching settings
    def getMatchSettings(self):
        """
        Load match settings from config file.
        Raises ValueError if no matchsettings are found in legion.conf.
        """
        self.actions.beginGroup('MatchSettings')
        matchsettings = {}
        keys = self.actions.childKeys()
        
        if not keys:
            self.actions.endGroup()
            addthis="[MatchSettings] \n global-negative=\"Enumerating vulnerable,valid password not found\" \n global-positive=\"valid pair found,valid password found,open,exists,Netbios,supported,vulnerable\" \n nikto-negative=asdf \n nikto-positive=Server leaks inodes via ETags,X-Frame-Options"
            log.error(f"No matchsettings found in legion.conf:  add this to legion.conf to fix:\n{addthis}")
            raise ValueError("No matchsettings found in legion.conf")
        
        for key in keys:
            rawValue = self.actions.value(key)
            
            # FIX: Handle case where QSettings returns a list instead of string
            if isinstance(rawValue, list):
                # QSettings returned a list - join it into a comma-separated string
                rawValue = ','.join(str(item) for item in rawValue)
            elif rawValue is None:
                rawValue = ''
            
            # Now it's safe to call .strip() on the string
            if isinstance(rawValue, str):
                rawValue = rawValue.strip().strip('"').strip("'")
            else:
                # Fallback: convert to string
                rawValue = str(rawValue)
            
            # Parse the key (format: "scanner-name-positive" or "scanner-name-negative")
            parts = key.rsplit('-', 1)  # Split from right, max 1 split
            if len(parts) == 2:
                scanner_name = parts[0]
                direction = parts[1]  # 'positive' or 'negative'
                
                if direction in ['positive', 'negative']:
                    if scanner_name not in matchsettings:
                        matchsettings[scanner_name] = {'positive': [], 'negative': []}
                    
                    # Split by comma to get individual values
                    if rawValue:
                        # Do NOT strip individual keyword values — spaces are semantic.
                        # " PUT " (space-PUT-space) must match as a whole word; stripping
                        # either space causes false positives:
                        #   lstrip only → "PUT " matches "Reading INPUT to stream"
                        #   strip both  → "PUT"  matches "OUTPUT", "INPUT"
                        # Qt6 QSettings returned list elements without stripping; v.strip()
                        # is used only to skip empty entries, not to modify keyword text.
                        values = [v for v in rawValue.split(',') if v.strip()]
                        matchsettings[scanner_name][direction] = values
                    else:
                        matchsettings[scanner_name][direction] = []
        
        self.actions.endGroup()
        return matchsettings
    
    def backupAndSave(self, newSettings, saveBackup=True):
        """
        Save settings with comprehensive backup and repo synchronization.
        
        This version matches the ConfigDialog.save() behavior:
        1. Backup to both local and repo locations
        2. Write to working config
        3. Sync to repo with timestamped versions
        """
        import shutil
        
        working_config = os.path.expanduser('~/.local/share/legion/legion.conf')
        timestamp = getTimestamp()
        
        # Calculate repo root (parent of app/)
        reporoot = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        repo_config = os.path.join(reporoot, 'legion.conf')
        
        # Step 1: Create backups if requested
        if saveBackup:
            log.info('Backing up old settings and saving new settings...')
            
            # Backup to local directory (~/.local/share/legion/backup/)
            backup_dir = os.path.expanduser("~/.local/share/legion/backup/")
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            
            if os.path.exists(working_config):
                try:
                    local_backup = os.path.join(backup_dir, f'{timestamp}-legion.conf')
                    shutil.copy(working_config, local_backup)
                    log.info(f"Backed up old config to local: {local_backup}")
                except Exception as e:
                    log.warning(f"Could not backup to local directory: {e}")
            
            # Backup to repo root
            if os.path.exists(working_config):
                try:
                    repo_backup = os.path.join(reporoot, "backup", f'{timestamp}-legion.conf.backup')
                    shutil.copy(working_config, repo_backup)
                    log.info(f"Backed up old config to repo: {repo_backup}")
                except Exception as e:
                    log.warning(f"Could not backup to repo: {e}")
        else:
            log.info('Saving config...')

        # Step 2: Write settings using QSettings (structured save)
        # DON'T recreate QSettings - just clear and reuse existing one
        self.actions.clear()  # Clear all existing settings

        self.actions.beginGroup('GeneralSettings')
        self.actions.setValue('log-directory', newSettings.general_log_directory)
        self.actions.setValue('default-terminal', newSettings.general_default_terminal)
        self.actions.setValue('tool-output-black-background', newSettings.general_tool_output_black_background)
        self.actions.setValue('screenshooter-timeout', newSettings.general_screenshooter_timeout)
        self.actions.setValue('process-timeout', newSettings.general_process_timeout)
        self.actions.setValue('web-services', newSettings.general_web_services)
        self.actions.setValue('enable-scheduler', newSettings.general_enable_scheduler)
        self.actions.setValue('enable-scheduler-on-import', newSettings.general_enable_scheduler_on_import)
        self.actions.setValue('max-fast-processes', newSettings.general_max_fast_processes)
        self.actions.setValue('max-slow-processes', newSettings.general_max_slow_processes)
        self.actions.setValue('tool-duplication', newSettings.general_tool_duplication)
        self.actions.endGroup()

        self.actions.beginGroup('BruteSettings')
        self.actions.setValue('store-cleartext-passwords-on-exit', newSettings.brute_store_cleartext_passwords_on_exit)
        self.actions.setValue('username-wordlist-path', newSettings.brute_username_wordlist_path)
        self.actions.setValue('password-wordlist-path', newSettings.brute_password_wordlist_path)
        self.actions.setValue('default-username', newSettings.brute_default_username)
        self.actions.setValue('default-password', newSettings.brute_default_password)
        self.actions.setValue('services', newSettings.brute_services)
        self.actions.setValue('no-username-services', newSettings.brute_no_username_services)
        self.actions.setValue('no-password-services', newSettings.brute_no_password_services)
        self.actions.endGroup()

        self.actions.beginGroup('ToolSettings')
        self.actions.setValue('nmap-path', newSettings.tools_path_nmap)
        self.actions.setValue('hydra-path', newSettings.tools_path_hydra)
        self.actions.setValue('cutycapt-path', newSettings.tools_path_cutycapt)
        self.actions.setValue('texteditor-path', newSettings.tools_path_texteditor)
        self.actions.setValue('pyshodan-api-key', newSettings.tools_pyshodan_api_key)
        self.actions.endGroup()

        self.actions.beginGroup('StagedNmapSettings')
        self.actions.setValue('stage1-ports', newSettings.tools_nmap_stage1_ports)
        self.actions.setValue('stage2-ports', newSettings.tools_nmap_stage2_ports)
        self.actions.setValue('stage3-ports', newSettings.tools_nmap_stage3_ports)
        self.actions.setValue('stage4-ports', newSettings.tools_nmap_stage4_ports)
        self.actions.setValue('stage5-ports', newSettings.tools_nmap_stage5_ports)
        self.actions.setValue('stage6-ports', newSettings.tools_nmap_stage6_ports)
        self.actions.endGroup()

        self.actions.beginGroup('GUISettings')
        self.actions.setValue('process-tab-column-widths', newSettings.gui_process_tab_column_widths)
        self.actions.setValue('hosts-table-column-widths', newSettings.gui_hosts_table_column_widths)
        self.actions.setValue('service-names-table-column-widths', newSettings.gui_service_names_table_column_widths)
        self.actions.setValue('cves-table-column-widths', newSettings.gui_cves_table_column_widths)
        self.actions.setValue('scripts-table-column-widths', newSettings.gui_scripts_table_column_widths)
        self.actions.setValue('splitter-sizes', newSettings.gui_splitter_sizes)
        self.actions.setValue('splitter-3-sizes', newSettings.gui_splitter_3_sizes)
        self.actions.setValue('splitter-2-sizes', newSettings.gui_splitter_2_sizes)
        self.actions.setValue('main-window-geometry', newSettings.gui_main_window_geometry)
        self.actions.setValue('process-tab-detail', newSettings.gui_process_tab_detail)


        self.actions.setValue('hosts-tab-splitter-sizes', newSettings.gui_hosts_tab_splitter_sizes)
        log.debug(f"Saving hosts-tab-splitter-sizes: {newSettings.gui_hosts_tab_splitter_sizes}")
        self.actions.setValue('hosts-tab-splitter-2-sizes', newSettings.gui_hosts_tab_splitter_2_sizes)
        log.debug(f"Saving hosts-tab-splitter-2-sizes: {newSettings.gui_hosts_tab_splitter_2_sizes}")
        self.actions.setValue('hosts-tab-splitter-3-sizes', newSettings.gui_hosts_tab_splitter_3_sizes)
        log.debug(f"Saving hosts-tab-splitter-3-sizes: {newSettings.gui_hosts_tab_splitter_3_sizes}")

        self.actions.setValue('services-tab-splitter-sizes', newSettings.gui_services_tab_splitter_sizes)
        self.actions.setValue('services-tab-splitter-2-sizes', newSettings.gui_services_tab_splitter_2_sizes)
        self.actions.setValue('services-tab-splitter-3-sizes', newSettings.gui_services_tab_splitter_3_sizes)

        self.actions.setValue('tools-tab-splitter-sizes', newSettings.gui_tools_tab_splitter_sizes)
        self.actions.setValue('tools-tab-splitter-2-sizes', newSettings.gui_tools_tab_splitter_2_sizes)
        self.actions.setValue('tools-tab-splitter-3-sizes', newSettings.gui_tools_tab_splitter_3_sizes)

        self.actions.setValue('os-tab-splitter-sizes', newSettings.gui_os_tab_splitter_sizes)
        self.actions.setValue('os-tab-splitter-2-sizes', newSettings.gui_os_tab_splitter_2_sizes)
        self.actions.setValue('os-tab-splitter-3-sizes', newSettings.gui_os_tab_splitter_3_sizes)
        self.actions.endGroup()


        self.actions.beginGroup('HostActions')
        for a in newSettings.hostActions:
            self.actions.setValue(a[1], [a[0], a[2]])
        self.actions.endGroup()

        self.actions.beginGroup('PortActions')
        for a in newSettings.portActions:
            self.actions.setValue(a[1], [a[0], a[2], a[3]])
        self.actions.endGroup()

        self.actions.beginGroup('PortTerminalActions')
        for a in newSettings.portTerminalActions:
            self.actions.setValue(a[1], [a[0], a[2], a[3]])
        self.actions.endGroup()

        self.actions.beginGroup('SchedulerSettings')
        for tool in newSettings.automatedAttacks:
            self.actions.setValue(tool[0], [tool[1], tool[2]])
        self.actions.endGroup()

        # Save MatchSettings
        self.actions.beginGroup('MatchSettings')
        self.actions.remove('')  # Clear existing keys in this group
        
        if hasattr(newSettings, 'matchSettings') and newSettings.matchSettings:
            for scanner_name, directions_dict in newSettings.matchSettings.items():
                if isinstance(directions_dict, dict):
                    for direction, values_list in directions_dict.items():
                        if direction in ['positive', 'negative']:
                            setting_key = f"{scanner_name}-{direction}"
                            if isinstance(values_list, list):
                                csv_string = ','.join(str(v) for v in values_list)
                            else:
                                csv_string = str(values_list)
                            self.actions.setValue(setting_key, csv_string)
                            log.debug(f"Saved MatchSetting: {setting_key} = {csv_string}")
        else:
            log.error("No matchSettings found in newSettings to save.")
        
        self.actions.endGroup()

        # Step 3: Sync to disk with error handling
        try:
            log.info("Syncing settings to disk...")
            self.actions.sync()
            
            # Check sync status
            status = self.actions.status()
            log.info(f"Settings sync status: {status}")
            NoError = (QtCore.QSettings.Status.NoError if _USE_QT_SETTINGS
                       else _IniSettings.Status.NoError)
            if status != NoError:
                log.error(f"QSettings sync failed with status: {status}")
                return
            else:
                log.info("Settings synced successfully to working config")
        except Exception as e:
            log.error(f"Exception during settings sync: {e}")
            return
        
        # Step 4: Copy timestamped version to repo root
        try:
            repo_timestamped = os.path.join(reporoot, 'backup', f'{timestamp}-legion.conf')
            #backup_dir = os.path.expanduser("~/.local/share/legion/backup/")
            shutil.copy(working_config, repo_timestamped)
            log.info(f"Saved timestamped config to repo: {repo_timestamped}")
        except Exception as e:
            log.warning(f"Could not save timestamped config to repo: {e}")
        
        # Step 5: Update repo default config
        try:
            shutil.copy(working_config, repo_config)
            log.info(f"Updated repo default config: {repo_config}")
        except Exception as e:
            log.warning(f"Could not update repo default config: {e}")



# This class first sets all the default settings and
# then overwrites them with the settings found in the configuration file
class Settings():
    def __init__(self, appSettings=None):

        # general
        self.general_log_directory = './log'
        self.general_default_terminal = "gnome-terminal"
        self.general_tool_output_black_background = "False"
        self.general_screenshooter_timeout = "15000"
        self.general_process_timeout = "300"
        self.general_web_services = "http,https,ssl,soap,http-proxy,http-alt,https-alt"
        self.general_enable_scheduler = "True"
        self.general_max_fast_processes = "10"
        self.general_max_slow_processes = "10"
        self.general_tool_duplication = "askMe" # options: append, skip, newTab, askMe

        # brute
        self.brute_store_cleartext_passwords_on_exit = "True"
        self.brute_username_wordlist_path = "/usr/share/wordlists/"
        self.brute_password_wordlist_path = "/usr/share/wordlists/"
        self.brute_default_username = "root"
        self.brute_default_password = "password"
        self.brute_services = "asterisk,afp,cisco,cisco-enable,cvs,firebird,ftp,ftps,http-head,http-get," + \
                              "https-head,https-get,http-get-form,http-post-form,https-get-form," + \
                              "https-post-form,http-proxy,http-proxy-urlenum,icq,imap,imaps,irc,ldap2,ldap2s," + \
                              "ldap3,ldap3s,ldap3-crammd5,ldap3-crammd5s,ldap3-digestmd5,ldap3-digestmd5s," + \
                              "mssql,mysql,ncp,nntp,oracle-listener,oracle-sid,pcanywhere,pcnfs,pop3,pop3s," + \
                              "postgres,rdp,rexec,rlogin,rsh,s7-300,sip,smb,smtp,smtps,smtp-enum,snmp,socks5," + \
                              "ssh,sshkey,svn,teamspeak,telnet,telnets,vmauthd,vnc,xmpp"
        self.brute_no_username_services = "cisco,cisco-enable,oracle-listener,s7-300,snmp,vnc"
        self.brute_no_password_services = "oracle-sid,rsh,smtp-enum"

        # tools
        self.tools_nmap_stage1_ports = "PORTS|T:80,81,443,4443,8080,8081,8082"
        self.tools_nmap_stage2_ports = "PORTS|T:25,135,137,139,445,1433,3306,5432,U:137,161,162,1434"
        self.tools_nmap_stage3_ports = "PORTS|T:23,21,22,110,111,2049,3389,8080,U:500,5060"
        self.tools_nmap_stage4_ports = "PORTS|T:0-20,24,26-79,81-109,112-134,136,138,140-442,444,446-1432,1434-2048," + \
                                       "2050-3305,3307-3388,3390-5431,5433-8079,8081-29999"
        self.tools_nmap_stage5_ports = "PORTS|T:30000-65535"
        self.tools_nmap_stage6_ports = "NSE|vulners"

        self.tools_path_nmap = "/sbin/nmap"
        self.tools_path_hydra = "/usr/bin/hydra"
        self.tools_path_cutycapt = "/usr/bin/cutycapt"
        self.tools_path_texteditor = "/usr/bin/xdg-open"
        self.tools_pyshodan_api_key = ""
        
        # GUI settings
        self.gui_process_tab_column_widths = "125,0,100,150,100,100,100,100,100,100,100,100,100,100,100,100,100"
        self.gui_hosts_table_column_widths = "150,150,150,150"
        self.gui_service_names_table_column_widths = "150,150,150"
        self.gui_cves_table_column_widths = "150,150,150,150,150,150"
        self.gui_scripts_table_column_widths = "150,150,150"
        self.gui_splitter_sizes = "200,500,200"
        self.gui_splitter_3_sizes = "300,400"
        self.gui_splitter_2_sizes = "400,200"
        self.gui_main_window_geometry = "1200,800,100,100"
        self.gui_process_tab_detail = False

        # splitter-sizes definitions
        self.gui_hosts_tab_splitter_sizes = '290,1243,0'
        self.gui_hosts_tab_splitter_2_sizes = '343,149'
        self.gui_hosts_tab_splitter_3_sizes = '0,0,0'

        self.gui_services_tab_splitter_sizes = '200,500,200'
        self.gui_services_tab_splitter_2_sizes = '400,200'
        self.gui_services_tab_splitter_3_sizes = '300,400'

        self.gui_tools_tab_splitter_sizes = '200,500,200'
        self.gui_tools_tab_splitter_2_sizes = '400,200'
        self.gui_tools_tab_splitter_3_sizes = '300,400'

        self.gui_os_tab_splitter_sizes = '200,500,200'
        self.gui_os_tab_splitter_2_sizes = '400,200'
        self.gui_os_tab_splitter_3_sizes = '300,400'



        self.hostActions = []
        self.portActions = []
        self.portTerminalActions = []
        self.stagedNmapSettings = []
        self.automatedAttacks = []
        #for matching
        self.matchSettings = dict()


        # now that all defaults are set, overwrite with whatever was in the .conf file (stored in appSettings)
        if appSettings:
            try:
                self.generalSettings = appSettings.getGeneralSettings()
                log.debug(f"Loaded generalSettings: {self.generalSettings}")
                self.bruteSettings = appSettings.getBruteSettings()
                self.stagedNmapSettings = appSettings.getStagedNmapSettings()
                self.toolSettings = appSettings.getToolSettings()
                self.guiSettings = appSettings.getGUISettings()
                log.debug(f"Loaded guiSettings: {self.guiSettings}")
                self.hostActions = appSettings.getHostActions()
                self.portActions = appSettings.getPortActions()
                self.portTerminalActions = appSettings.getPortTerminalActions()
                self.automatedAttacks = appSettings.getSchedulerSettings()
                #for matching
                self.matchSettings = appSettings.getMatchSettings()


                # general
                self.general_log_directory = self.generalSettings.get("log-directory", "./log")
                self.general_default_terminal = self.generalSettings['default-terminal']
                self.general_tool_output_black_background = self.generalSettings['tool-output-black-background']
                self.general_screenshooter_timeout = self.generalSettings['screenshooter-timeout']
                self.general_process_timeout = self.generalSettings.get('process-timeout', '300')
                self.general_web_services = self.generalSettings['web-services']
                self.general_enable_scheduler = self.generalSettings['enable-scheduler']
                self.general_enable_scheduler_on_import = self.generalSettings['enable-scheduler-on-import']
                self.general_max_fast_processes = self.generalSettings['max-fast-processes']
                self.general_max_slow_processes = self.generalSettings['max-slow-processes']
                self.general_tool_duplication = self.generalSettings['tool-duplication']

                # brute
                self.brute_store_cleartext_passwords_on_exit = self.bruteSettings['store-cleartext-passwords-on-exit']
                self.brute_username_wordlist_path = self.bruteSettings['username-wordlist-path']
                self.brute_password_wordlist_path = self.bruteSettings['password-wordlist-path']
                self.brute_default_username = self.bruteSettings['default-username']
                self.brute_default_password = self.bruteSettings['default-password']
                self.brute_services = self.bruteSettings['services']
                self.brute_no_username_services = self.bruteSettings['no-username-services']
                self.brute_no_password_services = self.bruteSettings['no-password-services']

                # tools
                self.tools_nmap_stage1_ports = self.stagedNmapSettings['stage1-ports']
                self.tools_nmap_stage2_ports = self.stagedNmapSettings['stage2-ports']
                self.tools_nmap_stage3_ports = self.stagedNmapSettings['stage3-ports']
                self.tools_nmap_stage4_ports = self.stagedNmapSettings['stage4-ports']
                self.tools_nmap_stage5_ports = self.stagedNmapSettings['stage5-ports']
                self.tools_nmap_stage6_ports = self.stagedNmapSettings['stage6-ports']

                self.tools_path_nmap = self.toolSettings['nmap-path']
                self.tools_path_hydra = self.toolSettings['hydra-path']
                self.tools_path_cutycapt = self.toolSettings['cutycapt-path']
                self.tools_path_texteditor = self.toolSettings['texteditor-path']
                self.tools_pyshodan_api_key = self.toolSettings['pyshodan-api-key']

                # gui
                self.gui_process_tab_column_widths = self.guiSettings.get('process-tab-column-widths', "125,0,100,150,100,100,100,100,100,100,100,100,100,100,100,100,100")
                self.gui_process_tab_detail = self.guiSettings.get('process-tab-detail', "False")
                self.gui_hosts_table_column_widths = self.guiSettings.get('hosts-table-column-widths', "150,150,150,150")
                self.gui_service_names_table_column_widths = self.guiSettings.get('service-names-table-column-widths', "150,150,150")
                self.gui_cves_table_column_widths = self.guiSettings.get('cves-table-column-widths', "150,150,150,150,150,150")
                self.gui_scripts_table_column_widths = self.guiSettings.get('scripts-table-column-widths', "150,150,150")
                self.gui_splitter_sizes = self.guiSettings.get('splitter-sizes', "200,500,200")
                self.gui_splitter_3_sizes = self.guiSettings.get('splitter-3-sizes', "300,400")
                self.gui_splitter_2_sizes = self.guiSettings.get('splitter-2-sizes', "400,200")
                #self.gui_main_window_geometry = self.guiSettings['main-window-geometry']#.get('main-window-geometry', "1200,800,100,100")
                self.gui_main_window_geometry = self.guiSettings.get('main-window-geometry', "1200,800,100,100")
                log.debug(f"replacing guiSettings - gui_splitter_sizes: {self.gui_splitter_sizes}")
                log.debug(f"replacing guiSettings - main-window-geometry: {self.gui_main_window_geometry}")

                # Tab-specific splitter sizes
                self.gui_hosts_tab_splitter_sizes = self.guiSettings['hosts-tab-splitter-sizes']
                self.gui_hosts_tab_splitter_2_sizes = self.guiSettings['hosts-tab-splitter-2-sizes']
                self.gui_hosts_tab_splitter_3_sizes = self.guiSettings['hosts-tab-splitter-3-sizes']

                self.gui_services_tab_splitter_sizes = self.guiSettings.get('services-tab-splitter-sizes', '200,500,200')
                self.gui_services_tab_splitter_2_sizes = self.guiSettings.get('services-tab-splitter-2-sizes', '400,200')
                self.gui_services_tab_splitter_3_sizes = self.guiSettings.get('services-tab-splitter-3-sizes', '300,400')

                self.gui_tools_tab_splitter_sizes = self.guiSettings['tools-tab-splitter-sizes']
                self.gui_tools_tab_splitter_2_sizes = self.guiSettings['tools-tab-splitter-2-sizes']
                self.gui_tools_tab_splitter_3_sizes = self.guiSettings['tools-tab-splitter-3-sizes']

                self.gui_os_tab_splitter_sizes = self.guiSettings.get('os-tab-splitter-sizes', '200,500,200')
                self.gui_os_tab_splitter_2_sizes = self.guiSettings.get('os-tab-splitter-2-sizes', '400,200')
                self.gui_os_tab_splitter_3_sizes = self.guiSettings.get('os-tab-splitter-3-sizes', '300,400')




            except KeyError as e:
                log.info('Something went wrong while loading the configuration file. Falling back to default ' +
                         'settings for some settings.')
                log.info('Go to the settings menu to fix the issues!')
                log.error(str(e))

    def __eq__(self, other):  # returns false if settings objects are different
        if type(other) is type(self):
            return self.__dict__ == other.__dict__
        return False


if __name__ == "__main__":
    settings = AppSettings()
    s = Settings(settings)
    s2 = Settings(settings)
    log.info(s == s2)
    s2.general_default_terminal = 'whatever'
    log.info(s == s2)
