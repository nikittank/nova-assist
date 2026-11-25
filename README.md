# Nova Assistant

### A personal AI operating layer for your Windows desktop

Nova is a voice-first desktop assistant designed to help you move from intention to action. Ask naturally, and Nova can understand the request, plan the next step, use the right desktop tool, and report what happened.

> **Do it now. Your future self will thank you.**

![Nova Assistant](novaassistant/assets/nova_icon.ico)

## What makes Nova different

Nova is more than a chat window. It is an AI workspace that connects conversation with useful desktop actions.

- **Natural conversation** — talk or type in plain language
- **AI tool calling** — Nova can choose and execute supported actions instead of only replying with text
- **Voice pipeline** — microphone input, speech recognition, reasoning, action execution, and spoken response
- **Live execution visibility** — follow listening, transcription, thinking, execution, and response states as they happen
- **Personal memory spaces** — manage notes, reminders, conversations, and activity locally
- **Desktop awareness** — browse files, open applications and links, and work with everyday desktop tasks
- **Always-available overlay** — keep Nova above other Windows applications while you work
- **Desktop widgets** — pin time, date, focus, notes, reminders, AI status, and activity widgets where you need them

## The Nova AI flow

```text
Speak or type
      ↓
Understand the request
      ↓
Plan the response or tool action
      ↓
Execute and verify
      ↓
Explain the result
```

Every operation is visible in the Activity audit stream, so you can see what Nova received, what it processed, which tool ran, and the final result.

## AI and voice capabilities

- Groq LLM integration for reasoning and tool calling
- Groq Whisper or Deepgram Nova for speech-to-text
- Deepgram Aura for text-to-speech
- Push-to-talk with `Ctrl+Space`
- Configurable voice and provider settings
- Friendly user-facing errors with technical details kept in the activity log

## A focused desktop workspace

Nova brings useful AI surfaces into one consistent Windows interface:

- **Conversation** — chat with a floating composer and clear user/assistant messages
- **Activity** — inspect the live execution audit stream
- **Notes** — create, edit, search, and organize personal notes
- **Reminders** — create, repeat, complete, snooze, and manage reminders
- **Files** — browse drives, search folders, and open local files
- **Widgets** — pin focused information to the desktop
- **Overlay** — keep Nova available while using other applications

## Privacy by design

Nova stores your local data in:

```text
%APPDATA%\\.nova-assistant\\
```

This includes configuration, notes, reminders, conversations, and activity history. API keys remain on your machine and are sent only to the provider you configure.

## Run Nova

Requirements: Windows 10 or later and Python 3.10+.

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
python main.py
```

You can also launch `start.bat` from Windows Explorer.

## Build the Windows executable

```powershell
.\\.venv\\Scripts\\Activate.ps1
pyinstaller NovaAssistant.spec
```

The executable is generated at:

```text
dist\\NovaAssistant.exe
```

The Nova application icon is stored at `novaassistant/assets/nova_icon.ico` and is included in the build.

## Test the application

```powershell
python selftest.py
```

## Project structure

```text
main.py                         Desktop application entry point
NovaAssistant.spec              Windows executable configuration
novaassistant/core/             AI orchestration and local data stores
novaassistant/providers/        Groq and Deepgram integrations
novaassistant/ui/               Desktop interface and pages
novaassistant/assets/           Nova icon and UI assets
```

## Status

Nova is an actively developed personal desktop assistant focused on practical AI actions, voice interaction, and a calm, productive Windows workspace.
