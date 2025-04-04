#!/usr/bin/env python3

import dbus
import dbus.mainloop.glib
from gi.repository import GLib  # type: ignore
import subprocess
import threading
from typing import Dict, List, Optional, Callable
import time  # For proper sleep handling
import os

from utils.logger import LogLevel, Logger

BLUEZ_SERVICE_NAME = "org.bluez"
BLUEZ_ADAPTER_INTERFACE = "org.bluez.Adapter1"
BLUEZ_DEVICE_INTERFACE = "org.bluez.Device1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
BLUEZ_SERVICE_NAME = 'org.bluez'
BLUEZ_ADAPTER_INTERFACE = 'org.bluez.Adapter1'
BLUEZ_DEVICE_INTERFACE = 'org.bluez.Device1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
DEFAULT_NOTIFY_SUBJECT='Better Control'


class BluetoothManager:
    def __init__(self, logging: Logger):
        self.logging = logging
        self.adapter = None
        self.adapter_path = None
        
        try:
            # Initialize DBus with mainloop
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.mainloop = GLib.MainLoop()
            
            # Find the adapter
            self.adapter_path = self.find_adapter()
            if self.adapter_path:
                self.adapter = dbus.Interface(
                    self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path),
                    DBUS_PROP_IFACE,
                )
                self.logging.log(LogLevel.Info, f"Bluetooth adapter found: {self.adapter_path}")
            else:
                self.logging.log(LogLevel.Warn, "No Bluetooth adapter found")
        except dbus.DBusException as e:
            self.logging.log(LogLevel.Error, f"DBus error initializing Bluetooth: {e}")
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Error initializing Bluetooth: {e}")

    BATTERY_INTERFACE = "org.bluez.Battery1"

    def __del__(self):
        """Cleanup resources"""
        try:
            # Clean up any resources
            self.adapter = None
            self.bus = None
        except Exception:
            pass  # Ignore errors during cleanup

    def get_device_battery(self, device_path: str) -> Optional[int]:
        """Retrieve battery percentage for a Bluetooth device using busctl."""
        try:
            cmd = [
                "busctl",
                "get-property",
                "org.bluez",
                device_path,
                "org.bluez.Battery1",
                "Percentage",
            ]

            # Run the command and capture the output
            output = subprocess.run(
                cmd, capture_output=True, text=True
            )

            if output.returncode != 0:
                return None
            else:
                return int(output.stdout.strip().split()[-1])

        except Exception as e:
            self.logging.log(LogLevel.Error, f"Failed retrieving battery info: {e}")
            return -1  # Indicate battery info is unavailable

    def find_adapter(self) -> str:
        """Find the first available Bluetooth adapter"""
        try:
            remote_om = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE
            )
            objects = remote_om.GetManagedObjects()

            for o, props in objects.items():
                if BLUEZ_ADAPTER_INTERFACE in props:
                    return o

            self.logging.log(LogLevel.Warn, "No Bluetooth adapter found")
            return ""
        except dbus.DBusException as e:
            self.logging.log(LogLevel.Error, f"DBus error finding Bluetooth adapter: {e}")
            return ""
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Error finding Bluetooth adapter: {e}")
            return ""

    def get_bluetooth_status(self) -> bool:
        """Get Bluetooth power status"""
        try:
            if not self.adapter:
                return False
            powered = self.adapter.Get(BLUEZ_ADAPTER_INTERFACE, "Powered")
            return bool(powered)
        except dbus.DBusException as e:
            self.logging.log(LogLevel.Error, f"DBus error getting Bluetooth status: {e}")
            return False
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Failed getting Bluetooth status: {e}")
            return False

    def set_bluetooth_power(self, enabled: bool) -> None:
        """Set Bluetooth power state"""
        try:
            if not self.adapter:
                return
            self.adapter.Set(BLUEZ_ADAPTER_INTERFACE, "Powered", dbus.Boolean(enabled))
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Failed setting Bluetooth power: {e}")

    def get_devices(self) -> List[Dict[str, str]]:
        """Get list of all known Bluetooth devices"""
        try:
            if not self.adapter:
                return []

            remote_om = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE
            )
            objects = remote_om.GetManagedObjects()
            devices = []
            for path, interfaces in objects.items():
                if BLUEZ_DEVICE_INTERFACE not in interfaces:
                    continue

                properties = interfaces[BLUEZ_DEVICE_INTERFACE]
                if not properties.get("Name", None):
                    continue

                devices.append(
                    {
                        "mac": properties.get("Address", ""),
                        "name": properties.get("Name", ""),
                        "paired": properties.get("Paired", False),
                        "connected": properties.get("Connected", False),
                        "trusted": properties.get("Trusted", False),
                        "icon": properties.get("Icon", ""),
                        "path": path,
                    }
                )
            return devices
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Failed getting devices: {e}")
            return []

    def start_discovery(self) -> None:
        """Start scanning for Bluetooth devices"""
        try:
            if not self.adapter:
                return
            adapter = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path),
                BLUEZ_ADAPTER_INTERFACE,
            )
            adapter.StartDiscovery()
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Failed starting discovery: {e}")

    def stop_discovery(self) -> None:
        """Stop scanning for Bluetooth devices"""
        try:
            if not self.adapter:
                return
            adapter = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path),
                BLUEZ_ADAPTER_INTERFACE,
            )
            adapter.StopDiscovery()
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Failed stopping discovery: {e}")

    def connect_device(self, device_path: str) -> bool:
        """Connect to a Bluetooth device, set it as the default audio sink, and fetch battery info."""
        try:
            device = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, device_path),
                BLUEZ_DEVICE_INTERFACE,
            )
            device.Connect()

            # Wait for the device to register
            import time

            time.sleep(2)

            # Fetch device name
            properties = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, device_path), DBUS_PROP_IFACE
            )
            device_name = properties.Get(BLUEZ_DEVICE_INTERFACE, "Alias")

            battery_percentage: Optional[int] = self.get_device_battery(device_path)
            battery_info: str = ''

            if battery_percentage is None:
                battery_info = ""
            else:
                battery_info = f"Battery: {battery_percentage}%"

            subprocess.run(["notify-send", DEFAULT_NOTIFY_SUBJECT,
                            f"{device_name} connected.\n{battery_info}"])

            return True
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Failed connecting to device: {e}")
            return False

    def connect_device_async(self, device_path: str, callback: Callable[[bool], None]) -> None:
        """Connect to a Bluetooth device asynchronously
        
        Args:
            device_path: DBus path of the device
            callback: Function to call when connection attempt completes with a boolean success parameter
        """
        def run_connect():
            success = False
            device_name = "Unknown Device"
            try:
                # Make a copy of the device_path to avoid any potential threading issues
                local_path = str(device_path)
                
                # Get DBus interfaces
                device = dbus.Interface(
                    self.bus.get_object(BLUEZ_SERVICE_NAME, local_path),
                    BLUEZ_DEVICE_INTERFACE,
                )
                properties = dbus.Interface(
                    self.bus.get_object(BLUEZ_SERVICE_NAME, local_path), 
                    DBUS_PROP_IFACE
                )
                
                # Get device name before connecting
                try:
                    device_name = str(properties.Get(BLUEZ_DEVICE_INTERFACE, "Alias"))
                except Exception:
                    device_name = "Bluetooth Device"
                
                # Connect to the device
                self.logging.log(LogLevel.Info, f"Connecting to {device_name}...")
                device.Connect()
                
                # Wait to ensure connection is established
                time.sleep(1)
                
                # Verify connection status
                try:
                    is_connected = bool(properties.Get(BLUEZ_DEVICE_INTERFACE, "Connected"))
                    if not is_connected:
                        self.logging.log(LogLevel.Warn, f"Connection to {device_name} reported as failed, but no exception thrown")
                        GLib.idle_add(lambda: callback(False))
                        return
                except Exception as e:
                    self.logging.log(LogLevel.Error, f"Failed to verify connection status: {e}")
                
                # Get battery information
                battery_percentage: Optional[int] = self.get_device_battery(local_path)
                battery_info: str = ''
                
                if battery_percentage is None:
                    battery_info = ""
                else:
                    battery_info = f"Battery: {battery_percentage}%"
                
                # Send notification
                subprocess.run(["notify-send", DEFAULT_NOTIFY_SUBJECT,
                                f"{device_name} connected.\n{battery_info}"])
                success = True
                
            except Exception as e:
                self.logging.log(LogLevel.Error, f"Failed connecting to device {device_name}: {e}")
                success = False
            
            # Call the callback in the main thread
            GLib.idle_add(lambda: callback(success))
        
        # Start the connection process in a separate real thread
        thread = threading.Thread(target=run_connect, daemon=True)
        thread.start()

    def disconnect_device(self, device_path: str) -> bool:
        """Disconnect from a Bluetooth device"""
        try:
            device = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, device_path),
                BLUEZ_DEVICE_INTERFACE,
            )
            properties = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, device_path), DBUS_PROP_IFACE
            )
            # Fetch device name
            device_name = "Bluetooth Device"
            device_name = properties.Get(BLUEZ_DEVICE_INTERFACE, "Name")
            device.Disconnect()

            subprocess.run(["notify-send", DEFAULT_NOTIFY_SUBJECT, f"{device_name} disconnected."])

            return True
        except Exception as e:
            self.logging.log(LogLevel.Error, f"Failed disconnecting from device: {e}")
            return False

    def disconnect_device_async(self, device_path: str, callback: Callable[[bool], None]) -> None:
        """Disconnect from a Bluetooth device asynchronously
        
        Args:
            device_path: DBus path of the device
            callback: Function to call when disconnection attempt completes with a boolean success parameter
        """
        def run_disconnect():
            success = False
            device_name = "Unknown Device"
            try:
                # Make a copy of the device_path to avoid any potential threading issues
                local_path = str(device_path)
                
                # Get DBus interfaces
                device = dbus.Interface(
                    self.bus.get_object(BLUEZ_SERVICE_NAME, local_path),
                    BLUEZ_DEVICE_INTERFACE,
                )
                properties = dbus.Interface(
                    self.bus.get_object(BLUEZ_SERVICE_NAME, local_path), 
                    DBUS_PROP_IFACE
                )
                
                # Get device name before disconnecting
                try:
                    device_name = str(properties.Get(BLUEZ_DEVICE_INTERFACE, "Name"))
                except Exception:
                    try:
                        device_name = str(properties.Get(BLUEZ_DEVICE_INTERFACE, "Alias"))
                    except Exception:
                        device_name = "Bluetooth Device"
                
                # Disconnect the device
                self.logging.log(LogLevel.Info, f"Disconnecting from {device_name}...")
                device.Disconnect()
                
                # Wait to ensure disconnection is completed
                time.sleep(1)
                
                # Send notification
                subprocess.run(["notify-send", DEFAULT_NOTIFY_SUBJECT, f"{device_name} disconnected."])
                success = True
                
            except Exception as e:
                self.logging.log(LogLevel.Error, f"Failed disconnecting from device {device_name}: {e}")
                success = False
            
            # Call the callback in the main thread
            GLib.idle_add(lambda: callback(success))
            
        # Start the disconnection process in a separate real thread
        thread = threading.Thread(target=run_disconnect, daemon=True)
        thread.start()


