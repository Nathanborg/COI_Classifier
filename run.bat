@echo off
REM Double-click this file to launch the COI Classifier.
cd /d "%~dp0"
python coi_classifier.py
if errorlevel 1 pause
