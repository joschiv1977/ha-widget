\# Home Assistant 3D Printer Widget



Ein modernes Desktop-Widget für Windows, das Home Assistant 3D-Drucker Daten und Bambu Lab MQTT-Verbindung kombiniert.



\## Features

\- 🏠 Home Assistant Integration

\- 📡 Bambu Lab 3D-Drucker MQTT

\- 📹 Live Kamerastream mit variabler Größe

\- 📊 Echtzeitanzeige aller Druckerdaten

\- 💡 Lichtsteuerung

\- 🎨 Modernes dunkles Design

\- ⚙️ Konfiguration über GUI



\## Installation

Python direkt bei https://www.python.org/downloads/ laden oder über den Microsoft Store.

\### Abhängigkeiten

```bash

pip install tkinter pillow requests paho-mqtt

\## .exe Datei erstellen

pyinstaller --onedir --windowed --icon=icon.ico ha-widget.py