# Create a global instance of the BluetoothManager
_manager = None


def get_bluetooth_manager(logging: Logger) -> BluetoothManager:
    """Get or create the global BluetoothManager instance"""
    global _manager
    if _manager is None:
        _manager = BluetoothManager(logging)
    return _manager


import time
import subprocess
import logging


def restore_last_sink(logging: Logger):
    """Restore the last used audio sink device after startup.
    
    This function attempts to restore the last used audio sink, typically
    a Bluetooth device, if one was previously connected.
    """
    try:
        # Wait for PA to fully initialize
        time.sleep(1.0)
        
        # Get PulseAudio settings directory
        pa_dir = os.path.expanduser("~/.config/pulse")
        
        # If the pulse config directory doesn't exist, exit early
        if not os.path.exists(pa_dir):
            logging.log(LogLevel.Debug, "No PulseAudio config directory found")
            return
            
        # Look for connection config files (specifically the default sink file)
        default_sink_file = os.path.join(pa_dir, "default-sink")
        
        if not os.path.exists(default_sink_file):
            logging.log(LogLevel.Debug, "No default sink file found to restore")
            return
            
        try:
            # Read the saved sink
            with open(default_sink_file, "r") as f:
                saved_sink = f.read().strip()
                
            if not saved_sink:
                logging.log(LogLevel.Debug, "No saved sink found")
                return
                
            # Check if it's a Bluetooth device by name convention
            if not "bluez" in saved_sink.lower():
                logging.log(LogLevel.Debug, "Saved sink is not a Bluetooth device")
                return
                
            # Get current sinks
            process = subprocess.run(
                ["pactl", "list", "sinks", "short"],
                capture_output=True,
                text=True,
                check=False
            )
            
            # Check for the presence of the saved device in currently available devices
            current_sinks = process.stdout.splitlines()
            device_found = False
            
            for sink in current_sinks:
                if saved_sink in sink:
                    device_found = True
                    break
                    
            if not device_found:
                logging.log(LogLevel.Info, f"Saved Bluetooth sink '{saved_sink}' not currently available")
                return
                
            # Set the sink as default if it was found
            logging.log(LogLevel.Info, f"Restoring Bluetooth sink: {saved_sink}")
            subprocess.run(
                ["pactl", "set-default-sink", saved_sink],
                check=False
            )
            
        except Exception as e:
            logging.log(LogLevel.Error, f"Error restoring Bluetooth sink: {e}")
    except Exception as e:
        # Handle any unexpected errors without crashing
        logging.log(LogLevel.Error, f"Unexpected error in restore_last_sink: {e}")
    finally:
        # Always log completion to help with debugging
        logging.log(LogLevel.Debug, "Audio sink restoration process completed")


