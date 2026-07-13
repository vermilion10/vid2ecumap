#!/usr/bin/env bash
set -e
pyinstaller --onefile --windowed --name ECU_Mapper_RT app.py
echo "Done. Binary at dist/ECU_Mapper_RT"
