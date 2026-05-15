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

from db.SqliteDbAdapter import Database
from six import u as unicode
from db.entities.note import note

class NoteRepository:
    def __init__(self, dbAdapter: Database, log):
        self.dbAdapter = dbAdapter
        self.log = log

    def getNoteByHostId(self, hostId):
        """
        Get note by numeric host ID.
        Returns note object or None if not found.

        FIXED: Uses scoped_session instead of creating new session
        """
        if hostId is None:
            self.log.debug("getNoteByHostId called with None - returning None")
            return None

        try:
            hostId = int(hostId)
        except (ValueError, TypeError):
            self.log.error(f"Invalid hostId: {hostId} - must be an integer")
            return None

        # Use scoped session - returns same session per thread
        session = self.dbAdapter.session

        try:
            result = session.query(note).filter_by(hostId=int(hostId)).first()
            if result:
                self.log.debug(f"getNoteByHostId({hostId}) -> Found note, length={len(result.text)}")
            else:
                self.log.debug(f"getNoteByHostId({hostId}) -> Not found")
            return result
        except Exception as e:
            self.log.error(f"Error getting note for hostId {hostId}: {e}")
            session.rollback()
            return None

    def storeNotes(self, hostId, notes):
        """
        Store notes using numeric host ID.

        FIXED: Query and update within same scoped session to avoid detached objects.
        This ensures the note object remains attached to the session throughout the operation.
        """
        # Handle None hostId gracefully
        if hostId is None:
            self.log.debug("storeNotes called with None hostId - skipping (no host selected)")
            return

        # Ensure hostId is an integer
        try:
            hostId = int(hostId)
        except (ValueError, TypeError):
            self.log.warning(f"Invalid hostId: {hostId} - must be an integer, skipping")
            return

        if len(notes) == 0:
            notes = unicode("")

        # Use scoped session - returns same session per thread
        session = self.dbAdapter.session

        try:
            self.log.debug(f"storeNotes: hostId={hostId}, notes length={len(notes)}")

            # CRITICAL FIX: Query within THIS scoped session
            # Do NOT call getNoteByHostId() which might use a different session
            t_note = session.query(note).filter_by(hostId=int(hostId)).first()

            if t_note:
                # Update existing note - object is attached to this session
                old_length = len(t_note.text)
                t_note.text = unicode(notes)
                self.log.debug(f"Updated existing note for hostId={hostId} (old length={old_length}, new length={len(notes)})")
            else:
                # Create new note and add to session
                t_note = note(hostId, unicode(notes))
                session.add(t_note)
                self.log.debug(f"Created new note for hostId={hostId}, length={len(notes)}")

            # Commit the transaction
            session.commit()
            self.log.debug(f"✓ Successfully committed notes for hostId={hostId}, length={len(notes)}")

        except Exception as e:
            self.log.error(f"✗ Error storing notes for hostId {hostId}: {e}")
            session.rollback()
            raise

    def deleteNote(self, hostId):
        """
        Delete note by host ID

        FIXED: Uses scoped session for consistency
        """
        if hostId is None:
            return

        try:
            hostId = int(hostId)
        except (ValueError, TypeError):
            self.log.error(f"Invalid hostId: {hostId} - must be an integer")
            return

        session = self.dbAdapter.session

        try:
            t_note = session.query(note).filter_by(hostId=int(hostId)).first()
            if t_note:
                session.delete(t_note)
                session.commit()
                self.log.info(f"Deleted note for hostId={hostId}")
            else:
                self.log.debug(f"No note to delete for hostId={hostId}")
        except Exception as e:
            self.log.error(f"Error deleting note for hostId {hostId}: {e}")
            session.rollback()
            raise
