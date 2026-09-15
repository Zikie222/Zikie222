@echo off
cd /d "%~dp0"

python -m coverage run --branch -m unittest discover -s tests -v

echo.
python -m coverage report -m

echo.
python -m coverage html

echo.
echo Coverage report generated: htmlcov\index.html
pause
