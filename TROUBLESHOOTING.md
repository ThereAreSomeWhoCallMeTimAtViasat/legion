# Troubleshooting Checklist

## Current Tasks

- [x] output from tool tabs that run with bash or msfconsole is not saved to database

- [x] on save and reload of data, the reloaded data in the qtextedit is formated as text, not the html that was presented.  do we need to save the data to the db differently?

- [ ] window resize is not being saved

- [x] cve data is not being reloaded from a db save

- [x] script data is not being reloaded from a db save

- [ ] notes need to be saved in the db and restored from the db as html

- [ ] file->open seeing some errors:  Error creating proxy: Unknown or unsupported transport “disabled” for address “disabled:” (g-io-error-quark, 13)

(python:6298): dconf-WARNING **: 08:48:30.044: failed to commit changes to dconf: Unknown or unsupported transport “disabled” for address “disabled:”

- [ ] orange flash from ctrl+B does not return the background to default in msfconsole...background stays orange now...

- [ ] stty: 'standard input': Inappropriate ioctl for device from the msfconsole now?

- [ ] right click run does not put msfconsole in a terminal...still qtextedit

- [ ] terminal portactions are not added to tools tab table list

- [x] blinking cursor in terminal does not allow scroll

- [x] double terminaltabs one blank one with data  WARNING  No dbId found for tab being closed; skipping DB status update.

- [ ] lets be smarter on the service and the version before running a port action

- [ ] splitter_2 for hosts not saving and restoring.

- [ ] check different splitter 2 for different tabs

- [ ] pylance type checking is turned off...when turned on it shows a lot of errors.  do I need to fix this stuff?

- [ ] when os tab selected not all the tabs come over in that view...sometimes just services, sometimes all the static tabs.  is this a feature?

- [ ] turn debug logging on and off in settings to avoid the file getting too big from all the data

- [ ] change some log.info back to log.debug (when done with hanging errors on exit)

- [ ] ~/.local/share/legion/ profiles and backups are here i think...move to cwd?

- [ ] /root/.local/legion/ profiles and backups are here now i think...move to cwd?  have to resolve this eventually...if we have to run as sudo why would the profiles be anywhere else?

- [ ] add a ports tab for multihost similar to OS tab maybe?  I added a ports colunm to services...this might be good enough for now.

- [ ] test multihost functionality

- [ ] why are duplicate runs happening? maybe because vulners looks for duplicate ports...

- [ ] move vulners to a script that runs in another process, not the nmap process, so nmap can continue.  or put vulners to the end?

## Completed Tasks

- [x] moved time-legion.conf to backup folder

- [x]  cves does not reload for different hosts

- [x] scripts middle window clears but right window still shows data

- [x] matching does not work now for some reason...no matchSettings in legion.conf

- [x] too many legion.bak and saves being made  try to get it in backup folder

- [x] move from /root/.cache/legion/log to running folder /log
- [x] fixed view.py for log-directory get

- [x] ui does not remember changes to widths between tab clicks

- [x] fix the tools lists for ->2 instead of -2

- [x] notes dont stay with the host when host is unselecteded and selected again (unselect host in host tab, click on tools, back to hosts, no notes...)

- [x] with only one entry in hosts table, it should never be allowed to be unselected. ctrl a did it somehow...

- [x] exploitdb columns in cves data?

- [x] multiple tabs for multiple versions of legion.conf files

- [x] does writing log files even work?  yes at /root/.cache/legion
- [x] log level filter on gui like for processes

- [x] services to hosts tab click should only blink the services tab if there is a change to the services data...not everytime.

- [x] no tools for ccproxy-ftp on 2121 but it is queued up on debug output

- [x]  put in ctrl+B
- [x]  get html paste into notestextedit
- [x]  update formatting for ctrl b
- [x]  allow ctrl b from displaywidget

- [x]  valid pair found, valid password found not working now?

- [x]  does watching the log still cause a crash?
- [x]  log lost /n/r?

- [x]  add something that tells user ctrl b did copy to notes tab...

- [x]  right click to start a tool causes crash?

- [x]  tools does not delete when host deleted

- [x]  nmap stage1 not red on match but others are...

- [x]  clean up output because vulners is too loud

- [x]  control b should work on scripts?

- [x]  control b to work on row selection?  low priority

- [x]  does purge work? it does now.

- [x] fix non showing first entry in append mode on toolhoststableview

- [x] nmap stages are not deduped properly after append dedup change

- [x] suspect save and load settings needs to be updated with changes to legion.conf 
- [x] save legion.conf when changes made via gui with error and syntax checking

- [x] get rid of identical cves in the table.  sort by cvss score, cve id, check product, version, url

- [x] services to hosts tab clears orange on information?
- [x] check orange implementation on information again...it is just not turning orange at all...
- [x] check orange implemetation on notes again...it loses orange when it had unread notes on scripts or cves updates

- [x] fix dedup so that new output is appended instead of ignoring the run again

- [x]  information tab is not cleared on delete

- [x]  on delete and then scan of same ip, not all the processes are displayed again in the processestableview

- [x]  finished process on the host are not cleaned up in the processtable after a delete

- [x]  fix smbenum...turns out it did not exist.

- [x]  change cve's tab to red after they are discovered.
- [x]  make diff red on information tab
- [x]  cves should sort by cvss score with highest at top

- [x]  when orange font is present, clicking on one of those tabs like notes and then clicking on tools and back to hosts the orange of notes goes away

- [x] random window not exiting when clicking on upper right corner x
 - [x] QFontDatabase: Must construct a QGuiApplication before accessing QFontDatabase zsh: IOT instruction  sudo python legion.py
 - [x]  clean up tmp file removal.

- [x]  update port in tooltableview for stage or port with nmap
- [x]  update name column font color in tools tab when there is a match
- [x]  add a debug switch to cleanup output after troubleshooting.

- [x]  timer is not updating every second anymore...not sure when that started happening

- [x]  legion.conf not saving matchSettings after update and shutdown after processes are running.
- [x]  make the port font red if match is found in toolHostsTableView port column


- [x]  smbenum had no output on either view.  tried to rerun it from services tab.  crash.

## Notes
qt.qpa.xcb could not connect to display 1
xhost xi:localuser:root

