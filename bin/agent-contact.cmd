@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agent-contact.ps1" %*
