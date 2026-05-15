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

"""Test helper — creates Flask app + WebController without upstream dependencies."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)


def create_test_app(enable_scheduler=False):
    """Create Flask app wired to WebController. Same setup as legion.py --web.

    enable_scheduler=False (default): disables the automatic tool scheduler so
    background processes don't race against project-switch operations (new-temp,
    save-as, open) in tests that cycle through projects.  Pass True for live-scan
    tests that rely on the scheduler to trigger the screenshooter automatically.
    """
    from flask import Flask
    from app.shell.DefaultShell import DefaultShell
    from db.RepositoryFactory import RepositoryFactory
    from app.ProjectManager import ProjectManager
    from app.tools.ToolCoordinator import ToolCoordinator
    from app.tools.nmap.DefaultNmapExporter import DefaultNmapExporter
    from app.logic import Logic
    from app.settings import AppSettings, Settings
    from app.logging.legionLog import getDbLogger, getAppLogger
    from controller.web_controller import WebController
    from app.web.routes import web_bp

    shell = DefaultShell()
    dbLog = getDbLogger()
    appLog = getAppLogger()
    repoFactory = RepositoryFactory(dbLog)
    pm = ProjectManager(shell, repoFactory, appLog)
    nmapExporter = DefaultNmapExporter(shell, appLog)
    tc = ToolCoordinator(shell, nmapExporter)
    logic = Logic(shell, pm, tc)
    logic.createNewTemporaryProject()

    settings = Settings(AppSettings())
    wc = WebController(logic, settings)

    if not enable_scheduler:
        # Disable scheduler so seeding a test host doesn't spawn real background
        # tool processes (nikto, whatweb, gobuster, etc.) that race against the
        # test's project-switch operations (new-temp, save-as, open) and cause
        # "no such table" SQLite errors when they land on a transitioning engine.
        #
        # Two-layer approach:
        #
        # Layer 1: patch applySettings() so that whenever the config-save tests
        # call POST /api/settings/legion-conf (which reloads Settings(AppSettings())
        # from disk and would overwrite the False with the conf's "True"), we
        # re-apply the override immediately after the reload.
        import types as _types
        _orig_apply = wc.applySettings.__func__
        def _apply_no_scheduler(self_wc):
            _orig_apply(self_wc)
            self_wc.settings.general_enable_scheduler = False
        wc.applySettings = _types.MethodType(_apply_no_scheduler, wc)
        wc.settings.general_enable_scheduler = False


    wc.start()

    app = Flask(__name__,
                template_folder=os.path.join(PROJECT_ROOT, 'app/web/templates'),
                static_folder=os.path.join(PROJECT_ROOT, 'app/web/static'))
    app.config['TESTING'] = True
    app.config['LEGION_WC'] = wc
    app.config['LEGION_LOGIC'] = logic
    app.register_blueprint(web_bp)

    return app, logic, wc
