# ERNI Stream Downloader for Windows

Windows-версия ERNI Stream Downloader `1.7.0`.

Приложение скачивает ваши видео через `yt-dlp` и `ffmpeg`, а затем при необходимости делает совместимый `MP4` для обычных плееров и монтажных программ.

Используйте приложение только для своих видео или видео, на которые у вас есть разрешение.

## Что делает

- Скачивает видео/клипы с поддерживаемых `yt-dlp` платформ: YouTube, YouTube Shorts, TikTok, Instagram Reels/Posts, Twitch VOD/Clips, Vimeo, Facebook, X/Twitter, Reddit, VK/OK.
- Автоматически определяет платформу: `Detected: TikTok`, `Detected: Instagram Reels`, `Detected: YouTube Shorts`.
- Поддерживает очередь-таблицу: ссылка, платформа, статус, качество, примерный размер выбранного качества и прогресс.
- Очередь можно поставить на паузу после текущего файла и потом продолжить.
- Можно включить режим плейлистов/профилей с лимитом видео, чтобы не скачать слишком много случайно.
- Поддерживает drag-and-drop: можно перетащить ссылку или текст прямо в окно.
- Поддерживает переключение интерфейса `RU / EN`.
- Поддерживает `Smart preset`: приложение само предлагает режим под платформу.
- Есть быстрые режимы `Original`, `Universal`, `Reels`, `Audio`.
- Интерфейс прокручивается колесом/трекпадом, поэтому всё доступно даже на меньшем экране.
- Основные кнопки отделены от второстепенных инструментов, чтобы интерфейс не перегружал глаза.
- Поддерживает `Best available`, `1440p / 2K`, `1080p`, `720p`.
- Поддерживает `MP4` и `MKV`.
- Поддерживает режимы:
  - `Original quality` — лучшее доступное качество без перекодирования;
  - `Best quality MP4` — лучший MP4 для просмотра и отправки;
  - `For editing: universal` — главный preset “подойдёт куда угодно”;
  - `For editing: VEGAS Pro`;
  - `For editing: Premiere / DaVinci / CapCut`;
  - `For editing: Final Cut / macOS`;
  - `For TikTok / Reels / Shorts`;
  - `For archive`;
  - `Audio only`;
  - `Thumbnail only`.
- Автоматически анализирует видео перед скачиванием: платформа, название, thumbnail-превью, максимум качества, FPS, codecs, есть ли звук/картинка, длительность и примерный размер именно выбранного качества.
- Проверяет готовый файл после скачивания через `ffprobe`: есть ли картинка, звук, codec, FPS и resolution.
- После скачивания показывает карточку результата: есть ли видео, есть ли звук, codec, FPS, resolution и вердикт совместимости.
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
