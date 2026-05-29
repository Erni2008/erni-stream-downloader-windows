# ERNI Stream Downloader for Windows

Windows-версия ERNI Stream Downloader `1.3.1`.

Приложение скачивает ваши YouTube-стримы/видео через `yt-dlp` и `ffmpeg`, а затем делает совместимый `MP4` для обычных плееров и VEGAS Pro.

Используйте приложение только для своих видео или видео, на которые у вас есть разрешение.

## Что делает

- Скачивает YouTube-видео/стримы.
- Поддерживает очередь-таблицу: ссылка, статус, качество, примерный размер выбранного качества и прогресс.
- Поддерживает `Best available`, `1440p / 2K`, `1080p`, `720p`.
- Поддерживает `MP4` и `MKV`.
- Поддерживает режимы:
  - `ВСЁ: максимально совместимый MP4` — главный preset “подойдёт куда угодно”: плееры, телефоны, соцсети, Premiere, DaVinci, CapCut, VEGAS, Final Cut;
  - `Смотреть в плеере (MP4, видео + звук)` — готовый файл для обычного просмотра;
  - `Монтаж: Premiere / DaVinci / CapCut` — универсальный MP4 для популярных редакторов;
  - `Монтаж: VEGAS Pro` — самый совместимый вариант для VEGAS;
  - `Монтаж: Final Cut / macOS` — MP4 для macOS/Final Cut;
  - `Архив: максимум качества без перекодирования` — максимально близко к YouTube-оригиналу.
- Автоматически анализирует видео перед скачиванием: максимум качества, FPS, длительность и примерный размер именно выбранного качества.
- Проверяет готовый файл после скачивания через `ffprobe`: есть ли картинка, звук, codec, FPS и resolution.
- Имеет историю загрузок: открыть файл, открыть папку, повторить ссылку.
- Может проверить любой готовый видеофайл кнопкой `Проверить файл`.
- Может починить готовое видео кнопкой `Починить видео`: создаёт universal MP4 для плееров и монтажных программ.
- Проверяет свободное место до начала скачивания.
- Может обновлять `yt-dlp` из интерфейса.
- Может проверить обновление самого приложения через GitHub Releases.
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

Если у вас уже есть готовый installer:

```text
ERNI Stream Downloader Setup.exe
```

Откройте его и установите приложение. Python, `yt-dlp` и `ffmpeg` устанавливать не нужно.

Если у вас только portable-файл:

```text
ERNI Stream Downloader.exe
```

его тоже можно просто открыть. Python, `yt-dlp` и `ffmpeg` устанавливать не нужно.

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

## Сборка installer

Для настоящего установщика поставьте Inno Setup:

```powershell
winget install JRSoftware.InnoSetup
```

Потом снова запустите:

```powershell
.\build_windows.ps1
```

Готовый installer будет здесь:

```text
installer-output\ERNI Stream Downloader Setup.exe
```

## Code signing

Для публикации в production нужен Windows code signing certificate. После покупки сертификата подпишите `.exe` и installer через `signtool`.

Пример:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "dist\ERNI Stream Downloader.exe"
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "installer-output\ERNI Stream Downloader Setup.exe"
```

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
