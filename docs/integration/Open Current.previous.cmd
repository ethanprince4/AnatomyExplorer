@echo off
rem Opens whichever worktree in Worktrees\ was checked out or committed to most recently.
start "" "%~dp0Workspace\runtime\pythonw.exe" "%~dp0Workspace\launch_current.py"
