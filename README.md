# ECU Mapper RT

<img width="1802" height="934" alt="image" src="https://github.com/user-attachments/assets/052543eb-1288-43fa-ab2d-c1046d8d37ee" />

ECU Mapper RT is a Qt-based desktop application that transforms local video files into real-time, adjustable color-heatmap "tuning tables" featuring live 2D and 3D surface graphs. The user interface is modeled after classic ECU calibration software (such as SXTune and TunerPro), featuring a traditional ECU navigation tree, tab strip, icon toolbar, side-by-side map table and 3D surface plot, 2D multi-line graph, Live Data panel, and a status bar.

All video processing is performed 100% locally on your machine. No video files are bundled with the application, and no data is uploaded externally.

---

## Installation & Running from Source

This method runs the application directly via Python and does not require compilation.

### Prerequisites

* Python 3.10 or higher 

### Execution Steps

1. Open a terminal or Command Prompt in the project root directory.
2. Install the dependencies and run the application:

```bash
pip install -r requirements.txt
python app.py

```

---

## Building Standalone Binaries

To generate a standalone executable that runs without a Python installation, use PyInstaller.

### Windows

```cmd
pip install -r requirements.txt pyinstaller
build.bat

```

The standalone executable `ECU_Mapper_RT.exe` will be generated in the `dist\` directory.

### macOS / Linux

```bash
pip install -r requirements.txt pyinstaller
chmod +x build.sh
./build.sh

```

The standalone binary will be generated in the `dist/` directory.

**Note for Linux Users:** A pre-built Linux binary (`ECU_Mapper_RT`) is included in this package (not yet). You can run it directly using:

> ```bash
> chmod +x ECU_Mapper_RT && ./ECU_Mapper_RT
> 
> ```


If the system reports a missing `libxcb-cursor` dependency, resolve it by installing it using your package manager

---

## User Guide & Features

1. **Video Input:** Load a local video file via **File > Open Video...** or by clicking the folder icon in the toolbar.
2. **Playback Controls:** The green (Start), amber (Pause), and red (Stop/Reset) toolbar icons function as playback controls styled after calibration toggles. Tooltips are available on hover.
3. **ECU Navigation Tree (Left Panel):** Provides an authentic ECU parameter hierarchy. The active nodes wired to real-time video data processing include:
* Main Injection Quantity
* Main Spark Advance
* AFR Target Map
* Boost Control
* Fuel Correction Factors
* Ignition Correction Factors\
*(Other nodes serve as visual placeholders).*


4. **Data Visualization:** The Map Table and 3D Graph update simultaneously in real-time. The 2D Graph below plots each row of the grid as an individual colored line reflecting live video frames.
5. **Graph Resolution:** The Zoom slider (far right of the toolbar) adjusts the resolution of the 2D and 3D graphs independently of the table grid.
6. **Color Palettes:** The three colored square icons next to the zoom slider switch the table palette between **Pastel**, **Vivid**, and **Thermal** modes.
7. **Table Adjustments:** The `+`, `−`, `*`, and `0` icons allow you to nudge contrast, invert polarity, and reset values, replicating real calibration tool table-editing shortcuts.
8. **Configuration:** Navigate to **Tools > Settings...** to adjust grid dimensions (up to 400×400 columns/rows), toggle aspect-ratio lock, and show/hide cell values or axis headers.
9. **Live Data:** The **Live Data** panel (right) and the **Site Target** gauge simulate real-time engine sensor diagnostics driven by the video's luminance and motion data.

---

## Performance & Technical Notes

The luminance grid is computed using OpenCV's `cv2.resize(..., INTER_AREA)` function to ensure high-quality area-averaging downsampling.

Increasing the column and row count yields smooth, continuous gradient profiles rather than pixelated subdivisions. At very high resolutions (e.g., 200×150 and above), the display transitions from a distinct data grid into a highly fluid, thermal-camera-style representation of the video feed.

---

## Project Structure

* `app.py` – Main application source code.
* `requirements.txt` – Required Python packages.
* `build.bat` / `build.sh` – Automated build scripts for PyInstaller execution.
* `dist/` – Output directory for compiled binaries and standalone executables.
