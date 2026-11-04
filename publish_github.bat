@echo off
rem Upload this folder (with version history and tags) to a new GitHub repo in YOUR account.
rem   publish_github.bat            -> private repo (not searchable, only you can open it)
rem   publish_github.bat public     -> public repo (anyone with the URL can open it; GitHub search can find it)
rem Needs git and the GitHub CLI (https://cli.github.com).
cd /d "%~dp0"
set VIS=%1
if "%VIS%"=="" set VIS=private
set NAME=mscw-market-watcher
where gh >nul 2>nul || (echo Install the GitHub CLI first: https://cli.github.com & pause & exit /b 1)
gh auth status >nul 2>nul || gh auth login
gh repo create %NAME% --%VIS% --source . --remote origin --push || (pause & exit /b 1)
git push origin --tags
gh repo view %NAME% --json url -q .url
pause