# Convenience functions using the global manager
def get_bluetooth_status(logging: Logger) -> bool:
    return get_bluetooth_manager(logging).get_bluetooth_status()


def set_bluetooth_power(enabled: bool, logging: Logger) -> None:
    get_bluetooth_manager(logging).set_bluetooth_power(enabled)


def get_devices(logging: Logger) -> List[Dict[str, str]]:
    return get_bluetooth_manager(logging).get_devices()


def start_discovery(logging: Logger) -> None:
    get_bluetooth_manager(logging).start_discovery()


def stop_discovery(logging: Logger) -> None:
    get_bluetooth_manager(logging).stop_discovery()


def connect_device(device_path: str, logging: Logger) -> bool:
    return get_bluetooth_manager(logging).connect_device(device_path)


def disconnect_device(device_path: str, logging: Logger) -> bool:
    return get_bluetooth_manager(logging).disconnect_device(device_path)


# Add async versions to the convenience functions
def connect_device_async(device_path: str, callback: Callable[[bool], None], logging: Logger) -> None:
    get_bluetooth_manager(logging).connect_device_async(device_path, callback)

def disconnect_device_async(device_path: str, callback: Callable[[bool], None], logging: Logger) -> None:
    get_bluetooth_manager(logging).disconnect_device_async(device_path, callback)
