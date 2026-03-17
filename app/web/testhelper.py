"""Test helper — creates Flask app + WebController without upstream dependencies."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)


def create_test_app():
    """Create Flask app wired to WebController. Same setup as legion.py --web."""
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
    wc.start()

    app = Flask(__name__,
                template_folder=os.path.join(PROJECT_ROOT, 'app/web/templates'),
                static_folder=os.path.join(PROJECT_ROOT, 'app/web/static'))
    app.config['TESTING'] = True
    app.config['LEGION_WC'] = wc
    app.config['LEGION_LOGIC'] = logic
    app.register_blueprint(web_bp)

    return app, logic, wc
