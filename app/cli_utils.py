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
import sys
import subprocess
from db.entities.host import hostObj

def import_targets_from_textfile(session, hostRepository, filename):
    """
    Import targets (hostnames, subnets, IPs, etc.) from a text file into the database.
    Each line is treated as a target.
    """
    added = 0
    try:
        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            for line_number, line in enumerate(f, 1):
                target = line.strip()
                if not target or target.startswith("#"):
                    continue
                try:
                    db_host = hostRepository.getHostInformation(target)
                except Exception as repo_exc:
                    print(
                        f"Warning: unable to check existing host '{target}' ({filename}:{line_number}): {repo_exc}",
                        file=sys.stderr
                    )
                    continue
                if db_host:
                    continue
                hid = hostObj(ip=target, ipv4=target, ipv6='', macaddr='', status='', hostname=target,
                              vendor='', uptime='', lastboot='', distance='', state='', count='')
                try:
                    session.add(hid)
                    session.commit()
                    added += 1
                except Exception as db_exc:
                    session.rollback()
                    print(
                        f"Error importing target '{target}' ({filename}:{line_number}): {db_exc}",
                        file=sys.stderr
                    )
    except FileNotFoundError:
        print(f"Error: input file '{filename}' not found.", file=sys.stderr)
        return 0
    except OSError as exc:
        print(f"Error opening input file '{filename}': {exc}", file=sys.stderr)
        return added
    return added

def is_wsl():
    try:
        with open('/proc/version', 'r') as f:
            return 'Microsoft' in f.read()
    except Exception:
        return False

def to_windows_path(path):
    try:
        import subprocess
        return subprocess.check_output(['wslpath', '-w', path]).decode().strip()
    except Exception:
        # Fallback: naive conversion for /mnt/c/...
        if path.startswith('/mnt/'):
            drive = path[5]
            rest = path[6:]
            rest_win = rest.replace('/', '\\')
            return f"{drive.upper()}:\\{rest_win}"
        return path

def run_nmap_scan(targets, output_prefix, discovery=True, staged=False, nmap_path="nmap"):
    """
    Run nmap scan on the given targets.
    - targets: string of targets (space/comma separated)
    - output_prefix: path prefix for nmap output files
    - discovery: if True, enable host discovery; if False, use -Pn
    - staged: if True, run a staged scan (simple implementation: run a basic scan, then a service scan)
    Returns the path to the main nmap XML output.
    """
    # Convert output_prefix to Windows path if running under WSL and using nmap.exe
    def convert_if_needed(prefix):
        if is_wsl() and nmap_path.lower().endswith('.exe'):
            return to_windows_path(prefix)
        return prefix

    if staged:
        # Example staged: first a fast scan, then a service scan
        # Stage 1: host discovery
        output_prefix1 = output_prefix + "_stage1"
        output_prefix1_conv = convert_if_needed(output_prefix1)
        cmd1 = [nmap_path, "-sn"] + targets.split() + ["-oA", output_prefix1_conv]
        try:
            subprocess.run(cmd1, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"Error running nmap stage 1: {e}", file=sys.stderr)
            return None
        # Stage 2: service/version scan on discovered hosts (for demo, just rerun on all)
        output_prefix2 = output_prefix + "_stage2"
        output_prefix2_conv = convert_if_needed(output_prefix2)
        cmd2 = [nmap_path, "-sV", "-O"] + targets.split() + ["-oA", output_prefix2_conv]
        if not discovery:
            cmd2.insert(1, "-Pn")
        try:
            subprocess.run(cmd2, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"Error running nmap stage 2: {e}", file=sys.stderr)
            return None
        return output_prefix + "_stage2.xml"
    else:
        output_prefix_conv = convert_if_needed(output_prefix)
        cmd = [nmap_path]
        if not discovery:
            cmd.append("-Pn")
        cmd += ["-T4", "-sV", "-O"] + targets.split() + ["-oA", output_prefix_conv]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"Error running nmap: {e}", file=sys.stderr)
            return None
        return output_prefix + ".xml"

# ── Config migration ─────────────────────────────────────────────────────────

def _read_conf_version(parser):
    try:
        return int(parser.get('GeneralSettings', 'config_version'))
    except Exception:
        return 0


def check_conf_version(user_path, master_path):
    """Compare config_version between user conf and master.
    Returns (user_ver, master_ver) tuple.  Missing key = 0."""
    import configparser
    up = configparser.RawConfigParser()
    up.optionxform = str
    up.read(user_path, encoding='utf-8')
    mp = configparser.RawConfigParser()
    mp.optionxform = str
    mp.read(master_path, encoding='utf-8')
    return _read_conf_version(up), _read_conf_version(mp)


