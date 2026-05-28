# ERNI Stream Downloader for Windows

Windows-версия ERNI Stream Downloader `1.1.0`.

Приложение скачивает ваши YouTube-стримы/видео через `yt-dlp` и `ffmpeg`, а затем делает совместимый `MP4` для обычных плееров и VEGAS Pro.

Используйте приложение только для своих видео или видео, на которые у вас есть разрешение.

## Что делает

- Скачивает YouTube-видео/стримы.
- Поддерживает `Best available`, `1440p / 2K`, `1080p`, `720p`.
- Поддерживает `MP4` и `MKV`.
- Для `MP4` делает совместимый файл:
  - H.264 video;
  - AAC audio;
  - CFR, constant frame rate;
  - 48 kHz stereo;
  - yuv420p.
- Это помогает избежать проблем “нет звука”, “нет картинки” и ошибок импорта в VEGAS Pro.
- Ведёт лог-файл для диагностики, если скачивание или конвертация упали.
- Проверяет YouTube-ссылку до запуска скачивания.
- Проверяет свободное место перед MP4-конвертацией.
- Имеет аккуратный desktop-интерфейс с карточками статуса, прогрессом, журналом и быстрым открытием логов.

## Для обычного пользователя

Если у вас уже есть готовый файл:

```text
ERNI Stream Downloader.exe
```

Python, `yt-dlp` и `ffmpeg` устанавливать не нужно. Просто откройте `.exe`.

Если Windows SmartScreen покажет предупреждение:

```text
More info -> Run anyway
```

## Сборка `.exe`

На компьютере, где собирается `.exe`, нужен Python 3.11+.

Установите Python:

```text
https://www.python.org/downloads/windows/
```

Во время установки включите:

```text
Add python.exe to PATH
```

Откройте PowerShell в папке проекта и выполните:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build_windows.ps1
```

Или из CMD:

```cmd
powershell -ExecutionPolicy Bypass -File build_windows.ps1
```

Готовый файл будет здесь:

```text
dist\ERNI Stream Downloader.exe
```

Его можно отправлять другим людям.

## Где лог

Если что-то пошло не так, приложение пишет лог сюда:

```text
%APPDATA%\ERNI Stream Downloader\app.log
```

Этот файл полезно прислать при отладке.

## Пример настроек

```text
Quality: 1440p / 2K
Format: MP4
Temporary local folder: enabled
```
