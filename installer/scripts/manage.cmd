@echo off
rem Production ayarlarıyla manage.py çalıştırır. Örnek: manage.cmd backup
setlocal
set DJANGO_SETTINGS_MODULE=config.settings.prod
set PYTHONUTF8=1
cd /d "%~dp0..\app"
"%~dp0..\python\python.exe" manage.py %*
exit /b %ERRORLEVEL%