def migrate_conf(user_path, master_path, dry_run=False):
    """Merge missing sections/keys from master into user conf without overwriting.

    Returns dict with migration results:
      up_to_date   : bool  — True if no migration needed
      backed_up    : str|None — path to backup file (None if dry_run or up_to_date)
      sections_added : list of section names added
      keys_added   : dict {section: [key, ...]} for keys added to existing sections
      user_version : int
      master_version : int
    """
    import configparser
    import shutil

    up = configparser.RawConfigParser()
    up.optionxform = str
    up.read(user_path, encoding='utf-8')

    mp = configparser.RawConfigParser()
    mp.optionxform = str
    mp.read(master_path, encoding='utf-8')

    u_ver = _read_conf_version(up)
    m_ver = _read_conf_version(mp)

    result = {
        'up_to_date': u_ver >= m_ver,
        'backed_up': None,
        'sections_added': [],
        'keys_added': {},
        'user_version': u_ver,
        'master_version': m_ver,
    }

    if u_ver >= m_ver:
        return result

    sections_added = []
    keys_added = {}

    for section in mp.sections():
        if not up.has_section(section):
            sections_added.append(section)
            if not dry_run:
                up.add_section(section)
                for key, val in mp.items(section):
                    up.set(section, key, val)
        else:
            added_in_section = []
            for key, val in mp.items(section):
                if not up.has_option(section, key):
                    added_in_section.append(key)
                    if not dry_run:
                        up.set(section, key, val)
            if added_in_section:
                keys_added[section] = added_in_section

    if not dry_run:
        up.set('GeneralSettings', 'config_version', str(m_ver))

    result['sections_added'] = sections_added
    result['keys_added'] = keys_added

    if dry_run:
        return result

    backup_dir = os.path.expanduser('~/.local/share/legion/backup')
    os.makedirs(backup_dir, exist_ok=True)
    from app.timing import getTimestamp
    backup_path = os.path.join(backup_dir, f'pre-migrate-{getTimestamp()}.conf')
    shutil.copy(user_path, backup_path)
    result['backed_up'] = backup_path

    with open(user_path, 'w', encoding='utf-8') as f:
        up.write(f)

    _inject_master_comments(user_path, master_path)

    return result


def _inject_master_comments(target_path, master_path):
    """Re-inject comment blocks from master conf into a file written by
    configparser (which strips all comments).

    For each [Section] in the master, extracts the comment lines between
    the section header and the first key, then inserts them into the
    target file after the matching section header."""
    import re
    with open(master_path, 'r', encoding='utf-8') as f:
        master_text = f.read()
    with open(target_path, 'r', encoding='utf-8') as f:
        target_text = f.read()

    for m in re.finditer(r'(\[([^\]]+)\]\n)((?:#[^\n]*\n|\n)*)', master_text):
        header = m.group(1)
        section = m.group(2)
        comments = m.group(3)
        if not comments.strip():
            continue
        target_header = f'[{section}]\n'
        if target_header in target_text:
            target_text = target_text.replace(target_header, target_header + comments, 1)

    with open(target_path, 'w', encoding='utf-8') as f:
        f.write(target_text)


def migrate_profiles(master_path):
    """Merge missing keys into shipped profiles that have a stale config_version.
    Returns list of profile filenames that were migrated."""
    import configparser
    profiles_dir = os.path.expanduser('~/.local/share/legion/profiles')
    shipped_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'profiles')
    migrated = []

    if not os.path.isdir(profiles_dir) or not os.path.isdir(shipped_dir):
        return migrated

    shipped_names = {fn for fn in os.listdir(shipped_dir) if fn.endswith('.conf')}

    for fn in os.listdir(profiles_dir):
        if fn not in shipped_names:
            continue
        user_prof = os.path.join(profiles_dir, fn)
        shipped_prof = os.path.join(shipped_dir, fn)
        u_ver, s_ver = check_conf_version(user_prof, shipped_prof)
        if u_ver < s_ver:
            r = migrate_conf(user_prof, shipped_prof)
            if not r['up_to_date']:
                migrated.append(fn)

    return migrated


def print_migration_summary(result, profiles=None):
    """Print a human-readable summary of migration results."""
    if result['up_to_date']:
        print("  Config is up to date (version %d)." % result['user_version'])
        return

    print(f"  Migrated config: version {result['user_version']} → {result['master_version']}")
    if result.get('backed_up'):
        print(f"  Backup saved to: {result['backed_up']}")
    if result['sections_added']:
        print(f"  Sections added: {', '.join(result['sections_added'])}")
    total_keys = sum(len(v) for v in result['keys_added'].values())
    if total_keys:
        for section, keys in result['keys_added'].items():
            print(f"  {section}: +{len(keys)} new entries")
    if profiles:
        print(f"  Profiles updated: {', '.join(profiles)}")
