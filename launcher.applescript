-- Beat Uploader launcher — source of "Beat Uploader.app".
--
-- Stay-open applet: starts the local web GUI in the background, sits in the
-- Dock while the server runs, and quits itself when the server stops (quit
-- link, tab closed with an empty queue, ...). Quitting from the Dock stops
-- the server too, after asking if beats are still processing.
--
-- Rebuild after editing (from the project folder):
--   osacompile -o "Beat Uploader.app/Contents/Resources/Scripts/main.scpt" launcher.applescript
--   codesign --force --deep --sign - "Beat Uploader.app"
-- The bundle's Info.plist must keep OSAAppletStayOpen = true.

on pidFile()
	return (POSIX path of (path to library folder from user domain)) & "Caches/BeatUploader.pid"
end pidFile

on run
	set appPath to POSIX path of (path to me)
	do shell script "PROJECT_DIR=$(dirname " & quoted form of appPath & "); cd \"$PROJECT_DIR\" || exit 1; PY=\"$HOME/miniconda3/bin/python\"; [ -x \"$PY\" ] || PY=$(command -v python3); LOG=\"$HOME/Library/Logs/BeatUploader.log\"; echo \"── $(date) launching with $PY ──\" >> \"$LOG\"; nohup \"$PY\" -u gui.py >> \"$LOG\" 2>&1 < /dev/null & echo $! > " & quoted form of pidFile()
end run

-- Clicking the Dock icon again re-opens the page
on reopen
	do shell script "open http://127.0.0.1:8765"
end reopen

on idle
	if not serverAlive() then quit
	return 3
end idle

on quit
	if serverAlive() then
		set busy to "0"
		try
			set busy to do shell script "curl -s -m 2 http://127.0.0.1:8765/api/busy || echo 0"
		end try
		if busy is not "0" and busy is not "" then
			try
				display dialog busy & " beat(s) still processing. Quitting cancels them." buttons {"Keep Running", "Quit Anyway"} default button "Keep Running" with title "Beat Uploader" with icon caution
				if button returned of result is "Keep Running" then return
			on error number -128
				return
			end try
		end if
		try
			-- Ask nicely, give the render/upload up to 20s to clean up, then SIGTERM
			do shell script "P=$(cat " & quoted form of pidFile() & "); curl -s -m 2 -X POST http://127.0.0.1:8765/api/quit > /dev/null; for i in $(seq 40); do ps -p $P -o command= | grep -q gui.py || exit 0; sleep 0.5; done; kill $P 2>/dev/null; true"
		end try
	end if
	continue quit
end quit

on serverAlive()
	try
		-- PID files go stale; make sure it's still *our* server, not a reused PID
		do shell script "ps -p $(cat " & quoted form of pidFile() & ") -o command= | grep -q gui.py"
		return true
	on error
		return false
	end try
end serverAlive
