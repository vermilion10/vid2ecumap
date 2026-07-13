@echo off
pyinstaller --onefile --windowed --name ECU_Mapper_RT app.py
echo Done. Executable at dist\ECU_Mapper_RT.exe
