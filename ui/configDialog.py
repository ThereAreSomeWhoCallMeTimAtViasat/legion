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

"""

import os
from PyQt6.QtGui import *                                               # for filters dialog
from PyQt6.QtWidgets import *
from PyQt6 import QtWidgets, QtGui
from app.auxiliary import *                                             # for timestamps
from six import u as unicode
from ui.ancillaryDialog import flipState

class Config(QtWidgets.QTextEdit):
    def __init__(self, qss, parent = None):
        super(Config, self).__init__(parent)
        self.setMinimumHeight(550)
        self.setStyleSheet(qss)
        self.originalText = open(os.path.expanduser('~/.local/share/legion/legion.conf'),'r').read()
        self.setPlainText(self.originalText)
        self.setReadOnly(False)
        
        # Track changes
        self.textChanged.connect(self.markAsModified)
        self.modified = False
    
    def markAsModified(self):
        """Track that content has been modified"""
        self.modified = True
    
    def getText(self):
        return self.toPlainText()
    
    def hasUnsavedChanges(self):
        """Check if current text differs from original"""
        return self.toPlainText() != self.originalText
    
    def reloadFromFile(self):
        """Reload original content from file, discarding changes"""
        self.originalText = open(os.path.expanduser('~/.local/share/legion/legion.conf'),'r').read()
        self.setPlainText(self.originalText)
        self.modified = False

class ConfigDialog(QtWidgets.QDialog):
    def __init__(self, controller, qss, parent = None):
        super(ConfigDialog, self).__init__(parent)
        self.controller = controller
        self.qss = qss
        self.setWindowTitle("Config")
        self.Main = QtWidgets.QVBoxLayout()
        self.frm = QtWidgets.QFormLayout()
        self.setGeometry(0, 0, 800, 600)
        self.center()
        self.Qui_update()
        self.setStyleSheet(self.qss)

    def center(self):
        frameGm = self.frameGeometry()
        centerPoint = QtGui.QGuiApplication.primaryScreen().availableGeometry().center()
        frameGm.moveCenter(centerPoint)
        self.move(frameGm.topLeft())

    def Qui_update(self):
        self.form = QtWidgets.QFormLayout()
        self.form2 = QtWidgets.QVBoxLayout()
        self.tabwid = QtWidgets.QTabWidget(self)
        self.TabConfig = QtWidgets.QWidget(self)
        self.cmdSave = QtWidgets.QPushButton("Save")
        self.cmdSave.setFixedWidth(90)
        self.cmdSave.setIcon(QtGui.QIcon('images/save.png'))
        self.cmdSave.clicked.connect(self.save)
        self.cmdClose = QtWidgets.QPushButton("Close")
        self.cmdClose.setFixedWidth(90)
        self.cmdClose.setIcon(QtGui.QIcon('images/close.png'))
        self.cmdClose.clicked.connect(self.closeDialog)  # Changed to closeDialog

        self.formConfig = QtWidgets.QFormLayout()

        # Config Section
        self.configObj = Config(qss = self.qss)
        self.formConfig.addRow(self.configObj)
        self.TabConfig.setLayout(self.formConfig)

        self.tabwid.addTab(self.TabConfig,'Config')
        self.form.addRow(self.tabwid)
        self.form2.addWidget(QtWidgets.QLabel('<br>'))
        self.form2.addWidget(self.cmdSave, alignment = Qt.AlignmentFlag.AlignCenter)
        self.form2.addWidget(self.cmdClose, alignment = Qt.AlignmentFlag.AlignCenter)
        self.form.addRow(self.form2)
        self.Main.addLayout(self.form)
        self.setLayout(self.Main)

    def identifyLoadError(self, error_msg, traceback_text):
        """
        Analyze the load error and provide helpful hints about what went wrong.
        """
        hints = []
        
        # Check for specific error patterns
        if 'KeyError' in traceback_text:
            # Extract the missing key if possible
            import re
            key_match = re.search(r"KeyError: '([^']+)'", traceback_text)
            if key_match:
                missing_key = key_match.group(1)
                hints.append(
                    f"Missing required setting: '{missing_key}'\n"
                    f"This setting is required but not found in the config file."
                )
        
        if 'ValueError' in traceback_text:
            hints.append(
                "Invalid value format detected.\n"
                "Check that numeric values are numbers and boolean values are True/False."
            )
        
        if 'AttributeError' in traceback_text:
            hints.append(
                "Configuration structure issue.\n"
                "A required setting or section may be missing or incorrectly named."
            )
        
        # Check for common setting names in error
        common_settings = [
            'GeneralSettings', 'BruteSettings', 'ToolSettings',
            'StagedNmapSettings', 'GUISettings', 'HostActions',
            'PortActions', 'SchedulerSettings', 'MatchSettings'
        ]
        
        for setting in common_settings:
            if setting.lower() in error_msg.lower() or setting.lower() in traceback_text.lower():
                hints.append(
                    f"Problem likely in [{setting}] section.\n"
                    f"Check this section for missing or malformed entries."
                )
        
        if not hints:
            hints.append(
                "Unable to identify specific cause.\n"
                "Check the log file for detailed traceback information."
            )
        
        return "\n".join(hints)

    
    def closeDialog(self):
        """Handle close button with unsaved changes check"""
        # Check if there are unsaved changes
        if self.configObj.hasUnsavedChanges():
            reply = QMessageBox.warning(
                self,
                "Unsaved Changes",
                "You have unsaved changes that will be lost.\n\n"
                "Are you sure you want to close without saving?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Cancel:
                return  # Don't close
        
        # User confirmed or no changes - reload from file to discard any edits
        self.configObj.reloadFromFile()
        
        # Close the dialog
        self.close()
    
    def closeEvent(self, event):
        """Handle window close (X button) with same check"""
        if self.configObj.hasUnsavedChanges():
            reply = QMessageBox.warning(
                self,
                "Unsaved Changes",
                "You have unsaved changes that will be lost.\n\n"
                "Are you sure you want to close without saving?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()  # Prevent closing
                return
        
        # User confirmed or no changes - reload from file
        self.configObj.reloadFromFile()
        event.accept()

    def checkSettingExists(self, config_text, section, key):
        """
        Check if a specific setting exists in the config text.
        """
        lines = config_text.split('\n')
        in_section = False
        
        for line in lines:
            stripped = line.strip()
            
            # Check if we're entering the target section
            if stripped == f'[{section}]':
                in_section = True
                continue
            
            # Check if we're leaving the section
            if in_section and stripped.startswith('['):
                in_section = False
                break
            
            # Check for the key in this section
            if in_section and '=' in stripped:
                line_key = stripped.split('=', 1)[0].strip()
                if line_key == key:
                    return True
        
        return False

    def analyzeMissingSettings(self, config_text, missing_keys):
        """
        Analyze config to identify which sections are missing required settings.
        """
        if not missing_keys:
            return "Unknown configuration errors detected."
        
        # Map settings to their expected sections
        setting_sections = {
            'default-terminal': 'GeneralSettings',
            'tool-output-black-background': 'GeneralSettings',
            'screenshooter-timeout': 'GeneralSettings',
            'web-services': 'GeneralSettings',
            'enable-scheduler': 'GeneralSettings',
            'enable-scheduler-on-import': 'GeneralSettings',
            'max-fast-processes': 'GeneralSettings',
            'max-slow-processes': 'GeneralSettings',
            'tool-duplication': 'GeneralSettings',
            'store-cleartext-passwords-on-exit': 'BruteSettings',
            'username-wordlist-path': 'BruteSettings',
            'password-wordlist-path': 'BruteSettings',
            'default-username': 'BruteSettings',
            'default-password': 'BruteSettings',
            'services': 'BruteSettings',
            'no-username-services': 'BruteSettings',
            'no-password-services': 'BruteSettings',
            'nmap-path': 'ToolSettings',
            'hydra-path': 'ToolSettings',
            'cutycapt-path': 'ToolSettings',
            'texteditor-path': 'ToolSettings',
            'pyshodan-api-key': 'ToolSettings',
            'stage1-ports': 'StagedNmapSettings',
            'stage2-ports': 'StagedNmapSettings',
            'stage3-ports': 'StagedNmapSettings',
            'stage4-ports': 'StagedNmapSettings',
            'stage5-ports': 'StagedNmapSettings',
            'stage6-ports': 'StagedNmapSettings',
            'process-tab-column-widths': 'GUISettings',
            'process-tab-detail': 'GUISettings',
        }
        
        # Group missing keys by section
        missing_by_section = {}
        for key in missing_keys:
            section = setting_sections.get(key, 'Unknown')
            if section not in missing_by_section:
                missing_by_section[section] = []
            missing_by_section[section].append(key)
        
        # Check if sections exist in config
        lines = config_text.split('\n')
        existing_sections = set()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('[') and stripped.endswith(']'):
                section_name = stripped[1:-1]
                existing_sections.add(section_name)
        
        # Build detailed error message
        errors = []
        for section, keys in missing_by_section.items():
            if section not in existing_sections:
                errors.append(
                    f"❌ Missing section: [{section}]\n"
                    f"   This entire section is missing from the config file.\n"
                    f"   Add: [{section}]"
                )
            else:
                errors.append(
                    f"❌ Section [{section}] is incomplete\n"
                    f"   Missing {len(keys)} required setting(s):\n" +
                    "\n".join(f"     • {key}" for key in keys)
                )
        
        return "\n\n".join(errors)


    def save(self):
        """
        Save with comprehensive validation - shows scrollable error dialog if needed.
        """
        import shutil
        import tempfile
        import traceback
        from PyQt6 import QtCore
        from PyQt6.QtWidgets import QMessageBox
        from app.timing import getTimestamp
        from app.auxiliary import getAppLogger
        from app.settings import Settings, AppSettings
        log = getAppLogger()
        
        log.info("=" * 80)
        log.debug("DEBUG: save() method called")
        
        # Get the edited config text
        new_config_text = self.configObj.getText()
        log.debug(f"DEBUG:Config text length: {len(new_config_text)} characters")
        
        # Step 1: Syntax validation
        log.debug("DEBUG: Starting syntax validation")
        syntax_errors = self.validateConfigSyntax(new_config_text)
        
        if syntax_errors:
            log.debug(f"DEBUG:BLOCKING SAVE - Found {len(syntax_errors)} syntax errors")
            self.showScrollableErrorDialog(
                f"Cannot Save - {len(syntax_errors)} Syntax Error(s)",
                "The configuration file has syntax errors that MUST be fixed:",
                syntax_errors
            )
            return
        
        log.debug("DEBUG: Syntax validation passed")
        
        # Step 2: Semantic validation
        log.debug("DEBUG: Starting semantic validation (checking setting names)")
        semantic_errors = self.validateSettingNames(new_config_text)
        
        if semantic_errors:
            log.debug(f"DEBUG:BLOCKING SAVE - Found {len(semantic_errors)} invalid settings")
            self.showScrollableErrorDialog(
                f"Cannot Save - {len(semantic_errors)} Invalid Setting(s)",
                "The configuration contains unknown or misspelled setting names:\n\n"
                "These settings will be ignored by Legion.",
                semantic_errors
            )
            return
        
        log.debug("DEBUG: Semantic validation passed")
        
        # Step 3: QSettings validation
        log.debug("DEBUG: Starting QSettings validation")
        temp_fd, temp_path = tempfile.mkstemp(suffix='.conf', prefix='legion-validate-')
        
        try:
            with os.fdopen(temp_fd, 'w') as f:
                f.write(new_config_text)
            
            test_settings = QtCore.QSettings(temp_path, QtCore.QSettings.Format.IniFormat)
            status = test_settings.status()
            
            if status != QtCore.QSettings.Status.NoError:
                log.error(f"DEBUG: QSettings validation FAILED")
                QMessageBox.critical(
                    self,
                    "Cannot Save - Parse Error",
                    f"QSettings cannot parse this configuration.\n❌ Save blocked."
                )
                os.remove(temp_path)
                return
        except Exception as e:
            log.error(f"DEBUG: QSettings crashed: {e}")
            QMessageBox.critical(self, "Cannot Save", f"Parse error: {str(e)}\n❌ Save blocked.")
            try:
                os.remove(temp_path)
            except:
                pass
            return
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
        
        log.debug("DEBUG: All validations passed - proceeding with save")
        
        # Proceed with save (same as before)
        working_config = os.path.expanduser('~/.local/share/legion/legion.conf')
        reporoot = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
        repo_config = os.path.join(reporoot, 'legion.conf')
        timestamp = getTimestamp()
        
        # Backup
        if os.path.exists(working_config):
            try:
                repo_backup = os.path.join(reporoot, f'{timestamp}-legion.conf.backup')
                shutil.copy(working_config, repo_backup)
                log.info(f"Backed up old config to: {repo_backup}")
            except Exception as e:
                log.warning(f"Could not backup: {e}")
        
        # Write new config
        try:
            with open(working_config, 'w') as fileObj:
                fileObj.write(new_config_text)
            log.info(f"Saved config to: {working_config}")
        except Exception as e:
            log.error(f"Failed to write config: {e}")
            QMessageBox.critical(self, "Save Failed", f"Failed to write file:\n{e}")
            return
        
        # Copy to repo
        try:
            repo_timestamped = os.path.join(reporoot, f'{timestamp}-legion.conf')
            shutil.copy(working_config, repo_timestamped)
            log.info(f"Saved timestamped to repo: {repo_timestamped}")
        except Exception as e:
            log.warning(f"Could not save timestamped: {e}")
        
        try:
            shutil.copy(working_config, repo_config)
            log.info(f"Updated repo default: {repo_config}")
        except Exception as e:
            log.warning(f"Could not update repo config: {e}")
        
        # Reload settings
        log.debug("DEBUG: Reloading settings")
        try:
            self.controller.loadSettings()
            log.info("Settings reloaded successfully")
        except Exception as e:
            import traceback
            log.error(f"Settings reload failed: {e}")
            log.error(f"Traceback: {traceback.format_exc()}")  # ← Add this
        
        # Success
        self.configObj.originalText = new_config_text
        self.configObj.modified = False
        log.info("Config saved successfully")
        
        QMessageBox.information(self, "Success", "Configuration saved and reloaded.")
        log.info("=" * 80)

    def showScrollableErrorDialog(self, title, message, errors):
        """
        Show a scrollable dialog with all errors listed.
        
        Args:
            title: Dialog window title
            message: Header message
            errors: List of error strings
        """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel
        from PyQt6.QtCore import Qt
        
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.resize(700, 500)  # Reasonable size
        
        # Layout
        layout = QVBoxLayout()
        
        # Header message
        header = QLabel(message)
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: bold; padding: 10px;")
        layout.addWidget(header)
        
        # Error count summary
        summary = QLabel(f"Found {len(errors)} error(s). Please fix before saving:")
        summary.setStyleSheet("padding: 5px 10px;")
        layout.addWidget(summary)
        
        # Scrollable text area with errors
        error_text = QTextEdit()
        error_text.setReadOnly(True)
        
        # Format all errors with spacing
        formatted_errors = "\n\n".join(errors)
        error_text.setPlainText(formatted_errors)
        
        # Style the text area
        error_text.setStyleSheet("""
            QTextEdit {
                font-family: monospace;
                font-size: 10pt;
                padding: 10px;
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)
        
        layout.addWidget(error_text)
        
        # Footer message
        footer = QLabel("❌ Save blocked. Fix the errors and try again.")
        footer.setStyleSheet("color: #ff4444; font-weight: bold; padding: 10px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        dialog.setLayout(layout)
        
        # Show dialog
        dialog.exec()


    def validateSettingNames(self, config_text):
        """
        Validate that all setting keys are recognized/expected by Legion.
        Catches typos like 'process-tab-columnwidths' vs 'process-tab-column-widths'.
        """
        from app.auxiliary import getAppLogger
        log = getAppLogger()
        
        # Complete list of ALL valid setting keys by section
        valid_settings = {
            'GeneralSettings': {
                'default-terminal',
                'tool-output-black-background',
                'screenshooter-timeout',
                'web-services',
                'enable-scheduler',
                'enable-scheduler-on-import',
                'max-fast-processes',
                'max-slow-processes',
                'tool-duplication'
            },
            'BruteSettings': {
                'store-cleartext-passwords-on-exit',
                'username-wordlist-path',
                'password-wordlist-path',
                'default-username',
                'default-password',
                'services',
                'no-username-services',
                'no-password-services'
            },
            'ToolSettings': {
                'nmap-path',
                'hydra-path',
                'cutycapt-path',
                'texteditor-path',
                'pyshodan-api-key'
            },
            'StagedNmapSettings': {
                'stage1-ports',
                'stage2-ports',
                'stage3-ports',
                'stage4-ports',
                'stage5-ports',
                'stage6-ports'
            },
            'GUISettings': {
                'process-tab-column-widths',
                'process-tab-detail'
            },
            'HostActions': 'dynamic',  # These have dynamic keys
            'PortActions': 'dynamic',
            'PortTerminalActions': 'dynamic',
            'SchedulerSettings': 'dynamic',
            'MatchSettings': 'dynamic'
        }
        
        errors = []
        lines = config_text.split('\n')
        current_section = None
        
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Skip empty and comments
            if not stripped or stripped.startswith('#') or stripped.startswith(';'):
                continue
            
            # Track current section
            if stripped.startswith('[') and stripped.endswith(']'):
                current_section = stripped[1:-1].strip()
                
                # Check if section itself is valid
                if current_section not in valid_settings:
                    log.warning(f"DEBUG: Line {line_num}: Unknown section '{current_section}'")
                    errors.append(
                        f"⚠️  Line {line_num}: Unknown section [{current_section}]\n"
                        f"   This section is not recognized by Legion.\n"
                        f"   Valid sections: {', '.join(valid_settings.keys())}"
                    )
                continue
            
            # Check key=value pairs
            if '=' in stripped:
                key = stripped.split('=', 1)[0].strip()
                
                if current_section and current_section in valid_settings:
                    expected_keys = valid_settings[current_section]
                    
                    # Skip validation for sections with dynamic keys
                    if expected_keys == 'dynamic':
                        continue
                    
                    # Check if key is in expected set
                    if key not in expected_keys:
                        log.warning(f"DEBUG: Line {line_num}: Invalid key '{key}' in [{current_section}]")
                        
                        # Find similar key names (likely typos)
                        suggestions = []
                        for valid_key in expected_keys:
                            # Simple similarity check: if only 1-2 chars different
                            if abs(len(key) - len(valid_key)) <= 2:
                                # Check character overlap
                                overlap = sum(1 for c in key if c in valid_key)
                                if overlap >= len(key) - 2:
                                    suggestions.append(valid_key)
                        
                        error_msg = f"❌ Line {line_num}: Unknown setting '{key}' in [{current_section}]\n"
                        if suggestions:
                            error_msg += f"   Did you mean: {', '.join(suggestions)}?"
                        else:
                            error_msg += f"   Valid settings in [{current_section}]:\n"
                            for valid_key in sorted(expected_keys):
                                error_msg += f"     • {valid_key}\n"
                        
                        errors.append(error_msg)
        
        log.debug(f"DEBUG:validateSettingNames() found {len(errors)} invalid settings")
        return errors

    def validateConfigSyntax(self, config_text):
        """
        Comprehensive INI validation with element count checking for dynamic sections.
        
        Expected format for each section:
        - HostActions: key=label, command (2 comma-separated elements)
        - PortActions: key=label, command, service (3 comma-separated elements)
        - PortTerminalActions: key=label, command, service (3 comma-separated elements)
        - SchedulerSettings: key=value1, value2 (2 comma-separated elements)
        - MatchSettings: key=csv,list,of,values (variable elements)
        """
        from app.auxiliary import getAppLogger
        log = getAppLogger()
        
        # Define expected element counts for each section type
        section_element_counts = {
            'HostActions': 2,  # label, command
            'PortActions': 3,  # label, command, service
            'PortTerminalActions': 3,  # label, command, service
            'SchedulerSettings': 2,  # value1, value2
            'MatchSettings': None  # Variable - any number of elements
        }
        
        errors = []
        lines = config_text.split('\n')
        current_section = None
        
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Skip empty lines and comments
            if not stripped or stripped.startswith('#') or stripped.startswith(';'):
                continue
            
            # Check for section headers
            if stripped.startswith('['):
                if not stripped.endswith(']'):
                    errors.append(
                        f"❌ Line {line_num}: Unclosed section header\n"
                        f"   Found: {stripped}\n"
                        f"   Fix: Add closing bracket ]"
                    )
                    continue
                
                section_name = stripped[1:-1].strip()
                if not section_name:
                    errors.append(
                        f"❌ Line {line_num}: Empty section header\n"
                        f"   Found: {stripped}\n"
                        f"   Fix: Provide a section name between [ ]"
                    )
                elif ' ' in section_name:
                    errors.append(
                        f"❌ Line {line_num}: Section name contains spaces\n"
                        f"   Found: [{section_name}]\n"
                        f"   Fix: Remove spaces (use CamelCase)"
                    )
                
                current_section = section_name
                log.debug(f"DEBUG:Line {line_num} - Entered section [{current_section}]")
                continue
            
            # Check for key=value pairs
            if '=' in stripped:
                # Extract key and value (split on FIRST equals)
                first_equals_pos = stripped.index('=')
                key = stripped[:first_equals_pos].strip()
                value = stripped[first_equals_pos + 1:].strip()
                
                log.debug(f"DEBUG:Line {line_num} - key: '{key}', value: '{value[:80]}...'")
                
                # Validate key
                if not key:
                    errors.append(
                        f"❌ Line {line_num}: Missing key name before '='\n"
                        f"   Found: {stripped}\n"
                        f"   Fix: Add a key name: key=value"
                    )
                    continue
                
                if '=' in key:
                    errors.append(
                        f"❌ Line {line_num}: Key contains '=' sign\n"
                        f"   Found key: {key}\n"
                        f"   Fix: Key name cannot contain '=' character"
                    )
                    continue
                
                if key.startswith('[') or key.endswith(']'):
                    errors.append(
                        f"❌ Line {line_num}: Key name contains brackets\n"
                        f"   Found: {key}\n"
                        f"   Fix: Did you mean to create a [SectionHeader]?"
                    )
                    continue
                
                # QUOTE VALIDATION - Check for unclosed quotes
                quote_errors = self.validateQuotes(value, line_num, key)
                if quote_errors:
                    errors.extend(quote_errors)
                    continue  # Skip element count check if quotes are broken
                
                # ELEMENT COUNT VALIDATION for dynamic sections
                if current_section and current_section in section_element_counts:
                    expected_count = section_element_counts[current_section]
                    
                    if expected_count is not None:  # None means variable count allowed
                        # Parse comma-separated elements, respecting quoted strings
                        elements = self.parseCommaSeparated(value)
                        actual_count = len(elements)
                        
                        log.debug(f"DEBUG:Line {line_num} - Section [{current_section}]: "
                                f"expected {expected_count} elements, found {actual_count}")
                        
                        if actual_count != expected_count:
                            errors.append(
                                f"❌ Line {line_num}: Wrong number of elements in [{current_section}]\n"
                                f"   Key: {key}\n"
                                f"   Expected: {expected_count} comma-separated elements\n"
                                f"   Found: {actual_count} elements\n"
                                f"   Value: {value}\n"
                                f"   Fix: Ensure value has exactly {expected_count} comma-separated parts"
                            )
                
                # Check if key-value pair is inside a section
                if current_section is None:
                    errors.append(
                        f"❌ Line {line_num}: Key-value pair outside of any section\n"
                        f"   Found: {stripped}\n"
                        f"   Fix: Add a [SectionName] header before this line"
                    )
            else:
                # No equals sign found
                log.warning(f"DEBUG: Line {line_num} has NO '=' sign: '{stripped}'")
                errors.append(
                    f"❌ Line {line_num}: Invalid syntax - missing '=' sign\n"
                    f"   Found: {stripped}\n"
                    f"   Fix: Lines must be [Section], key=value, or comment (#)"
                )
        
        log.debug(f"DEBUG:validateConfigSyntax() found {len(errors)} syntax errors")
        return errors

    def validateQuotes(self, value, line_num, key):
        """
        Validate that quotes are properly balanced and closed.
        Returns list of error messages if invalid.
        """
        errors = []
        
        # Check for unbalanced double quotes
        double_quote_count = value.count('"')
        if double_quote_count % 2 != 0:
            errors.append(
                f"❌ Line {line_num}: Unclosed double quote (\") in value\n"
                f"   Key: {key}\n"
                f"   Value: {value}\n"
                f"   Fix: Close all double quotes - found {double_quote_count} quotes (should be even)"
            )
        
        # Check for unbalanced single quotes
        single_quote_count = value.count("'")
        if single_quote_count % 2 != 0:
            errors.append(
                f"❌ Line {line_num}: Unclosed single quote (') in value\n"
                f"   Key: {key}\n"
                f"   Value: {value}\n"
                f"   Fix: Close all single quotes - found {single_quote_count} quotes (should be even)"
            )
        
        # Check for mixed quote types (opening with one, closing with another)
        # This is a basic check - looks for common patterns
        if (value.count('"') > 0 and value.count("'") > 0):
            # Check if there's a pattern like "text' or 'text"
            import re
            mixed_quote_pattern = r'''["'][^"']*['"]'''
            if re.search(mixed_quote_pattern, value):
                # This might be intentional (quoted string containing other quotes)
                # Only warn if it looks suspicious
                pass
        
        return errors

    def parseCommaSeparated(self, value):
        """
        Parse comma-separated values, treating quoted strings as single elements.
        
        CRITICAL: Commas inside quotes do NOT count as separators!
        
        Examples (correct behavior):
            'Launch dirbuster, /usr/bin/dirbuster, "http,https,ssl"' → 3 elements
            'Run enum4linux, enum4linux [IP], "netbios-ssn,microsoft-ds"' → 3 elements
            
        Elements are:
            1. Everything before first comma (outside quotes)
            2. Everything before second comma (outside quotes)  
            3. The quoted string "http,https,ssl" (ONE element despite internal commas)
        """
        import re
        from app.auxiliary import getAppLogger
        log = getAppLogger()
        
        elements = []
        current_element = []
        in_quotes = False
        quote_char = None
        
        i = 0
        while i < len(value):
            char = value[i]
            
            # Check for quote characters
            if char in ['"', "'"]:
                if not in_quotes:
                    # Starting a quoted section
                    in_quotes = True
                    quote_char = char
                    current_element.append(char)
                elif char == quote_char:
                    # Ending the quoted section (matching quote)
                    in_quotes = False
                    quote_char = None
                    current_element.append(char)
                else:
                    # Different quote type inside quoted string
                    current_element.append(char)
            
            # Check for comma separator
            elif char == ',':
                if in_quotes:
                    # Comma inside quotes - part of the value, NOT a separator
                    current_element.append(char)
                else:
                    # Comma outside quotes - this is a separator
                    element_text = ''.join(current_element).strip()
                    elements.append(element_text)
                    current_element = []
            
            else:
                # Regular character
                current_element.append(char)
            
            i += 1
        
        # Don't forget the last element
        if current_element:
            element_text = ''.join(current_element).strip()
            elements.append(element_text)
        
        log.debug(f"DEBUG:Parsed {len(elements)} elements from value")
        for idx, elem in enumerate(elements, 1):
            preview = elem[:80] + '...' if len(elem) > 80 else elem
            log.debug(f"DEBUG:  Element {idx}: '{preview}'")
        
        return elements




