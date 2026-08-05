# Microweaver - MicroPython Framework for ESP32 and Supported Microcontrollers

Microweaver is a lightweight MicroPython framework designed to simplify the development of applications for ESP32 and other supported microcontrollers. It serves as a scaffold or boilerplate to help embedded programmers get started with their projects quickly and efficiently. With Microweaver, you can focus on your application's logic instead of dealing with low-level hardware initialization and management.

## Features

- Abstraction for common hardware components and peripherals via `BaseAdapter`.
- Runtime-editable configuration (`device_config.json`) — no reflash needed to change WiFi/MQTT settings.
- WiFi and MQTT auto-reconnect with exponential backoff, so a dropped connection self-heals.
- Boot sequence (`boot.py`) separated from application logic (`main.py`) for a clean startup path.
- Provides a foundation for building IoT and embedded projects.
- Designed to work with MicroPython and ESP32 out of the box.
- Extensible and customizable for different microcontrollers.

## Getting Started

### Prerequisites

Before you can start using Microweaver, ensure you have the following prerequisites:

- An ESP32 or a supported microcontroller.
- MicroPython installed on your device.
- A development environment set up for MicroPython programming.

### Installation

1. Clone or download the Microweaver repository to your local machine.

   ```shell
   git clone https://github.com/nerdmonkey/microweaver-framework.git
   ```

2. Copy `device_config.json.example` to `device_config.json` and fill in your WiFi and MQTT settings:

   ```shell
   cp device_config.json.example device_config.json
   ```

3. Upload `boot.py`, `_boot.py`, `main.py`, `device_config.json`, and the `app`/`config` directories to your microcontroller. You can use tools like `ampy`, `rshell`, or `uPyCraft` to upload files.

   On boot, the device runs `boot.py`, which imports `main` and calls `main.start()`. `device_config.json` is read at runtime, so WiFi/MQTT credentials can be changed by editing that file and rebooting — no reflash required.

### Project Structure

- `boot.py` — thin MicroPython entry point; calls `_boot.run_bootstrap()`, logs and re-raises any unhandled boot exception.
- `_boot.py` — does the actual bootstrap: `gc.collect()`, imports `main`, `gc.collect()` again, then calls `main.start()`. Split from `boot.py` so memory used during import is freed before the app runs.
- `main.py` — defines `start()`, which wires up and runs the app's services.
- `config/app.py` — `Setting` class, reads `device_config.json` with sane defaults if the file is missing.
- `app/services/` — `WiFiService`, `MqttConnection` (shared reconnect/backoff logic), `PublishService`, `SubscribeService`.
- `app/adapters/{sensors,actuators,displays}/` — extension points for hardware drivers; each should subclass `BaseAdapter` (`app/adapters/base.py`), which provides an `available` property and a `deinit()` hook.

### Running tests

```shell
pip install -r requirements.txt
pytest
```

MicroPython-only modules (`network`, `umqtt.simple`) are stubbed in `tests/conftest.py` so the suite runs on a regular CPython interpreter.

## Contributing

We welcome contributions from the community to improve and expand Microweaver. If you have ideas, bug reports, or feature requests, please open an issue on the GitHub repository or submit a pull request.

## License

Microweaver is released under the [MIT License](LICENSE).

## Acknowledgments

Microweaver was inspired by the need for a simplified MicroPython framework for ESP32 and other microcontrollers. Special thanks to the MicroPython community for their ongoing contributions and support.

## Support

If you have any questions or need assistance with Microweaver, you can reach out to us on the [GitHub repository](https://github.com/nerdmonkey/microweaver-framework) or through [email](mailto:sydel.palinlin@gmail.com).

Happy coding with Microweaver!
