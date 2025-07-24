#!/usr/bin/env python3
"""
Home Assistant 3D Printer Widget
Copyright (C) 2025 [joschiv]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import requests
import threading
import time
from PIL import Image, ImageTk
import io
from tkinter import font
import paho.mqtt.client as mqtt
import ssl
import json
import os
from tkinter import filedialog

class HomeAssistantWidget:
    def __init__(self):
        # ===== KONFIGURATION - Wird aus Datei geladen =====
        self.config_file = "widget_config.json"
        self.config = {
            "homeassistant": {
                "ha_url": "http://YOUR_HA_IP:8123",
                "token": "YOUR_LONG_LIVED_TOKEN",
                "entity_id": "switch.your_switch_entity",
                "camera_entity": "camera.your_camera_entity",
                "light_entity": "light.your_printer_chamber_light",
                "entity_names": {
                    # Automatische Namen werden zur Laufzeit generiert
                },
                "entities": [
                    "sensor.your_printer_total_layers",
                    "sensor.your_printer_current_layer",
                    "sensor.your_printer_progress",
                    "sensor.your_printer_nozzle_temp",
                    "sensor.your_printer_bed_temp",
                    "sensor.your_smart_plug_power",
                    "binary_sensor.your_printer_hms_error",
                    "sensor.your_printer_part_fan_speed",
                    "sensor.your_printer_hotend_fan_speed",
                    "binary_sensor.your_printer_print_error",
                    "binary_sensor.your_printer_external_spool",
                    "binary_sensor.your_printer_filament_status",
                    "sensor.your_printer_total_usage",
                    "sensor.your_printer_start_time",
                    "sensor.your_printer_remaining_time",
                    "sensor.your_printer_end_time",
                    "light.your_printer_chamber_light"
                ]
            },
            "mqtt": {
                "bambu_ip": "DEINE_DRUCKER_IP",           # Statt 192.168.xxx.xxx
                "bambu_serial": "DEINE_SERIENNUMMER",     # Statt 01P05C2G1711725
                "bambu_access_code": "DEIN_ACCESS_CODE",   # Statt 12345678
                "printer_name": "3D Drucker",            # Benutzerdefinierten Drucker Namen
            },
            "ustreamer": {
                "enabled": False,
                "pi5_ip": "192.168.178.2",
                "port": 8888,
                "username": "",
                "password": ""
            }
        }

        # Konfiguration laden
        self.load_config()
        self.update_runtime_variables()

        # Variablen aus Konfiguration setzen
        self.ha_url = self.config["homeassistant"]["ha_url"]
        self.token = self.config["homeassistant"]["token"]
        self.entity_id = self.config["homeassistant"]["entity_id"]
        self.camera_entity = self.config["homeassistant"]["camera_entity"]
        self.light_entity = self.config["homeassistant"]["light_entity"]
        self.entities = self.config["homeassistant"]["entities"]
        self.bambu_ip = self.config["mqtt"]["bambu_ip"]
        self.bambu_serial = self.config["mqtt"]["bambu_serial"]
        self.bambu_access_code = self.config["mqtt"]["bambu_access_code"]

        # MQTT Status-Variablen hinzufügen
        self.mqtt_connected = False
        self.mqtt_client = None
        self.printer_status = {}
        # Druckername aus Konfiguration
        self.printer_name = self.config["mqtt"]["printer_name"]
        # µStreamer basierend auf Konfiguration aktivieren
        self.use_ustreamer_camera = self.config["ustreamer"]["enabled"]
        self.stream_reader = None
        self.pip_window = None
        self.pip_active = False
        # Kamera-Größen-Einstellungen
        self.camera_sizes = [
            (480, 270),   # Klein
            (640, 360),   # Medium
            (720, 405),   # Groß
            (960, 540)    # Sehr groß
        ]
        self.current_size_index = 1  # Start mit Medium

        # App-Größen entsprechend der Kamera-Größe
        self.app_sizes = [
            (1200, 850),  # Klein - App klein
            (1300, 910),  # Medium - Standard
            (1400, 910),  # Groß - App größer
            (1600, 1050)  # Sehr groß - App sehr groß
        ]

        # Cache für letzte bekannte Druckdaten
        self.last_print_data = {
            'progress': 0,
            'layer_num': 0,
            'total_layers': 0,
            'remaining_time': 0,
            'print_time': 0,
            'filename': 'Kein Druck aktiv',
            'gcode_state': 'IDLE'
        }
        # ===== ENDE KONFIGURATION =====

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        self.setup_gui()

        # Setup-Wizard anzeigen wenn nicht konfiguriert
        if not self.is_configured():
            self.show_unconfigured_status()
            self.root.after(500, self.show_setup_wizard)
        else:
            self.root.after(1000, self.check_and_start_updates)

        # MQTT IMMER versuchen (unabhängig von HA-Konfiguration)
        self.root.after(2000, self.auto_connect_mqtt)

        # Cleanup beim Schließen
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """App wird geschlossen"""
        if self.stream_reader:
            self.stream_reader.stop_stream()
        self.root.destroy()

    def check_and_start_updates(self):
        """Startet Updates immer"""
        self.update_status()
        self.update_camera()

    def show_unconfigured_status(self):
        """Zeigt Status für unkonfigurierte App"""
        for entity in self.entities:
            if entity in self.sensor_labels:
                self.sensor_labels[entity].config(text="Nicht konfiguriert", fg="#95a5a6")

        self.camera_label.config(text="Bitte Home Assistant in\nEinstellungen konfigurieren",
                                bg='#34495e', fg='#95a5a6')

    def center_window(self, window, width, height):
            """Fenster über dem Hauptfenster zentrieren"""
            # Position des Hauptfensters ermitteln
            self.root.update_idletasks()
            main_x = self.root.winfo_x()
            main_y = self.root.winfo_y()
            main_width = self.root.winfo_width()
            main_height = self.root.winfo_height()

            # Zentrale Position berechnen
            x = main_x + (main_width - width) // 2
            y = main_y + (main_height - height) // 2

            # Fenster positionieren
            window.geometry(f"{width}x{height}+{x}+{y}")

    def update_pip_camera(self):
        """PiP-Kamera aktualisieren - separate von Hauptkamera"""
        if not self.pip_active or not self.pip_window:
            return

        def update():
            image_data = self.get_camera_image()
            if image_data and self.pip_window:
                try:
                    image = Image.open(io.BytesIO(image_data))

                    # An PiP-Fenstergröße anpassen
                    pip_width = self.pip_window.winfo_width()
                    pip_height = self.pip_window.winfo_height()

                    if pip_width > 100 and pip_height > 50:
                        img_ratio = image.width / image.height
                        win_ratio = pip_width / pip_height

                        if img_ratio > win_ratio:
                            new_width = pip_width - 10
                            new_height = int(new_width / img_ratio)
                        else:
                            new_height = pip_height - 10
                            new_width = int(new_height * img_ratio)

                        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(image)

                        if self.pip_camera_label and self.pip_window:
                            self.pip_camera_label.config(image=photo, text="")
                            self.pip_camera_label.image = photo

                except Exception as e:
                    if self.pip_camera_label and self.pip_window:
                        self.pip_camera_label.config(text="PiP Fehler")

        # PiP nur aktualisieren nicht Threading für bessere Performance
        if self.pip_active:
            update()  # Direkt aufrufen, kein Thread
            self.root.after(66, self.update_pip_camera)  # Auch nur 5 FPS

    def update_runtime_variables(self):
        """Runtime-Variablen aus Konfiguration aktualisieren"""
        # Home Assistant
        self.ha_url = self.config["homeassistant"]["ha_url"]
        self.token = self.config["homeassistant"]["token"]
        self.entity_id = self.config["homeassistant"]["entity_id"]
        self.camera_entity = self.config["homeassistant"]["camera_entity"]
        self.entities = self.config["homeassistant"]["entities"]

        # MQTT
        self.bambu_ip = self.config["mqtt"]["bambu_ip"]
        self.bambu_serial = self.config["mqtt"]["bambu_serial"]
        self.bambu_access_code = self.config["mqtt"]["bambu_access_code"]

        # Headers aktualisieren
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        # Light Entity aktualisieren
        self.light_entity = self.config["homeassistant"]["light_entity"]


    def auto_connect_mqtt(self):
        """MQTT automatisch und still verbinden"""
        # Nur MQTT-Daten prüfen, KEINE Home Assistant Abhängigkeit
        mqtt_ready = (self.bambu_ip != "DEINE_DRUCKER_IP" and
                     self.bambu_serial != "DEINE_SERIENNUMMER" and
                     self.bambu_access_code != "DEIN_ACCESS_CODE" and
                     self.bambu_ip and self.bambu_serial and self.bambu_access_code)

        if not self.mqtt_connected and mqtt_ready:
            try:
                # MQTT Client erstellen
                self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                self.mqtt_client.username_pw_set("bblp", self.bambu_access_code)
                self.mqtt_client.on_connect = self.on_mqtt_connect_silent
                self.mqtt_client.on_message = self.on_mqtt_message
                self.mqtt_client.on_disconnect = self.on_mqtt_disconnect_silent

                # SSL Context
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.mqtt_client.tls_set_context(context)

                # Status anzeigen
                self.mqtt_status_label.config(text="📡 MQTT: Verbinde...", fg="#f39c12")

                # Verbindung herstellen
                self.mqtt_client.connect(self.bambu_ip, 8883, 60)
                self.mqtt_client.loop_start()

            except Exception as e:
                # Stille Fehlerbehandlung - nur Status aktualisieren
                self.mqtt_status_label.config(text="📡 MQTT: Fehler", fg="#e74c3c")
                print(f"Auto-MQTT Fehler: {e}")

    def on_mqtt_connect_silent(self, client, userdata, flags, reason_code, properties):
        """MQTT Verbindung hergestellt - OHNE Popup"""
        if reason_code == 0:
            self.mqtt_connected = True
            self.mqtt_status_label.config(text="📡 MQTT: Verbunden", fg="#27ae60")
            self.mqtt_connect_btn.config(text="📡 MQTT Trennen", state="normal")

            # Status Topic abonnieren
            topic = f"device/{self.bambu_serial}/report"
            client.subscribe(topic)

            # Pushall Command senden
            self.send_pushall_command()

            # Periodisches Pushall alle 10 Sekunden
            self.schedule_periodic_pushall()

            # KEIN messagebox.showinfo!
        else:
            self.mqtt_connected = False
            self.mqtt_status_label.config(text="📡 MQTT: Fehler", fg="#e74c3c")
            self.mqtt_connect_btn.config(text="📡 MQTT Verbinden", state="normal")

    def get_ustreamer_image(self):
        """Bild von µStreamer MJPEG-Stream holen"""
        if not self.config["ustreamer"]["enabled"]:
            return None

        # Stream-Reader starten falls noch nicht aktiv
        if not self.stream_reader or not self.stream_reader.running:
            pi5_ip = self.config["ustreamer"]["pi5_ip"]
            port = self.config["ustreamer"]["port"]
            username = self.config["ustreamer"]["username"]
            password = self.config["ustreamer"]["password"]

            stream_url = f"http://{pi5_ip}:{port}/stream"

            # Auth falls nötig
            auth = None
            if username and password:
                from requests.auth import HTTPBasicAuth
                auth = HTTPBasicAuth(username, password)

            self.stream_reader = SimpleStreamReader(stream_url, auth)
            if not self.stream_reader.start_stream():
                return None

        # Neuestes Frame holen
        return self.stream_reader.get_latest_frame()

    def on_mqtt_disconnect_silent(self, client, userdata, disconnect_flags, reason_code, properties):
        """MQTT Verbindung getrennt - OHNE Popup"""
        self.mqtt_connected = False
        self.mqtt_status_label.config(text="📡 MQTT: Getrennt", fg="#e74c3c")
        self.mqtt_connect_btn.config(text="📡 MQTT Verbinden", state="normal")

        # KEIN messagebox bei unerwarteter Trennung

    def toggle_light(self):
        """Druckraumlicht ein/ausschalten"""
        light_entity = self.light_entity

        # Aktuellen Status abrufen
        light_data = self.get_state(light_entity)
        if not light_data:
            messagebox.showwarning("Warnung", "Lichtstatus konnte nicht abgerufen werden!")
            return

        current_state = light_data["state"]

        # Service bestimmen
        if current_state == "on":
            service = "turn_off"
            service_domain = "light"
        else:
            service = "turn_on"
            service_domain = "light"

        # Befehl senden
        try:
            response = requests.post(
                f"{self.ha_url}/api/services/{service_domain}/{service}",
                json={"entity_id": light_entity},
                headers=self.headers,
                timeout=5
            )

            if response.status_code == 200:
                # Button sofort aktualisieren für besseres UX
                new_state = "off" if current_state == "on" else "on"
                self.update_light_button_state(new_state)

                # Nach kurzer Verzögerung echten Status abrufen
                self.root.after(1000, self.update_light_from_server)
            else:
                messagebox.showerror("Fehler", f"Licht-Befehl fehlgeschlagen: {response.status_code}")

        except Exception as e:
            messagebox.showerror("Fehler", f"Verbindungsfehler beim Lichtschalten: {str(e)}")

    def update_light_from_server(self):
        """Lichtstatus vom Server abrufen und Button aktualisieren"""
        light_entity = self.light_entity
        light_data = self.get_state(light_entity)

        if light_data:
            state = light_data["state"]
            self.update_light_button_state(state)

    def update_light_button_state(self, state):
        """Licht-Button basierend auf Status aktualisieren"""
        if not hasattr(self, 'light_btn'):
            return

        if state == "on":
            self.light_btn.configure(
                text="🔆 Licht aus",
                bg="#f1c40f",  # Gelb für an
                activebackground="#e67e22"  # Orange hover
            )
        else:
            self.light_btn.configure(
                text="💡 Licht ein",
                bg="#3498db",  # Blau für aus
                activebackground="#2980b9"  # Dunkelblau hover
            )

    def toggle_camera_source(self):
        """Zwischen µStreamer und Home Assistant Kamera wechseln"""
        self.use_ustreamer_camera = not self.use_ustreamer_camera

        if self.use_ustreamer_camera:
            self.camera_switch_btn.configure(
                text="📷 µStreamer",
                bg="#9b59b6",
                activebackground="#8e44ad"
            )
        else:
            self.camera_switch_btn.configure(
                text="📹 Home Assistant",
                bg="#e67e22",
                activebackground="#d35400"
            )

        # Kamera sofort neu laden
        self.force_camera_update()

    def setup_gui(self):
        # DPI-Awareness für scharfe Darstellung
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass

        # Skalierung für hochauflösende Displays
        self.root = tk.Tk()
        # Icon für Taskleiste setzen
        try:
            self.root.iconbitmap('icon.ico')  # Falls du eine .ico Datei hast
        except:
            pass
        self.create_menu()
        self.root.call('tk', 'scaling', 1.5)  # 1.5x Skalierung für 1920x1200
        self.root.title("3D Drucker Widget")
        self.root.geometry("1250x910")
        self.root.configure(bg='#2c3e50')  # Dunkler Hintergrund
        #self.root.attributes('-topmost', True)

        # Moderne Schriftarten definieren
        self.font_title = font.Font(family="Segoe UI", size=12, weight="bold")
        self.font_normal = font.Font(family="Segoe UI", size=11)
        self.font_small = font.Font(family="Segoe UI", size=11)

        # Hauptframe mit modernem Design
        main_frame = tk.Frame(self.root, bg='#2c3e50')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Horizontaler Container für Kamera und Sensoren
        horizontal_frame = tk.Frame(main_frame, bg='#2c3e50')
        horizontal_frame.pack(fill=tk.BOTH, expand=True)

        # Kamera Bereich - Moderne Card (linke Seite)
        camera_card = tk.Frame(horizontal_frame, bg='#34495e', relief='solid', bd=1)
        camera_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        camera_inner = tk.Frame(camera_card, bg='#34495e')
        camera_inner.pack(padx=15, pady=15)

        camera_title = tk.Label(
            camera_inner,
            text="📹 Live Kamera",
            font=self.font_title,
            bg='#34495e',
            fg='#ecf0f1'
        )
        camera_title.pack(pady=(0, 10))

        # Kamera mit Overlay-Container
        camera_container = tk.Frame(camera_inner, bg='#34495e')
        camera_container.pack(pady=(0, 10))

        # Kamera Label
        self.camera_label = tk.Label(
            camera_container,
            text="Lade Kamera...",
            bg='#1a252f',
            fg='#95a5a6',
            font=self.font_normal,
            relief='solid',
            bd=1
        )
        self.camera_label.pack()

        # Overlay-Buttons (nach dem pack, damit sie über dem Bild sind)
        overlay_frame = tk.Frame(camera_container, bg='#2c3e50', relief='solid', bd=1)
        overlay_frame.place(x=10, y=10)

        # Größen-Buttons horizontal
        small_btn = tk.Button(overlay_frame, text="S", command=lambda: self.set_camera_size(0),
                             font=("Arial", 8, "bold"), width=2, height=1, bg='#34495e', fg='white', relief='flat')
        small_btn.pack(side='left', padx=1, pady=1)

        medium_btn = tk.Button(overlay_frame, text="M", command=lambda: self.set_camera_size(1),
                              font=("Arial", 8, "bold"), width=2, height=1, bg='#3498db', fg='white', relief='flat')
        medium_btn.pack(side='left', padx=1, pady=1)

        large_btn = tk.Button(overlay_frame, text="L", command=lambda: self.set_camera_size(2),
                             font=("Arial", 8, "bold"), width=2, height=1, bg='#34495e', fg='white', relief='flat')
        large_btn.pack(side='left', padx=1, pady=1)

        xlarge_btn = tk.Button(overlay_frame, text="XL", command=lambda: self.set_camera_size(3),
                              font=("Arial", 8, "bold"), width=2, height=1, bg='#34495e', fg='white', relief='flat')
        xlarge_btn.pack(side='left', padx=1, pady=1)

        # PiP Button
        pip_btn = tk.Button(overlay_frame, text="PiP", command=self.toggle_pip,
                           font=("Arial", 8, "bold"), width=2, height=1,
                           bg='#e67e22', fg='white', relief='flat',
                           cursor='hand2')
        pip_btn.pack(side='left', padx=1, pady=1)

        # Buttons für Referenz speichern
        self.size_buttons = [small_btn, medium_btn, large_btn, xlarge_btn]
        self.pip_btn = pip_btn

        # Buttons für Referenz speichern
        self.size_buttons = [small_btn, medium_btn, large_btn, xlarge_btn]

        # Button-Container für nebeneinander liegende Buttons
        button_container = tk.Frame(camera_inner, bg='#34495e')
        button_container.pack(pady=(15, 0), fill='x')

        # Buttons nebeneinander
        button_frame = tk.Frame(button_container, bg='#34495e')
        button_frame.pack()

        # Ein/Aus Button (links)
        switch_subframe = tk.Frame(button_frame, bg='#34495e')
        switch_subframe.pack(side='left', padx=(0, 10))

        self.status_label = tk.Label(
            switch_subframe,
            text="Status: Unbekannt",
            font=self.font_normal,
            bg='#34495e',
            fg='#ecf0f1'
        )
        self.status_label.pack(pady=(0, 5))

        self.toggle_button = tk.Button(
            switch_subframe,
            text="Ein/Aus",
            command=self.toggle_switch,
            font=self.font_title,
            width=12,
            height=1,
            relief='flat',
            cursor='hand2',
            bg='#3498db',
            fg='white',
            activebackground='#2980b9',
            activeforeground='white'
        )
        self.toggle_button.pack()

        # Licht-Button (rechts)
        light_subframe = tk.Frame(button_frame, bg='#34495e')
        light_subframe.pack(side='left', padx=(10, 0))

        # Kamera-Wechsel-Button (ganz rechts)
        camera_subframe = tk.Frame(button_frame, bg='#34495e')
        camera_subframe.pack(side='left', padx=(10, 0))

        camera_status_label = tk.Label(
            camera_subframe,
            text="Kameraquelle",
            font=self.font_normal,
            bg='#34495e',
            fg='#ecf0f1'
        )
        camera_status_label.pack(pady=(0, 5))

        self.camera_switch_btn = tk.Button(
            camera_subframe,
            text="📷 µStreamer",
            command=self.toggle_camera_source,
            font=self.font_title,
            width=15,
            height=1,
            relief='flat',
            cursor='hand2',
            bg='#9b59b6',
            fg='white',
            activebackground='#8e44ad',
            activeforeground='white'
        )
        self.camera_switch_btn.pack()

        # Button-Text basierend auf Konfiguration setzen
        if self.use_ustreamer_camera:
            self.camera_switch_btn.configure(text="📷 µStreamer", bg="#9b59b6", activebackground="#8e44ad")
        else:
            self.camera_switch_btn.configure(text="📹 Home Assistant", bg="#e67e22", activebackground="#d35400")

        light_status_label = tk.Label(
            light_subframe,
            text="Druckraumlicht",
            font=self.font_normal,
            bg='#34495e',
            fg='#ecf0f1'
        )
        light_status_label.pack(pady=(0, 5))

        self.light_btn = tk.Button(
            light_subframe,
            text="💡 Licht ein",
            command=self.toggle_light,
            font=self.font_title,
            width=12,
            height=1,
            relief='flat',
            cursor='hand2',
            bg='#3498db',
            fg='white',
            activebackground='#2980b9',
            activeforeground='white'
        )
        self.light_btn.pack()

        # Druckfortschritt unter den Buttons
        progress_card = tk.Frame(camera_inner, bg='#2c3e50', relief='solid', bd=1)
        progress_card.pack(fill='x', pady=(15, 0))

        progress_inner = tk.Frame(progress_card, bg='#2c3e50')
        progress_inner.pack(padx=10, pady=10, fill='x')

        # MQTT Status
        self.mqtt_status_label = tk.Label(
            progress_inner,
            text="📡 MQTT: Nicht verbunden",
            font=self.font_normal,
            bg='#2c3e50',
            fg='#e74c3c'
        )
        self.mqtt_status_label.pack(pady=(0, 10))

        # Druckfortschritt Titel
        progress_title = tk.Label(
            progress_inner,
            text="🖨️ Live Druckfortschritt",
            font=self.font_title,
            bg='#2c3e50',
            fg='#ecf0f1'
        )
        progress_title.pack(pady=(0, 10))

        # Progress Bar
        self.progress_var = tk.DoubleVar()
        progress_style = ttk.Style()
        progress_style.configure("Custom.Horizontal.TProgressbar",
                                 background='#3498db',
                                 troughcolor='#34495e',
                                 borderwidth=0,
                                 lightcolor='#3498db',
                                 darkcolor='#3498db')

        self.progress_bar = ttk.Progressbar(
            progress_inner,
            variable=self.progress_var,
            maximum=100,
            style="Custom.Horizontal.TProgressbar"
        )
        self.progress_bar.pack(fill='x', pady=(0, 5))

        # Progress Info
        self.progress_info = tk.Label(
            progress_inner,
            text="Fortschritt: 0% | Schicht: 0/0",
            font=self.font_normal,
            bg='#2c3e50',
            fg='#bdc3c7'
        )
        self.progress_info.pack(pady=(0, 5))

        # Zeit Info
        self.time_info = tk.Label(
            progress_inner,
            text="Zeit: --:-- / Verbleibend: --:--",
            font=self.font_normal,
            bg='#2c3e50',
            fg='#bdc3c7'
        )
        self.time_info.pack(pady=(0, 5))

        # Datei Info
        self.file_info = tk.Label(
            progress_inner,
            text="Datei: Kein Druck aktiv",
            font=self.font_normal,
            bg='#2c3e50',
            fg='#bdc3c7'
        )
        self.file_info.pack(pady=(0, 5))

        # MQTT Connect Button
        self.mqtt_connect_btn = tk.Button(
            progress_inner,
            text="📡 MQTT Verbinden",
            command=self.connect_mqtt,
            font=self.font_normal,
            width=20,
            height=1,
            relief='flat',
            cursor='hand2',
            bg='#e67e22',
            fg='white',
            activebackground='#d35400',
            activeforeground='white'
        )
        self.mqtt_connect_btn.pack(pady=(10, 0))

        # Sensoren Bereich - Moderne Card (rechte Seite)
        sensor_card = tk.Frame(horizontal_frame, bg='#34495e', relief='solid', bd=1)
        sensor_card.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(8, 0))

        sensor_inner = tk.Frame(sensor_card, bg='#34495e')
        sensor_inner.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        self.sensor_title = tk.Label(
            sensor_inner,
            text=f"🖨️ {self.printer_name} Status",
            font=self.font_title,
            bg='#34495e',
            fg='#ecf0f1'
        )
        self.sensor_title.pack(pady=(0, 15))

        # Canvas und Scrollbar für Sensoren mit modernem Design
        canvas_frame = tk.Frame(sensor_inner, bg='#34495e')
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, bg='#2c3e50', highlightthickness=0)
        self.scrollable_frame = tk.Frame(canvas, bg='#2c3e50')

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")


        # Labels für Sensoren erstellen - Moderne Rows
        self.sensor_labels = {}
        for i, entity in enumerate(self.entities):
            # Benutzerdefinierten Namen verwenden falls vorhanden
            entity_names = self.config["homeassistant"].get("entity_names", {})
            if entity in entity_names:
                name = entity_names[entity]
            else:
                full_name = entity.split('.')[-1].replace('_', ' ').title()
                # Generisches Prefix-Cleaning für Bambu Drucker
                # Entferne Muster wie "P1S SERIENNUMMER" am Anfang
                import re
                name = re.sub(r'^P1S [A-Z0-9]+ ', '', full_name).strip()
                if not name:  # Falls alles entfernt wurde
                    name = full_name

            # Alternating row colors
            row_color = '#34495e' if i % 2 == 0 else '#2c3e50'

            row_frame = tk.Frame(self.scrollable_frame, bg=row_color, relief='flat')
            row_frame.pack(fill=tk.X, padx=5, pady=2, ipady=8)

            name_label = tk.Label(
                row_frame,
                text=f"{name}:",
                width=22,
                anchor="w",
                font=self.font_normal,
                bg=row_color,
                fg='#bdc3c7'
            )
            name_label.pack(side="left", padx=(10, 5))

            value_label = tk.Label(
                row_frame,
                text="Lade...",
                anchor="w",
                width=25,
                font=self.font_normal,
                bg=row_color,
                fg='#3498db'
            )
            value_label.pack(side="left", padx=(5, 10))

            self.sensor_labels[entity] = value_label

        # Mouse wheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        canvas.pack(fill="both", expand=True)

    def create_menu(self):
        """Menüband erstellen"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Datei-Menü
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Datei", menu=file_menu)
        file_menu.add_command(label="Konfiguration exportieren", command=self.export_config)
        file_menu.add_command(label="Konfiguration importieren", command=self.import_config)
        file_menu.add_separator()
        file_menu.add_command(label="Beenden", command=self.root.quit)

        # Einstellungen-Menü
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Einstellungen", menu=settings_menu)
        settings_menu.add_command(label="Home Assistant", command=self.open_ha_settings)
        settings_menu.add_command(label="MQTT Drucker", command=self.open_mqtt_settings)
        settings_menu.add_command(label="µStreamer Kamera", command=self.open_ustreamer_settings)

        # Verbindung-Menü
        connection_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Verbindung", menu=connection_menu)
        connection_menu.add_command(label="MQTT neu verbinden", command=self.reconnect_mqtt)
        connection_menu.add_command(label="Status anzeigen", command=self.show_connection_status)

        # Hilfe-Menü
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Hilfe", menu=help_menu)
        help_menu.add_command(label="Über", command=self.show_about)

    def load_config(self):
        """Konfiguration aus Datei laden"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # Merge mit Default-Konfiguration
                    self.merge_config(loaded_config)
            else:
                # Erste Ausführung - Konfigurationsdatei erstellen
                self.save_config()
        except Exception as e:
            messagebox.showerror("Konfigurationsfehler", f"Fehler beim Laden: {str(e)}")

    def is_configured(self):
        """Prüft ob die App grundlegend konfiguriert ist"""
        ha_config = self.config["homeassistant"]
        mqtt_config = self.config["mqtt"]

        # Kritische HA-Einstellungen prüfen
        if (ha_config["ha_url"] == "http://YOUR_HA_IP:8123" or
            ha_config["token"] == "YOUR_LONG_LIVED_TOKEN" or
            not ha_config["ha_url"] or not ha_config["token"]):
            return False

        # MQTT optional, aber wenn gesetzt dann vollständig
        if (mqtt_config["bambu_ip"] != "DEINE_DRUCKER_IP" and
            mqtt_config["bambu_ip"] and
            (mqtt_config["bambu_serial"] == "DEINE_SERIENNUMMER" or
             mqtt_config["bambu_access_code"] == "DEIN_ACCESS_CODE")):
            return False

        return True

    def merge_config(self, loaded_config):
        """Geladene Konfiguration mit Default-Werten zusammenführen"""
        for section, values in loaded_config.items():
            if section in self.config:
                if isinstance(values, dict):
                    for key, value in values.items():
                        # ALLE Keys akzeptieren, nicht nur bestehende
                        self.config[section][key] = value
                else:
                    self.config[section] = values
            else:
                # Neue Sections auch hinzufügen
                self.config[section] = values

    def save_config(self):
        """Konfiguration in Datei speichern"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Konfigurationsfehler", f"Fehler beim Speichern: {str(e)}")

    def generate_printer_entities(self, serial, model="p1s"):
        """Automatische Entity-Generierung basierend auf Drucker-Seriennummer"""
        serial_lower = serial.lower()

        # Standard Bambu Lab Sensoren (deutsche Namen aus deiner Konfiguration)
        sensor_templates = [
            f"sensor.{model}_{serial_lower}_temperatur_der_duse",
            f"sensor.{model}_{serial_lower}_druckbetttemperatur",
            f"sensor.{model}_{serial_lower}_bauteillufterdrehzahl",
            f"sensor.{model}_{serial_lower}_druckkopflufterdrehzahl",
            f"sensor.{model}_{serial_lower}_gesamtnutzung",
            f"sensor.{model}_{serial_lower}_startzeit",
            f"sensor.{model}_{serial_lower}_verbleibende_zeit",
            f"sensor.{model}_{serial_lower}_endzeit",
            f"binary_sensor.{model}_{serial_lower}_hms_fehler",
            f"binary_sensor.{model}_{serial_lower}_druckfehler",
            f"binary_sensor.{model}_{serial_lower}_externalspool_aktiv",
            f"binary_sensor.{model}_{serial_lower}_extruder_filament_status",
            f"light.{model}_{serial_lower}_druckraumbeleuchtung"
        ]

        # Automatische Namen generieren
        entity_names = {
            f"sensor.{model}_{serial_lower}_temperatur_der_duse": "Düsentemperatur",
            f"sensor.{model}_{serial_lower}_druckbetttemperatur": "Betttemperatur",
            f"sensor.{model}_{serial_lower}_bauteillufterdrehzahl": "Teillüfter",
            f"sensor.{model}_{serial_lower}_druckkopflufterdrehzahl": "Druckkopflüfter",
            f"sensor.{model}_{serial_lower}_gesamtnutzung": "Gesamtnutzung",
            f"binary_sensor.{model}_{serial_lower}_hms_fehler": "HMS Fehler",
            f"binary_sensor.{model}_{serial_lower}_druckfehler": "Druckfehler",
            f"light.{model}_{serial_lower}_druckraumbeleuchtung": "Druckraumlicht"
        }

        # Entity-Namen in Konfiguration speichern
        self.config["homeassistant"]["entity_names"].update(entity_names)

        return sensor_templates

    def export_config(self):
        """Konfiguration exportieren"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON-Dateien", "*.json"), ("Alle Dateien", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                messagebox.showinfo("Export", "Konfiguration erfolgreich exportiert!")
            except Exception as e:
                messagebox.showerror("Export-Fehler", f"Fehler beim Exportieren: {str(e)}")

    def import_config(self):
        """Konfiguration importieren"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON-Dateien", "*.json"), ("Alle Dateien", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    imported_config = json.load(f)

                # Konfiguration übernehmen
                self.config = imported_config
                self.save_config()

                messagebox.showinfo("Import", "Konfiguration erfolgreich importiert!\nBitte App neu starten.")
            except Exception as e:
                messagebox.showerror("Import-Fehler", f"Fehler beim Importieren: {str(e)}")

    def open_ha_settings(self):
        """Home Assistant Einstellungen öffnen"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Home Assistant Einstellungen")
        # Icon setzen
        try:
            settings_window.iconbitmap('icon.ico')
        except:
            pass
        self.center_window(settings_window, 600, 550)
        settings_window.configure(bg='#2c3e50')
        settings_window.resizable(False, False)

        # Hauptframe
        main_frame = tk.Frame(settings_window, bg='#2c3e50')
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # Titel
        title = tk.Label(main_frame, text="Home Assistant Konfiguration",
                         font=self.font_title, bg='#2c3e50', fg='#ecf0f1')
        title.pack(pady=(0, 20))

        # URL
        tk.Label(main_frame, text="Home Assistant URL:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        url_entry = tk.Entry(main_frame, font=self.font_normal, width=60)
        url_entry.insert(0, self.config["homeassistant"]["ha_url"])
        url_entry.pack(fill='x', pady=(5, 15))

        # Token
        tk.Label(main_frame, text="Long-lived Access Token:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        token_entry = tk.Entry(main_frame, font=self.font_normal, width=60, show='*')
        token_entry.insert(0, self.config["homeassistant"]["token"])
        token_entry.pack(fill='x', pady=(5, 15))

        # Switch Entity
        tk.Label(main_frame, text="Schalter Entity ID:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        switch_entry = tk.Entry(main_frame, font=self.font_normal, width=60)
        switch_entry.insert(0, self.config["homeassistant"]["entity_id"])
        switch_entry.pack(fill='x', pady=(5, 15))

        # Camera Entity
        tk.Label(main_frame, text="Kamera Entity ID:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        camera_entry = tk.Entry(main_frame, font=self.font_normal, width=60)
        camera_entry.insert(0, self.config["homeassistant"]["camera_entity"])
        camera_entry.pack(fill='x', pady=(5, 15))

        # Light Entity
        tk.Label(main_frame, text="Licht Entity ID:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        light_entry = tk.Entry(main_frame, font=self.font_normal, width=60)
        light_entry.insert(0, self.config["homeassistant"]["light_entity"])
        light_entry.pack(fill='x', pady=(5, 15))

        # Buttons
        button_frame = tk.Frame(main_frame, bg='#2c3e50')
        button_frame.pack(fill='x', pady=(20, 0))

        def save_ha_settings():
            self.config["homeassistant"]["ha_url"] = url_entry.get()
            self.config["homeassistant"]["token"] = token_entry.get()
            self.config["homeassistant"]["entity_id"] = switch_entry.get()
            self.config["homeassistant"]["camera_entity"] = camera_entry.get()
            self.config["homeassistant"]["light_entity"] = light_entry.get()

            # Runtime-Variablen aktualisieren
            self.ha_url = self.config["homeassistant"]["ha_url"]
            self.token = self.config["homeassistant"]["token"]
            self.entity_id = self.config["homeassistant"]["entity_id"]
            self.camera_entity = self.config["homeassistant"]["camera_entity"]

            # Headers neu setzen
            self.headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }

            self.save_config()
            messagebox.showinfo("Gespeichert", "Home Assistant Einstellungen gespeichert!")
            settings_window.destroy()

        tk.Button(button_frame, text="Speichern", command=save_ha_settings,
                  bg='#27ae60', fg='white', font=self.font_normal, width=15).pack(side='right', padx=5)
        tk.Button(button_frame, text="Abbrechen", command=settings_window.destroy,
                  bg='#e74c3c', fg='white', font=self.font_normal, width=15).pack(side='right')

    def open_mqtt_settings(self):
        """MQTT Einstellungen öffnen"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("MQTT Drucker Einstellungen")
        # Icon setzen
        try:
            settings_window.iconbitmap('icon.ico')
        except:
            pass
        self.center_window(settings_window, 500, 580)
        settings_window.configure(bg='#2c3e50')
        settings_window.resizable(False, False)

        # Hauptframe
        main_frame = tk.Frame(settings_window, bg='#2c3e50')
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # Titel
        title = tk.Label(main_frame, text="Bambu Lab Drucker MQTT",
                         font=self.font_title, bg='#2c3e50', fg='#ecf0f1')
        title.pack(pady=(0, 20))

        # IP
        tk.Label(main_frame, text="Drucker IP-Adresse:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        ip_entry = tk.Entry(main_frame, font=self.font_normal, width=40)
        ip_entry.insert(0, self.config["mqtt"]["bambu_ip"])
        ip_entry.pack(fill='x', pady=(5, 15))

        # Serial
        tk.Label(main_frame, text="Drucker Seriennummer:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        serial_entry = tk.Entry(main_frame, font=self.font_normal, width=40)
        serial_entry.insert(0, self.config["mqtt"]["bambu_serial"])
        serial_entry.pack(fill='x', pady=(5, 15))

        # Access Code
        tk.Label(main_frame, text="Access Code:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        access_entry = tk.Entry(main_frame, font=self.font_normal, width=40)
        access_entry.insert(0, self.config["mqtt"]["bambu_access_code"])
        access_entry.pack(fill='x', pady=(5, 15))

        # Druckername
        tk.Label(main_frame, text="Druckername (Anzeige):",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        name_entry = tk.Entry(main_frame, font=self.font_normal, width=40)
        name_entry.insert(0, self.config["mqtt"]["printer_name"])
        name_entry.pack(fill='x', pady=(5, 15))

        # Info
        info_text = """Hinweis: Den Access Code findest du auf dem Display
    deines Bambu Lab Druckers unter:
    Einstellungen → WLAN → Access Code"""

        tk.Label(main_frame, text=info_text, font=self.font_small,
                 bg='#2c3e50', fg='#95a5a6', justify='left').pack(pady=(10, 20))

        # Buttons
        button_frame = tk.Frame(main_frame, bg='#2c3e50')
        button_frame.pack(fill='x', pady=(20, 0))

        def save_mqtt_settings():
            self.config["mqtt"]["bambu_ip"] = ip_entry.get()
            self.config["mqtt"]["bambu_serial"] = serial_entry.get()
            self.config["mqtt"]["bambu_access_code"] = access_entry.get()
            self.config["mqtt"]["printer_name"] = name_entry.get()  # Neue Zeile

            self.save_config()
            # Runtime-Variablen sofort aktualisieren
            self.update_runtime_variables()

            # Druckername sofort aktualisieren
            self.printer_name = self.config["mqtt"]["printer_name"]
            self.update_printer_title()

            messagebox.showinfo("Gespeichert", "MQTT Einstellungen gespeichert!")
            settings_window.destroy()

        tk.Button(button_frame, text="Speichern", command=save_mqtt_settings,
                  bg='#27ae60', fg='white', font=self.font_normal, width=15).pack(side='right', padx=5)
        tk.Button(button_frame, text="Abbrechen", command=settings_window.destroy,
                  bg='#e74c3c', fg='white', font=self.font_normal, width=15).pack(side='right')

    def open_ustreamer_settings(self):
        """µStreamer Einstellungen öffnen"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("µStreamer Kamera")
        # Icon setzen
        try:
            settings_window.iconbitmap('icon.ico')
        except:
            pass
        self.center_window(settings_window, 400, 550)
        settings_window.configure(bg='#2c3e50')

        main_frame = tk.Frame(settings_window, bg='#2c3e50')
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        title = tk.Label(main_frame, text="Pi5 µStreamer Kamera",
                         font=self.font_title, bg='#2c3e50', fg='#ecf0f1')
        title.pack(pady=(0, 20))

        # Aktivieren
        enabled_var = tk.BooleanVar(value=self.config["ustreamer"]["enabled"])
        enabled_check = tk.Checkbutton(main_frame, text="µStreamer verwenden",
                                       variable=enabled_var, font=self.font_normal,
                                       bg='#2c3e50', fg='#bdc3c7', selectcolor='#34495e')
        enabled_check.pack(anchor='w', pady=(0, 15))

        # Pi5 IP
        tk.Label(main_frame, text="Pi5 IP-Adresse:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        ip_entry = tk.Entry(main_frame, font=self.font_normal, width=30)
        ip_entry.insert(0, self.config["ustreamer"]["pi5_ip"])
        ip_entry.pack(fill='x', pady=(5, 15))

        # Port
        tk.Label(main_frame, text="Port:",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        port_entry = tk.Entry(main_frame, font=self.font_normal, width=30)
        port_entry.insert(0, str(self.config["ustreamer"]["port"]))
        port_entry.pack(fill='x', pady=(5, 15))

        # Username
        tk.Label(main_frame, text="Benutzername (optional):",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        username_entry = tk.Entry(main_frame, font=self.font_normal, width=30)
        username_entry.insert(0, self.config["ustreamer"]["username"])
        username_entry.pack(fill='x', pady=(5, 15))

        # Password
        tk.Label(main_frame, text="Passwort (optional):",
                 font=self.font_normal, bg='#2c3e50', fg='#bdc3c7').pack(anchor='w')
        password_entry = tk.Entry(main_frame, font=self.font_normal, width=30, show='*')
        password_entry.insert(0, self.config["ustreamer"]["password"])
        password_entry.pack(fill='x', pady=(5, 15))

        # Buttons
        button_frame = tk.Frame(main_frame, bg='#2c3e50')
        button_frame.pack(fill='x')

        def save_settings():
            self.config["ustreamer"]["enabled"] = enabled_var.get()
            self.config["ustreamer"]["pi5_ip"] = ip_entry.get()
            self.config["ustreamer"]["port"] = int(port_entry.get()) if port_entry.get().isdigit() else 8888
            self.config["ustreamer"]["username"] = username_entry.get()
            self.config["ustreamer"]["password"] = password_entry.get()
            self.save_config()
            messagebox.showinfo("Gespeichert", "Einstellungen gespeichert!")
            settings_window.destroy()

        tk.Button(button_frame, text="Speichern", command=save_settings,
                  bg='#27ae60', fg='white', font=self.font_normal, width=15).pack(side='right', padx=5)
        tk.Button(button_frame, text="Abbrechen", command=settings_window.destroy,
                  bg='#e74c3c', fg='white', font=self.font_normal, width=15).pack(side='right')

    def reconnect_mqtt(self):
        """MQTT neu verbinden"""
        if self.mqtt_connected:
            self.disconnect_mqtt()
        self.root.after(1000, self.connect_mqtt)

    def show_connection_status(self):
        """Verbindungsstatus anzeigen"""
        ha_status = "✅ Verbunden" if self.ha_url and self.token else "❌ Nicht konfiguriert"
        mqtt_status = "✅ Verbunden" if self.mqtt_connected else "❌ Getrennt"

        status_text = f"""Verbindungsstatus:

    Home Assistant: {ha_status}
    URL: {self.ha_url}

    MQTT Drucker: {mqtt_status}
    IP: {self.bambu_ip}
    Serial: {self.bambu_serial}
    """

        messagebox.showinfo("Verbindungsstatus", status_text)

    def show_about(self):
        """Über-Dialog anzeigen"""
        about_text = """3D Drucker Widget v1.2

    Ein modernes Desktop-Widget für:
    - Home Assistant Integration
    - Bambu Lab 3D-Drucker MQTT
    - Live Kamerastream
    - Druckfortschritt-Überwachung

    Entwickelt für Windows
    Erstellt mit Python & tkinter"""

        messagebox.showinfo("Über", about_text)

    def show_setup_wizard(self):
        """Setup-Wizard für erste Einrichtung - Horizontales Layout"""
        setup_window = tk.Toplevel(self.root)
        setup_window.title("🚀 Erste Einrichtung")
        # Icon setzen
        try:
            setup_window.iconbitmap('icon.ico')
        except:
            pass
        setup_window.configure(bg='#2c3e50')
        setup_window.resizable(False, False)
        setup_window.grab_set()  # Modal
        self.center_window(setup_window, 800, 700)  # Breiter für horizontales Layout

        main_frame = tk.Frame(setup_window, bg='#2c3e50')
        main_frame.pack(fill='both', expand=True, padx=25, pady=25)

        # Header
        header_frame = tk.Frame(main_frame, bg='#34495e', relief='flat', bd=1)
        header_frame.pack(fill='x', pady=(0, 20))

        header_inner = tk.Frame(header_frame, bg='#34495e')
        header_inner.pack(padx=20, pady=15)

        title = tk.Label(header_inner, text="🚀 Willkommen!",
                         font=("Segoe UI", 18, "bold"), bg='#34495e', fg='#ecf0f1')
        title.pack()

        subtitle = tk.Label(header_inner, text="Lass uns deine App in 2 Minuten einrichten",
                           font=("Segoe UI", 11), bg='#34495e', fg='#bdc3c7')
        subtitle.pack(pady=(5, 0))

        # Content Frame mit Scroll
        content_frame = tk.Frame(main_frame, bg='#2c3e50')
        content_frame.pack(fill='both', expand=True)

        canvas = tk.Canvas(content_frame, bg='#2c3e50', highlightthickness=0, height=450)
        scrollable_frame = tk.Frame(canvas, bg='#2c3e50')

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # === HORIZONTALER CONTAINER FÜR HOME ASSISTANT & µSTREAMER ===
        top_row = tk.Frame(scrollable_frame, bg='#2c3e50')
        top_row.pack(fill='x', pady=(0, 15))

        # === HOME ASSISTANT CARD (Links) ===
        ha_card = tk.Frame(top_row, bg='#34495e', relief='solid', bd=1)
        ha_card.pack(side='left', fill='both', expand=True, padx=(0, 8))

        ha_header = tk.Frame(ha_card, bg='#3498db')
        ha_header.pack(fill='x')

        tk.Label(ha_header, text="📡 Home Assistant",
                font=("Segoe UI", 12, "bold"), bg='#3498db', fg='white').pack(pady=8)

        ha_body = tk.Frame(ha_card, bg='#34495e')
        ha_body.pack(fill='x', padx=15, pady=15)

        # Kompakte Eingabefelder
        def create_input_row(parent, label_text, default_value="", show_password=False):
            row = tk.Frame(parent, bg='#34495e')
            row.pack(fill='x', pady=3)

            label = tk.Label(row, text=label_text, font=("Segoe UI", 9),
                           bg='#34495e', fg='#bdc3c7', width=12, anchor='w')
            label.pack(side='left')

            entry = tk.Entry(row, font=("Segoe UI", 9), bg='#2c3e50', fg='#ecf0f1',
                           insertbackground='#ecf0f1', relief='flat', bd=1)
            if show_password:
                entry.config(show='*')
            if default_value:
                entry.insert(0, default_value)
            entry.pack(side='right', fill='x', expand=True, padx=(5, 0))

            return entry

        ha_url_entry = create_input_row(ha_body, "URL:", "http://192.168.178.10:8123")
        ha_token_entry = create_input_row(ha_body, "Token:", show_password=True)
        switch_entry = create_input_row(ha_body, "Schalter:", "switch.drucker_steckdose")

        # === µSTREAMER CARD (Rechts) ===
        ustreamer_card = tk.Frame(top_row, bg='#34495e', relief='solid', bd=1)
        ustreamer_card.pack(side='right', fill='both', expand=True, padx=(8, 0))

        ustreamer_header = tk.Frame(ustreamer_card, bg='#e67e22')
        ustreamer_header.pack(fill='x')

        tk.Label(ustreamer_header, text="📷 µStreamer (Optional)",
                font=("Segoe UI", 12, "bold"), bg='#e67e22', fg='white').pack(pady=8)

        ustreamer_body = tk.Frame(ustreamer_card, bg='#34495e')
        ustreamer_body.pack(fill='x', padx=15, pady=15)

        # Checkbox für µStreamer aktivieren
        ustreamer_enabled_var = tk.BooleanVar()
        ustreamer_check = tk.Checkbutton(
            ustreamer_body,
            text="µStreamer verwenden",
            variable=ustreamer_enabled_var,
            font=("Segoe UI", 9),
            bg='#34495e',
            fg='#bdc3c7',
            selectcolor='#2c3e50'
        )
        ustreamer_check.pack(anchor='w', pady=(0, 8))

        ustreamer_ip_entry = create_input_row(ustreamer_body, "Pi5 IP:", "192.168.178.30")
        ustreamer_port_entry = create_input_row(ustreamer_body, "Port:", "8888")
        ustreamer_user_entry = create_input_row(ustreamer_body, "User:")
        ustreamer_pass_entry = create_input_row(ustreamer_body, "Passwort:", show_password=True)

        # === MQTT CARD (Unten, volle Breite) ===
        mqtt_card = tk.Frame(scrollable_frame, bg='#34495e', relief='solid', bd=1)
        mqtt_card.pack(fill='x')

        mqtt_header = tk.Frame(mqtt_card, bg='#9b59b6')
        mqtt_header.pack(fill='x')

        tk.Label(mqtt_header, text="🖨️ MQTT Drucker (Optional)",
                font=("Segoe UI", 12, "bold"), bg='#9b59b6', fg='white').pack(pady=8)

        mqtt_body = tk.Frame(mqtt_card, bg='#34495e')
        mqtt_body.pack(fill='x', padx=15, pady=15)

        # MQTT Eingaben in zwei Spalten
        mqtt_row1 = tk.Frame(mqtt_body, bg='#34495e')
        mqtt_row1.pack(fill='x', pady=(0, 5))

        mqtt_left = tk.Frame(mqtt_row1, bg='#34495e')
        mqtt_left.pack(side='left', fill='both', expand=True, padx=(0, 10))

        mqtt_right = tk.Frame(mqtt_row1, bg='#34495e')
        mqtt_right.pack(side='right', fill='both', expand=True, padx=(10, 0))

        printer_name_entry = create_input_row(mqtt_left, "Name:", "Mein Bambulab P1S")
        mqtt_ip_entry = create_input_row(mqtt_right, "IP-Adresse:", "192.168.178.20")

        mqtt_row2 = tk.Frame(mqtt_body, bg='#34495e')
        mqtt_row2.pack(fill='x')

        mqtt_left2 = tk.Frame(mqtt_row2, bg='#34495e')
        mqtt_left2.pack(side='left', fill='both', expand=True, padx=(0, 10))

        mqtt_right2 = tk.Frame(mqtt_row2, bg='#34495e')
        mqtt_right2.pack(side='right', fill='both', expand=True, padx=(10, 0))

        mqtt_serial_entry = create_input_row(mqtt_left2, "Seriennummer:")
        mqtt_access_entry = create_input_row(mqtt_right2, "Access Code:")

        # Info Box für MQTT
        info_frame = tk.Frame(mqtt_body, bg='#2c3e50', relief='solid', bd=1)
        info_frame.pack(fill='x', pady=(10, 0))

        info_text = tk.Label(info_frame,
                           text="💡 Access Code am Drucker: Einstellungen → WLAN → Access Code | µStreamer: Pi5 Kamera-Server",
                           font=("Segoe UI", 9), bg='#2c3e50', fg='#95a5a6', justify='center')
        info_text.pack(padx=10, pady=8)

        canvas.pack(fill="both", expand=True)

        # Bottom Buttons
        button_frame = tk.Frame(main_frame, bg='#2c3e50')
        button_frame.pack(fill='x', pady=(20, 0))

        def save_setup():
            if not ha_url_entry.get().strip() or not ha_token_entry.get().strip():
                messagebox.showerror("Fehler", "Home Assistant URL und Token sind erforderlich!")
                return

            # ALLE Werte ZUERST auslesen
            ha_url_val = ha_url_entry.get().strip()
            ha_token_val = ha_token_entry.get().strip()
            switch_val = switch_entry.get().strip()
            printer_name_val = printer_name_entry.get().strip()
            mqtt_ip_val = mqtt_ip_entry.get().strip()
            mqtt_serial_val = mqtt_serial_entry.get().strip()
            mqtt_access_val = mqtt_access_entry.get().strip()

            # µStreamer Werte
            ustreamer_enabled_val = ustreamer_enabled_var.get()
            ustreamer_ip_val = ustreamer_ip_entry.get().strip()
            ustreamer_port_val = ustreamer_port_entry.get().strip()
            ustreamer_user_val = ustreamer_user_entry.get().strip()
            ustreamer_pass_val = ustreamer_pass_entry.get().strip()

            # Setup-Fenster schließen
            setup_window.destroy()

            # Konfiguration speichern
            self.config["homeassistant"]["ha_url"] = ha_url_val
            self.config["homeassistant"]["token"] = ha_token_val
            self.config["homeassistant"]["entity_id"] = switch_val

            self.config["mqtt"]["printer_name"] = printer_name_val
            self.config["mqtt"]["bambu_ip"] = mqtt_ip_val
            self.config["mqtt"]["bambu_serial"] = mqtt_serial_val
            self.config["mqtt"]["bambu_access_code"] = mqtt_access_val

            # µStreamer Konfiguration
            self.config["ustreamer"]["enabled"] = ustreamer_enabled_val
            self.config["ustreamer"]["pi5_ip"] = ustreamer_ip_val if ustreamer_ip_val else "192.168.178.2"
            self.config["ustreamer"]["port"] = int(ustreamer_port_val) if ustreamer_port_val.isdigit() else 8888
            self.config["ustreamer"]["username"] = ustreamer_user_val
            self.config["ustreamer"]["password"] = ustreamer_pass_val

            # Automatische Entity-Generierung
            if mqtt_serial_val:
                auto_entities = self.generate_printer_entities(mqtt_serial_val)

                # Schalter hinzufügen
                if switch_val and switch_val.startswith("sensor."):
                    if switch_val not in auto_entities:
                        auto_entities.append(switch_val)
                        self.config["homeassistant"]["entity_names"][switch_val] = "Steckdose"

                self.config["homeassistant"]["entities"] = auto_entities
                self.config["homeassistant"]["camera_entity"] = f"camera.p1s_{mqtt_serial_val.lower()}_kamera"
                self.config["homeassistant"]["light_entity"] = f"light.p1s_{mqtt_serial_val.lower()}_druckraumbeleuchtung"

                print(f"✅ Automatisch {len(auto_entities)} Entities generiert!")

            self.save_config()
            self.update_runtime_variables()

            if mqtt_serial_val:
                self.rebuild_sensor_gui()

            self.root.after(1000, self.check_and_start_updates)
            self.root.after(2000, self.auto_connect_mqtt)

            messagebox.showinfo("🎉 Fertig!", "Setup abgeschlossen! Deine App ist bereit.")

        def skip_setup():
            if messagebox.askyesno("Setup überspringen?", "Ohne Konfiguration funktioniert die App nur eingeschränkt.\n\nTrotzdem überspringen?"):
                setup_window.destroy()

        # Moderne Buttons
        skip_btn = tk.Button(button_frame, text="⏭️ Überspringen", command=skip_setup,
                            bg='#7f8c8d', fg='white', font=("Segoe UI", 10),
                            relief='flat', padx=20, pady=8, cursor='hand2')
        skip_btn.pack(side='left')

        save_btn = tk.Button(button_frame, text="✅ Los geht's!", command=save_setup,
                            bg='#27ae60', fg='white', font=("Segoe UI", 11, "bold"),
                            relief='flat', padx=30, pady=8, cursor='hand2')
        save_btn.pack(side='right')

        # Mouse wheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

    def rebuild_sensor_gui(self):
        """Sensor-GUI nach Setup neu aufbauen"""
        # Aktualisiere Runtime-Variablen
        self.update_runtime_variables()

        # Lösche alte Sensor-Labels
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        # Erstelle neue Labels für alle Entities
        self.sensor_labels = {}
        for i, entity in enumerate(self.entities):
            # Benutzerdefinierten Namen verwenden falls vorhanden
            entity_names = self.config["homeassistant"].get("entity_names", {})
            if entity in entity_names:
                name = entity_names[entity]
            else:
                full_name = entity.split('.')[-1].replace('_', ' ').title()
                # Generisches Prefix-Cleaning für Bambu Drucker
                import re
                name = re.sub(r'^P1S [A-Z0-9]+ ', '', full_name).strip()
                if not name:
                    name = full_name

            # Alternating row colors
            row_color = '#34495e' if i % 2 == 0 else '#2c3e50'

            row_frame = tk.Frame(self.scrollable_frame, bg=row_color, relief='flat')
            row_frame.pack(fill=tk.X, padx=5, pady=2, ipady=8)

            name_label = tk.Label(
                row_frame,
                text=f"{name}:",
                width=22,
                anchor="w",
                font=self.font_normal,
                bg=row_color,
                fg='#bdc3c7'
            )
            name_label.pack(side="left", padx=(10, 5))

            value_label = tk.Label(
                row_frame,
                text="Lade...",
                anchor="w",
                width=25,
                font=self.font_normal,
                bg=row_color,
                fg='#3498db'
            )
            value_label.pack(side="left", padx=(5, 10))

            self.sensor_labels[entity] = value_label

    def connect_mqtt(self):
        """MQTT Verbindung zum Bambu Drucker herstellen - MIT Popups"""
        if self.mqtt_connected:
            self.disconnect_mqtt()
            return

        try:
            # MQTT Client erstellen
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.mqtt_client.username_pw_set("bblp", self.bambu_access_code)
            self.mqtt_client.on_connect = self.on_mqtt_connect  # MIT Popup
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect  # MIT Popup
            # SSL Context
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            self.mqtt_client.tls_set_context(context)

            # Status anzeigen
            self.mqtt_status_label.config(text="📡 MQTT: Verbinde...", fg="#f39c12")
            self.mqtt_connect_btn.config(text="🔄 Verbinde...", state="disabled")

            # Verbindung herstellen (mit Timeout)
            self.mqtt_client.connect(self.bambu_ip, 8883, 60)
            self.mqtt_client.loop_start()

            # Nach 10 Sekunden prüfen ob Verbindung erfolgreich
            self.root.after(10000, self.check_mqtt_connection)

        except Exception as e:
            self.mqtt_status_label.config(text="📡 MQTT: Fehler", fg="#e74c3c")
            self.mqtt_connect_btn.config(text="📡 MQTT Verbinden", state="normal")
            messagebox.showerror("MQTT Fehler", f"Verbindung fehlgeschlagen:\n{str(e)}\n\nPrüfe IP-Adresse und Netzwerkverbindung!")

    def check_mqtt_connection(self):
        """Prüft ob MQTT-Verbindung erfolgreich war"""
        if not self.mqtt_connected:
            self.mqtt_status_label.config(text="📡 MQTT: Timeout", fg="#e74c3c")
            self.mqtt_connect_btn.config(text="📡 MQTT Verbinden", state="normal")
            messagebox.showwarning("Verbindung fehlgeschlagen",
                                 "MQTT-Verbindung konnte nicht hergestellt werden.\n\n" +
                                 "Mögliche Ursachen:\n" +
                                 "• Drucker ist ausgeschaltet\n" +
                                 "• Falsche IP-Adresse\n" +
                                 "• Netzwerkproblem\n" +
                                 "• Falscher Access Code")

    def disconnect_mqtt(self):
        """MQTT Verbindung trennen"""
        try:
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
        except Exception as e:
            print(f"MQTT Disconnect Fehler: {e}")

        self.mqtt_connected = False
        self.mqtt_status_label.config(text="📡 MQTT: Nicht verbunden", fg="#e74c3c")
        self.mqtt_connect_btn.config(text="📡 MQTT Verbinden", state="normal")

        # Cache zurücksetzen
        self.last_print_data = {
            'progress': 0,
            'layer_num': 0,
            'total_layers': 0,
            'remaining_time': 0,
            'print_time': 0,
            'filename': 'Kein Druck aktiv',
            'gcode_state': 'IDLE'
        }

        # UI zurücksetzen
        self.update_progress_ui()

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT Verbindung hergestellt"""
        if reason_code == 0:
            self.mqtt_connected = True
            self.mqtt_status_label.config(text="📡 MQTT: Verbunden", fg="#27ae60")
            self.mqtt_connect_btn.config(text="📡 MQTT Trennen", state="normal")

            # Status Topic abonnieren
            topic = f"device/{self.bambu_serial}/report"
            client.subscribe(topic)

            # Pushall Command senden
            self.send_pushall_command()

            # Periodisches Pushall alle 10 Sekunden
            self.schedule_periodic_pushall()

        else:
            self.mqtt_connected = False
            self.mqtt_status_label.config(text="📡 MQTT: Fehler", fg="#e74c3c")
            self.mqtt_connect_btn.config(text="📡 MQTT Verbinden", state="normal")
            messagebox.showerror("MQTT Fehler", f"Verbindung fehlgeschlagen: Code {reason_code}")

    def on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """MQTT Verbindung getrennt"""
        self.mqtt_connected = False
        self.mqtt_status_label.config(text="📡 MQTT: Getrennt", fg="#e74c3c")
        self.mqtt_connect_btn.config(text="📡 MQTT Verbinden", state="normal")

        if reason_code != 0:
            messagebox.showwarning("Verbindung verloren", "MQTT-Verbindung wurde unerwartet getrennt!")

    def schedule_periodic_pushall(self):
        """Periodisches Pushall alle 10 Sekunden"""
        if self.mqtt_connected:
            self.send_pushall_command()
            self.root.after(10000, self.schedule_periodic_pushall)  # 10 Sekunden

    def on_mqtt_message(self, client, userdata, msg):
        """MQTT Nachricht empfangen"""
        try:
            data = json.loads(msg.payload.decode())
            self.printer_status = data
            self.update_print_progress()
        except Exception as e:
            print(f"MQTT Nachricht Fehler: {e}")

    def send_pushall_command(self):
        """Pushall Command senden"""
        if not self.mqtt_connected or not self.mqtt_client:
            return

        command = {
            "pushing": {
                "sequence_id": "1",
                "command": "pushall"
            },
            "user_id": "1234567890"
        }

        topic = f"device/{self.bambu_serial}/request"
        self.mqtt_client.publish(topic, json.dumps(command))

    def update_print_progress(self):
        """Druckfortschritt aktualisieren"""
        if not self.printer_status:
            return

        print_info = self.printer_status.get("print", {})

        # Nur aktualisieren wenn neue Daten vorhanden sind
        progress = print_info.get("mc_percent")
        layer_num = print_info.get("layer_num")
        total_layers = print_info.get("total_layer_num")
        remaining_time = print_info.get("mc_remaining_time")  # Nur dieser Key ist verfügbar
        filename = print_info.get("subtask_name")
        gcode_state = print_info.get("gcode_state")

        # Cache aktualisieren nur wenn neue Werte vorhanden
        if progress is not None:
            self.last_print_data['progress'] = progress
        if layer_num is not None:
            self.last_print_data['layer_num'] = layer_num
        if total_layers is not None:
            self.last_print_data['total_layers'] = total_layers
        if remaining_time is not None and remaining_time > 0:
            self.last_print_data['remaining_time'] = remaining_time
        if filename is not None:
            self.last_print_data['filename'] = filename
        if gcode_state is not None:
            self.last_print_data['gcode_state'] = gcode_state

        # UI mit gecachten Daten aktualisieren
        self.update_progress_ui()

    def update_progress_ui(self):
        """Progress UI mit gecachten Daten aktualisieren"""
        # Fortschritt
        progress = self.last_print_data['progress']
        self.progress_var.set(progress)

        # Schichten
        layer_num = self.last_print_data['layer_num']
        total_layers = self.last_print_data['total_layers']

        self.progress_info.config(text=f"Fortschritt: {progress}% | Schicht: {layer_num}/{total_layers}")

        # Zeit - Nur verbleibende Zeit anzeigen, da verstrichene Zeit nicht verfügbar
        remaining_time = self.last_print_data['remaining_time']

        if remaining_time > 0:
            remaining_hours = remaining_time // 60
            remaining_minutes = remaining_time % 60
            remaining_str = f"{remaining_hours:02d}:{remaining_minutes:02d}"

            # Geschätzte Gesamtzeit berechnen wenn Fortschritt > 0
            if progress > 0:
                estimated_total = remaining_time / (1 - progress/100)
                elapsed_time = estimated_total - remaining_time
                elapsed_hours = int(elapsed_time // 60)
                elapsed_mins = int(elapsed_time % 60)
                elapsed_str = f"{elapsed_hours:02d}:{elapsed_mins:02d}"

                total_hours = int(estimated_total // 60)
                total_mins = int(estimated_total % 60)
                total_str = f"{total_hours:02d}:{total_mins:02d}"

                time_text = f"Verstichen: {elapsed_str} | Verbleibend: {remaining_str} | Gesamt: {total_str}"
            else:
                time_text = f"Verbleibende Zeit: {remaining_str}"
        else:
            time_text = "Zeit: Keine Daten verfügbar"

        self.time_info.config(text=time_text)

        # Dateiname und Status
        filename = self.last_print_data['filename']
        gcode_state = self.last_print_data['gcode_state']

        if gcode_state == "RUNNING":
            self.file_info.config(text=f"Datei: {filename} (Druckt)", fg="#27ae60")
        elif gcode_state == "PAUSE":
            self.file_info.config(text=f"Datei: {filename} (Pausiert)", fg="#f39c12")
        elif gcode_state == "FINISH":
            self.file_info.config(text=f"Datei: {filename} (Fertig)", fg="#3498db")
        elif gcode_state == "FAILED":
            self.file_info.config(text=f"Datei: {filename} (Fehler)", fg="#e74c3c")
        else:
            self.file_info.config(text="Datei: Kein Druck aktiv", fg="#bdc3c7")

    def update_printer_title(self):
        """Drucker-Titel mit echtem Namen aktualisieren"""
        if hasattr(self, 'sensor_title'):
            self.sensor_title.config(text=f"🖨️ {self.printer_name} Status")

    def get_state(self, entity_id=None):
        if entity_id is None:
            entity_id = self.entity_id

        try:
            response = requests.get(
                f"{self.ha_url}/api/states/{entity_id}",
                headers=self.headers,
                timeout=2  # Reduziert von 5 auf 2 Sekunden
            )
            if response.status_code == 200:
                return response.json()
        except:
            return None

    def set_camera_size(self, size_index):
        """Kamera-Größe setzen mit sofortiger App-Anpassung"""
        self.current_size_index = size_index

        # Button-Hervorhebung aktualisieren
        for i, btn in enumerate(self.size_buttons):
            if i == size_index:
                btn.config(bg='#3498db')
            else:
                btn.config(bg='#34495e')

        # App-Größe sofort anpassen
        app_width, app_height = self.app_sizes[size_index]
        self.root.geometry(f"{app_width}x{app_height}")

        # Kamera sofort neu laden
        self.force_camera_update()

    def force_camera_update(self):
        """Kamera sofort neu laden mit neuer Größe"""
        def update():
            image_data = self.get_camera_image()
            if image_data:
                try:
                    image = Image.open(io.BytesIO(image_data))
                    width, height = self.camera_sizes[self.current_size_index]
                    image = image.resize((width, height), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image)
                    self.camera_label.config(image=photo, text="")
                    self.camera_label.image = photo
                except Exception as e:
                    self.camera_label.config(text=f"Kamera Fehler: {str(e)}")
            else:
                self.camera_label.config(text="Kamera offline")

        threading.Thread(target=update, daemon=True).start()

    def get_camera_image(self):
        """Kamerabild holen - je nach gewählter Quelle"""
        # Kameraquelle basierend auf Toggle-Button
        if self.use_ustreamer_camera and self.config["ustreamer"]["enabled"]:
            return self.get_ustreamer_image()

        # Fallback zu Home Assistant Kamera
        try:
            response = requests.get(
                f"{self.ha_url}/api/camera_proxy/{self.camera_entity}",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.content
        except:
            return None

    def update_camera(self):
        def update():
            image_data = self.get_camera_image()
            if image_data:
                try:
                    image = Image.open(io.BytesIO(image_data))
                    # Dynamische Größe verwenden
                    width, height = self.camera_sizes[self.current_size_index]
                    image = image.resize((width, height), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image)

                    self.camera_label.config(image=photo, text="")
                    self.camera_label.image = photo
                except Exception as e:
                    pass  # Fehler ignorieren für flüssigere Darstellung
            # Kein "Kamera offline" Text mehr - stört nur

        threading.Thread(target=update, daemon=True).start()
        self.root.after(100, self.update_camera)

    def toggle_switch(self):
        try:
            current_state = self.get_state()["state"]
            if current_state == "on":
                service = "turn_off"
            else:
                service = "turn_on"

            requests.post(
                f"{self.ha_url}/api/services/switch/{service}",
                json={"entity_id": self.entity_id},
                headers=self.headers,
                timeout=5
            )

            self.root.after(500, self.update_status)

        except Exception as e:
            messagebox.showerror("Fehler", f"Verbindungsfehler: {str(e)}")

    def update_status(self):
        state_data = self.get_state()
        if state_data:
            state = state_data["state"]
            if state == "on":
                self.status_label.config(text="Status: Ein", fg="#27ae60")
                self.toggle_button.config(bg="#27ae60", activebackground="#2ecc71")
            else:
                self.status_label.config(text="Status: Aus", fg="#e74c3c")
                self.toggle_button.config(bg="#e74c3c", activebackground="#c0392b")
        else:
            self.status_label.config(text="Status: Offline", fg="gray")
            self.toggle_button.config(bg="lightgray")

        # Sensor Status aktualisieren
        for entity in self.entities:
            data = self.get_state(entity)
            if data:
                state = data["state"]
                unit = data.get("attributes", {}).get("unit_of_measurement", "")

                # Spezielle Formatierung für verschiedene Sensortypen
                if entity.startswith("binary_sensor"):
                    display_text = "Ja" if state == "on" else "Nein"
                    color = "#e74c3c" if state == "on" and "fehler" in entity else "#27ae60"
                elif "zeit" in entity and "-" in str(state) and ":" in str(state):
                    # Datum/Zeit Formatierung (2025-07-17 17:04:00 -> 17.07.2025 17:04:00)
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(str(state), "%Y-%m-%d %H:%M:%S")
                        display_text = dt.strftime("%d.%m.%Y %H:%M:%S")
                        color = "#3498db"
                    except:
                        display_text = str(state)
                        color = "#3498db"
                elif "verbleibende_zeit" in entity and unit == "h":
                    # Verbleibende Zeit formatierung (3.0666 h -> 3 Stunden und 4 Minuten)
                    try:
                        hours_float = float(state)
                        hours = int(hours_float)
                        minutes = int((hours_float - hours) * 60)
                        if minutes == 0:
                            display_text = f"{hours} Stunden"
                        else:
                            display_text = f"{hours} Stunden und {minutes} Minuten"
                        color = "#3498db"
                    except:
                        display_text = f"{state} {unit}"
                        color = "#3498db"
                elif entity.startswith("sensor") and unit:
                    display_text = f"{state} {unit}"
                    color = "#3498db"
                else:
                    display_text = str(state)
                    color = "#3498db"

                self.sensor_labels[entity].config(text=display_text, fg=color)
            else:
                self.sensor_labels[entity].config(text="Offline", fg="gray")

        light_entity = self.light_entity
        light_data = self.get_state(light_entity)
        if light_data:
            light_state = light_data["state"]
            self.update_light_button_state(light_state)

        # Alle 5 Sekunden Status aktualisieren
        self.root.after(5000, self.update_status)

    def toggle_pip(self):
        """Picture-in-Picture Modus ein/ausschalten"""
        if not self.pip_active:
            self.start_pip()
        else:
            self.stop_pip()

    def start_pip(self):
        """PiP-Fenster starten"""
        if self.pip_window:
            return

        # PiP-Fenster erstellen
        self.pip_window = tk.Toplevel(self.root)
        self.pip_window.title("📹 Kamera PiP")
        self.pip_window.geometry("640x360+100+100")  # Startgröße und Position
        self.pip_window.configure(bg='#1a252f')

        # Fenster-Eigenschaften
        self.pip_window.resizable(True, True)
        self.pip_window.attributes('-topmost', True)  # Immer oben

        # PiP-Kamera-Label
        self.pip_camera_label = tk.Label(
            self.pip_window,
            text="PiP Kamera wird geladen...",
            bg='#1a252f',
            fg='#95a5a6',
            font=self.font_normal
        )
        self.pip_camera_label.pack(fill='both', expand=True, padx=5, pady=5)

        # Beim Schließen des PiP-Fensters
        self.pip_window.protocol("WM_DELETE_WINDOW", self.stop_pip)

        # PiP-Update starten
        self.pip_active = True
        self.pip_btn.config(bg='#27ae60', text="PiP")  # Grün wenn aktiv
        self.update_pip_camera()

    def stop_pip(self):
        """PiP-Fenster beenden"""
        if self.pip_window:
            self.pip_window.destroy()
            self.pip_window = None

        self.pip_active = False
        self.pip_btn.config(bg='#e67e22', text="PiP")  # Orange wenn inaktiv

    def run(self):
        self.root.mainloop()

import cv2

class SimpleStreamReader:
    def __init__(self, url, auth=None):
        self.url = url
        self.auth = auth
        self.cap = None
        self.running = False

    def start_stream(self):
        """Stream mit OpenCV starten"""
        try:
            # URL mit Auth falls nötig
            if self.auth:
                # Requests Session für Auth
                import requests
                session = requests.Session()
                session.auth = self.auth
                # OpenCV kann direkt mit authentifizierten URLs arbeiten
                auth_url = self.url.replace('http://', f'http://{self.auth.username}:{self.auth.password}@')
                self.cap = cv2.VideoCapture(auth_url)
            else:
                self.cap = cv2.VideoCapture(self.url)

            self.running = self.cap.isOpened()
            return self.running
        except:
            return False

    def get_latest_frame(self):
        """Frame mit OpenCV lesen"""
        if not self.running or not self.cap:
            return None

        ret, frame = self.cap.read()
        if ret:
            # OpenCV BGR zu RGB konvertieren
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Zu JPEG encodieren
            _, buffer = cv2.imencode('.jpg', frame_rgb)
            return buffer.tobytes()
        return None

    def stop_stream(self):
        """Stream stoppen"""
        self.running = False
        if self.cap:
            self.cap.release()

if __name__ == "__main__":
    widget = HomeAssistantWidget()
    widget.run()
