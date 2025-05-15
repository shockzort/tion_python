# Tion Yandex Smart Home Integration

This module provides integration between Tion ventilation devices and the Yandex Smart Home platform, allowing users to control their Tion devices through Yandex Alice voice assistant and the Yandex Home app.

## Features

- **Device Discovery**: Automatically detects and registers all connected Tion devices
- **State Reporting**: Reports current device state including power, fan speed, temperature, and mode
- **Device Control**: Supports controlling all device functions:
  - Power on/off
  - Fan speed adjustment
  - Temperature control
  - Operation mode selection
- **Scenario Support**: Execute and manage device scenarios
- **OAuth Authentication**: Secure authentication using Yandex OAuth tokens

## API Endpoints

### Device Management

- `GET /devices` - List all available devices with their capabilities
- `POST /state` - Get current state of specified devices
- `POST /action` - Execute commands on devices

### Scenario Management

- `GET /scenarios` - List all available scenarios
- `POST /scenarios` - Execute a specific scenario

## Authentication

All API endpoints require authentication using a Yandex OAuth token. The token must be provided in the `Authorization` header as a Bearer token:

```
Authorization: Bearer <yandex_oauth_token>
```

The integration validates tokens with the Yandex OAuth service and caches valid tokens for one hour to reduce API calls.

## Device Capabilities

The integration exposes the following device capabilities to Yandex Smart Home:

### All Devices

- **on_off**: Power control (on/off)
- **fan_speed**: Fan speed control (1-6)

### Devices with Heaters (S3, S4)

- **temperature**: Temperature control (10-30°C)

### Devices with Mode Control (S3)

- **work_mode**: Operation mode selection:
  - `auto`: Automatic mode
  - `manual`: Manual mode (outside air)
  - `recirculation`: Recirculation mode

## Special Voice Commands

The integration supports special voice commands through predefined modes:

- **"Тихий режим"** (Quiet mode): Sets fan speed to 1
- **"Турбо режим"** (Turbo mode): Sets fan speed to 6
- **"Ночной режим"** (Night mode): Sets fan speed to 1 and turns off sound
- **"Проветривание"** (Ventilation): Sets fan speed to 4 and mode to outside air

## Error Handling

The API returns standard HTTP status codes:

- `200 OK`: Request successful
- `400 Bad Request`: Invalid request format
- `401 Unauthorized`: Missing authentication
- `403 Forbidden`: Invalid token
- `500 Internal Server Error`: Server-side error

## Running the Integration

Start the integration server with:

```bash
python yandex_api_integration.py
```

By default, the server runs on port 5000. In production, it's recommended to run behind a reverse proxy with HTTPS enabled.

## Development and Testing

The integration includes comprehensive test coverage. Run tests with:

```bash
pytest tests/unit/test_yandex_api_integration.py
```
