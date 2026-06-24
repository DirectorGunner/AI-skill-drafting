@echo off
rem Thin launcher for skill_policy.py (Windows). Passes all args through.
rem Default action is read-only `audit`. See: python skill_policy.py -h
python "%~dp0skill_policy.py" %*
