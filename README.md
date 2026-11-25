# Nova Assistant

Nova is a personal desktop assistant for Windows. It combines conversation, voice control, notes, reminders, file browsing, activity history, desktop widgets, and an always-on-top AI overlay in one focused application.

## Features

- Chat with Nova using text or voice
- Groq LLM integration with tool calling
- Speech-to-text and text-to-speech support
- Create, edit, search, and manage notes
- Create and manage reminders
- Browse and search local files and folders
- Live activity and execution audit stream
- Desktop widgets and a floating AI overlay
- Global push-to-talk shortcut: `Ctrl+Space`
- Dark, rounded Windows desktop interface

## Requirements

- Windows 10 or later
- Python 3.10 or later
- A working microphone for voice features
- API keys for the providers you want to use

## Run from source

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

Start Nova:

```powershell
python main.py
```

You can also run `start.bat` from Windows Explorer.

## Configuration and data

Nova stores configuration and local application data in:

```text
%APPDATA%\\.nova-assistant\\
```

This includes `config.json`, notes, reminders, conversation history, and activity logs. API keys are stored locally and are sent only to their configured provider.

Add or update provider keys from Nova's Settings page. No `.env` file is required.

## Build the Windows executable

Install the dependencies, then run:

```powershell
.\\.venv\\Scripts\\Activate.ps1
pyinstaller NovaAssistant.spec
```

The executable is created at:

```text
dist\\NovaAssistant.exe
```

The application icon is stored at `novaassistant/assets/nova_icon.ico` and is included in the executable build.

## Tests

Run the local checks with:

```powershell
python selftest.py
```

## Project structure

```text
main.py                         Application entry point
NovaAssistant.spec              Windows executable build configuration
requirements.txt                Python dependencies
novaassistant/config.py         Local configuration and data paths
novaassistant/core/             Assistant logic and data stores
novaassistant/providers/        Groq and Deepgram integrations
novaassistant/ui/               Desktop interface and pages
novaassistant/assets/           Application assets and icon
```

## Privacy

Nova is a local desktop application. Conversations, notes, reminders, and activity records are stored locally. Network requests are made only when using configured AI, speech, or voice providers.
