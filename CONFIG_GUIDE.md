# Configuration Guide

## Available Themes
- `classic-gold` - Classic Gold (default)
- `modern-blue` - Modern Blue
- `elegant-black` - Elegant Black  
- `liturgical-purple` - Liturgical Purple
- `festive-red` - Festive Red

## Available Font Combinations
- `cinzel-lora` - Cinzel + Lora (default)
- `roboto-open-sans` - Roboto + Open Sans
- `playfair-source` - Playfair + Source Sans Pro

## Configuration Options

### Branding Settings
- `branding.title`: Heading shown at the top of the display (default: `Church Calendar`)
- `branding.subtitle`: Line under the heading (default: `Upcoming Events • Next {days} Days`;
  `{days}` becomes `calendar.default_display_days`)
- `branding.page_title`: Browser tab title (default: `{title} - Calendar`)

Changes apply on the next page load; no restart is needed. The ⚙️ options menu also shows the
installed version (from `/etc/church-calendar/installed-version.json`, or `VERSION` on a checkout).

### Display Settings
- `slide_duration`: Slide transition time in seconds (default: 12)
- `theme`: Theme name (see list above)
- `font`: Font combination (see list above)
- `show_images`: Enable/disable image display (default: true)
- `max_images`: Maximum number of images to display (default: 7)

### Optimization Settings
- `enabled`: Enable image optimization (default: true)
- `quality`: Image quality percentage (default: 85)
- `max_width`: Maximum image width in pixels (default: 1920)
- `max_height`: Maximum image height in pixels (default: 1080)
- `thumbnail_size`: Thumbnail size in pixels (default: 32)
- `cleanup_orphaned`: Enable orphaned file cleanup (default: true)
- `cleanup_interval`: Cleanup interval in seconds (default: 3600)

### Calendar Settings
- `refresh_interval`: Calendar refresh interval in seconds (default: 300)
- `cache_enabled`: Enable calendar caching (default: true)
- `cache_file`: Cache file name (default: "calendar_cache.json")
- `cache_days`: How many days ahead to cache (default: 90). `calendar_cache.json`
  is consumed by LiveStreamScheduler, which cannot schedule further ahead than
  this window reaches.
- `default_display_days`: How many days ahead a display shows until its viewer picks a
  different number in the ⚙️ options menu (default: 10). Formerly `display_days`, which is
  still read if `default_display_days` is absent.
- `max_display_days`: The most days any display may choose (default: the default, so the
  menu offers no choice until you raise it). Never exceeds `cache_days`; a default above
  the maximum is lowered to it. The page's choice is stored in that browser only. It can
  also be set with `?days=N` on the page URL, like `?theme=`, `?font=`, `?speed=` and
  `?margins=`: the value is saved in the browser, the address bar is cleaned, and a value
  above the maximum is lowered to it.
- `max_events`: Maximum number of events to cache (default: 100)

### Local Files Settings
- `enabled`: Enable local file scanning (default: true)
- `folder_path`: Path to image folder (default: "./images/")
- `scan_interval`: File scan interval in seconds (default: 300)
- `file_extensions`: List of supported file extensions
- `recursive`: Scan subdirectories (default: true)